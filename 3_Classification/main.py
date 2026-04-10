"""
Pipeline Stage: Classification Container
Main service - polls SQS, classifies documents, and injects headers
"""

import os
import json
import time
import logging
import boto3
from datetime import datetime
from typing import Dict, Any, List, Set

from src.config import Config
from src.classifier import DocumentClassifier
from src.segmentation_engine import SegmentationEngine, Segment
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.hierarchy_restructurer import restructure_by_type
from monitor import enter as mon_enter, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly

def _get_active_batch_id():
    try:
        import sqlite3
        from monitor import _db_path
        with sqlite3.connect(str(_db_path()), timeout=5) as conn:
            row = conn.execute(
                "SELECT batch_id FROM events WHERE event='batch_start' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None


# All possible document types for integrity checklist
ALL_DOCUMENT_TYPES = [
    "avis_fr",
    "avis_ar",
    "administrative",
    "specification",
    "product",
    "acte_engagement",
    "declaration",
    "annexe"
]

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load env vars for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class ClassificationService:
    """Main classification service."""
    
    def __init__(self):
        """Initialize classification service."""
        # Validate configuration
        if not Config.validate():
            raise ValueError("Invalid configuration. Check environment variables.")
        
        Config.print_config()
        
        # AWS clients
        self.sqs = boto3.client('sqs', region_name=Config.AWS_REGION)
        self.s3 = boto3.client('s3', region_name=Config.AWS_REGION)
        
        # OpenRouter client for Step 3
        self.openrouter_client = OpenRouterClientWrapper(api_key=Config.OPENROUTER_API_KEY)
        
        # Document classifier
        self.classifier = DocumentClassifier(openrouter_client=self.openrouter_client)
        
        # Segmentation engine
        self.segmenter = SegmentationEngine()
        
        logger.info("Classification Service initialized successfully")
    
    def _download_markdown(self, s3_key: str) -> str:
        """
        Download markdown file from S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            Markdown content as string
        """
        try:
            response = self.s3.get_object(Bucket=Config.S3_BUCKET_NAME, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            logger.info(f"Downloaded {s3_key}: {len(content):,} characters")
            return content
        except Exception as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            raise
    
    def _upload_markdown(self, s3_key: str, content: str, metadata: Dict[str, str] = None) -> None:
        """
        Upload classified markdown to S3.
        
        Args:
            s3_key: S3 object key
            content: Markdown content
            metadata: Optional S3 metadata dictionary
        """
        try:
            put_params = {
                'Bucket': Config.S3_BUCKET_NAME,
                'Key': s3_key,
                'Body': content.encode('utf-8'),
                'ContentType': 'text/markdown'
            }
            
            # Add metadata if provided
            if metadata:
                put_params['Metadata'] = metadata
            
            self.s3.put_object(**put_params)
            logger.info(f"Uploaded classified markdown to {s3_key}")
            if metadata:
                logger.info(f"  with metadata: {metadata}")
        except Exception as e:
            logger.error(f"Failed to upload {s3_key}: {e}")
            raise
    
    def _generate_yaml_header(self, tender_ref: str, segments: List[Segment]) -> str:
        """
        Generate YAML frontmatter header with document type checklist.
        
        Args:
            tender_ref: Tender reference ID
            segments: List of classified Segment objects
            
        Returns:
            YAML frontmatter as string
        """
        # Get current timestamp in ISO format
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        # Build document checklist
        found_types = {seg.doc_type for seg in segments}
        checklist = {}
        for doc_type in ALL_DOCUMENT_TYPES:
            checklist[doc_type] = "checked" if doc_type in found_types else "missing"
        
        # Build YAML header
        yaml_lines = [
            "---",
            f"tender_ref: {tender_ref}",
            f"classification_date: {timestamp}",
            "document_checklist:"
        ]
        
        for doc_type in ALL_DOCUMENT_TYPES:
            yaml_lines.append(f"  {doc_type}: {checklist[doc_type]}")
        
        yaml_lines.append("---")
        yaml_lines.append("")  # Empty line after YAML header
        
        return "\n".join(yaml_lines)
    
    def _generate_s3_metadata_from_types(self, found_types: Set[str]) -> Dict[str, str]:
        """
        Generate S3 metadata from set of found document types.
        
        Args:
            found_types: Set of document types that are present
            
        Returns:
            Dictionary of S3 metadata
        """
        metadata = {}
        
        for doc_type in ALL_DOCUMENT_TYPES:
            # S3 metadata keys must be lowercase and use hyphens
            # Format: doc-<type>: checked|missing
            key = f"doc-{doc_type.replace('_', '-')}"
            value = "checked" if doc_type in found_types else "missing"
            metadata[key] = value
        
        return metadata
    
    def _inject_segment_headers(self, tender_ref: str, segments: List[Segment]) -> str:
        """
        Inject segment headers and reconstruct markdown with YAML frontmatter.
        
        Args:
            tender_ref: Tender reference ID
            segments: List of classified Segment objects
            
        Returns:
            Reconstructed markdown
        """
        # Build YAML header
        yaml_header = self._generate_yaml_header(tender_ref, segments)
        
        # Build document sections
        markdown_parts = [yaml_header]
        
        for i, seg in enumerate(segments):
            filename = f"segment_{i+1}_{seg.doc_type}.md"
            markdown_parts.append(f"# File: {filename}\n\n")
            markdown_parts.append(f"> Document Type: {seg.doc_type}\n\n")
            markdown_parts.append(seg.content)
            markdown_parts.append("\n\n---\n\n")
        
        result = "".join(markdown_parts)
        if result.endswith("\n\n---\n\n"):
            result = result[:-7]
        
        return result
    
    def _process_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a single SQS message.
        
        Args:
            message: SQS message dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            body = json.loads(message['Body'])
            tender_ref = body.get('tender_ref')
            markdown_paths = body.get('markdown_paths', [])
            
            if not tender_ref or not markdown_paths:
                logger.error(f"Invalid message format: {body}")
                return False
            
            logger.info(f"Processing tender: {tender_ref}")
            batch_id = _get_active_batch_id()
            if batch_id:
                mon_enter(batch_id, tender_ref, "classification")

            # Download and concatenate all markdown files
            markdown_parts = []
            for md_path in markdown_paths:
                content = self._download_markdown(md_path)
                markdown_parts.append(content)
            
            full_markdown = "\n\n---\n\n".join(markdown_parts)
            
            # Run 4-pass segmentation pipeline
            segments = self.segmenter.segment_and_classify(full_markdown, self.classifier)
            logger.info(f"Segmentation produced {len(segments)} segments")
            
            for seg in segments:
                logger.info(
                    f"  [{seg.start_line}-{seg.end_line}] {seg.doc_type} "
                    f"(conf={seg.confidence:.2f}, method={seg.method})"
                )
            
            # Reconstruct markdown with document headers and YAML frontmatter
            classified_markdown = self._inject_segment_headers(tender_ref, segments)
            
            # Restructure hierarchy based on document type
            logger.info("Restructuring markdown hierarchy based on document types...")
            classified_markdown = restructure_by_type(classified_markdown)
            
            # Detect anomalies: missing expected document types
            EXPECTED_TYPES = {"avis_fr", "avis_ar", "administrative", "specification", "product"}
            final_types = {seg.doc_type for seg in segments}
            missing_types = EXPECTED_TYPES - final_types
            if missing_types and batch_id:
                mon_anomaly(batch_id, tender_ref, "classification",
                            [f"missing_doc_type:{t}" for t in sorted(missing_types)])
            
            # Generate S3 metadata
            s3_metadata = self._generate_s3_metadata_from_types(final_types)
            
            # Generate output S3 key
            output_key = markdown_paths[0].replace('_ocr.md', '.md')
            
            # Upload classified markdown with metadata
            self._upload_markdown(output_key, classified_markdown, metadata=s3_metadata)
            
            # Send message to EXTRACTION_QUEUE
            extraction_message = {
                'tender_ref': tender_ref,
                'markdown_paths': [output_key],
                'classification_complete': True
            }
            
            self.sqs.send_message(
                QueueUrl=Config.EXTRACTION_QUEUE_URL,
                MessageBody=json.dumps(extraction_message)
            )
            logger.info(f"Sent message to EXTRACTION_QUEUE for {tender_ref}")
            
            # Delete message from CLASSIFICATION_QUEUE
            self.sqs.delete_message(
                QueueUrl=Config.CLASSIFICATION_QUEUE_URL,
                ReceiptHandle=message['ReceiptHandle']
            )
            logger.info(f"Successfully processed {tender_ref}")
            if batch_id:
                mon_complete(
                    batch_id, tender_ref, "classification",
                    doc_count=len(segments),
                )

            return True
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            if 'batch_id' in locals() and batch_id:
                mon_failed(batch_id, tender_ref, "classification", error=str(e))
            return False
    
    def run(self) -> None:
        """Main service loop."""
        logger.info(f"Starting classification service polling {Config.CLASSIFICATION_QUEUE_URL}")
        
        while True:
            try:
                # Poll SQS
                response = self.sqs.receive_message(
                    QueueUrl=Config.CLASSIFICATION_QUEUE_URL,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20
                )
                
                if 'Messages' not in response:
                    continue
                
                for message in response['Messages']:
                    self._process_message(message)
                    
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(5)


def main():
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("Classification Container Starting")
    logger.info("=" * 50)
    
    service = ClassificationService()
    service.run()


if __name__ == "__main__":
    main()
