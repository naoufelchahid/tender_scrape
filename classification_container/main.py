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
from src.document_splitter import split_concatenated_file, LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.hierarchy_restructurer import restructure_by_type
from src.missing_doc_detector import detect_missing_documents, extract_balised_documents

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
    
    def _generate_yaml_header(self, tender_ref: str, docs: List[LogicalDocument]) -> str:
        """
        Generate YAML frontmatter header with document type checklist.
        
        Args:
            tender_ref: Tender reference ID
            docs: List of classified LogicalDocument objects
            
        Returns:
            YAML frontmatter as string
        """
        # Get current timestamp in ISO format
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        # Build document checklist
        found_types = {doc.doc_type for doc in docs}
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
    
    def _generate_s3_metadata(self, docs: List[LogicalDocument]) -> Dict[str, str]:
        """
        Generate S3 metadata from document checklist.
        
        Args:
            docs: List of classified LogicalDocument objects
            
        Returns:
            Dictionary of S3 metadata
        """
        found_types = {doc.doc_type for doc in docs}
        metadata = {}
        
        for doc_type in ALL_DOCUMENT_TYPES:
            # S3 metadata keys must be lowercase and use hyphens
            # Format: doc-<type>: checked|missing
            key = f"doc-{doc_type.replace('_', '-')}"
            value = "checked" if doc_type in found_types else "missing"
            metadata[key] = value
        
        return metadata
    
    def _parse_existing_yaml_checklist(self, markdown: str) -> Set[str]:
        """
        Parse existing YAML header to extract already-checked document types.
        
        Args:
            markdown: Markdown content with YAML frontmatter
            
        Returns:
            Set of document types that are currently marked as 'checked'
        """
        lines = markdown.split('\n')
        
        # Find YAML boundaries
        if not lines or lines[0].strip() != '---':
            return set()
        
        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break
        
        if yaml_end == -1:
            return set()
        
        # Parse checklist
        checked_types = set()
        in_checklist = False
        
        for i in range(1, yaml_end):
            line = lines[i].strip()
            
            if line == 'document_checklist:':
                in_checklist = True
                continue
            
            if in_checklist and line.startswith(' '):
                # Parse: "  avis_fr: checked"
                parts = line.split(':', 1)
                if len(parts) == 2:
                    doc_type = parts[0].strip()
                    status = parts[1].strip()
                    if status == 'checked':
                        checked_types.add(doc_type)
        
        return checked_types
    
    def _update_yaml_header(
        self, markdown: str, tender_ref: str, newly_found_types: Set[str]
    ) -> str:
        """
        Update YAML header with newly detected document types.
        
        Only updates documents transitioning from missing → checked.
        Preserves existing checked status.
        
        Args:
            markdown: Markdown content with existing YAML header
            tender_ref: Tender reference ID
            newly_found_types: Document types newly detected
            
        Returns:
            Markdown with updated YAML header
        """
        # Parse existing checked types
        existing_checked = self._parse_existing_yaml_checklist(markdown)
        
        # Combine existing + newly found
        all_checked_types = existing_checked.union(newly_found_types)
        
        # Generate new YAML header
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        yaml_lines = [
            "---",
            f"tender_ref: {tender_ref}",
            f"classification_date: {timestamp}",
            "document_checklist:"
        ]
        
        for doc_type in ALL_DOCUMENT_TYPES:
            status = "checked" if doc_type in all_checked_types else "missing"
            yaml_lines.append(f"  {doc_type}: {status}")
        
        yaml_lines.append("---")
        yaml_lines.append("")  # Empty line after YAML
        
        new_yaml_header = '\n'.join(yaml_lines)
        
        # Replace existing YAML header
        lines = markdown.split('\n')
        if lines and lines[0].strip() == '---':
            # Find end of existing YAML
            yaml_end = -1
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    yaml_end = i
                    break
            
            if yaml_end != -1:
                # Remove old YAML header and prepend new one
                remaining_content = '\n'.join(lines[yaml_end + 1:])
                if remaining_content.startswith('\n'):
                    remaining_content = remaining_content[1:]
                return new_yaml_header + remaining_content
        
        # No existing YAML header, prepend new one
        return new_yaml_header + markdown
    
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
            key = f"doc-{doc_type.replace('_', '-')}"
            value = "checked" if doc_type in found_types else "missing"
            metadata[key] = value
        
        return metadata
    
    def _inject_document_headers(self, tender_ref: str, docs: List[LogicalDocument]) -> str:
        """
        Inject document type headers and reconstruct markdown.
        
        Args:
            tender_ref: Tender reference ID
            docs: List of classified LogicalDocument objects
            
        Returns:
            Reconstructed markdown with YAML header and document headers
        """
        markdown_parts = []
        
        # Add YAML frontmatter header at the beginning
        yaml_header = self._generate_yaml_header(tender_ref, docs)
        markdown_parts.append(yaml_header)
        
        for doc in docs:
            # Add file header
            markdown_parts.append(f"# File: {doc.original_filename}\n\n")
            
            # Inject document type header
            markdown_parts.append(f"> Document Type: {doc.doc_type}\n\n")
            
            # Add content
            markdown_parts.append(doc.content)
            
            # Add separator
            markdown_parts.append("\n\n---\n\n")
        
        # Join and remove trailing separator
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
            
            # Download and concatenate all markdown files
            markdown_parts = []
            for md_path in markdown_paths:
                content = self._download_markdown(md_path)
                markdown_parts.append(content)
            
            full_markdown = "\n\n---\n\n".join(markdown_parts)
            
            # Split into logical documents
            docs = split_concatenated_file(full_markdown)
            logger.info(f"Split into {len(docs)} logical documents")
            
            # Classify each document
            for doc in docs:
                result = self.classifier.classify(doc.original_filename, doc.content)
                doc.doc_type = result.doc_type
                logger.info(
                    f"  '{doc.original_filename}' → {result.doc_type} "
                    f"(step {result.step}, confidence: {result.confidence})"
                )
            
            # Inject headers and reconstruct markdown (with YAML frontmatter)
            classified_markdown = self._inject_document_headers(tender_ref, docs)
            
            # Restructure hierarchy based on document type
            logger.info("Restructuring markdown hierarchy based on document types...")
            classified_markdown = restructure_by_type(classified_markdown)
            
            # Detect missing documents in the entire markdown (includes BDP detection now)
            logger.info("Searching for missing document types in entire markdown...")
            found_types = {doc.doc_type for doc in docs}
            classified_markdown, newly_found_types = detect_missing_documents(
                classified_markdown, found_types
            )
            
            if newly_found_types:
                logger.info(f"✓ Detected missing document types: {', '.join(newly_found_types)}")
                
                # Extract balised content and create LogicalDocument objects
                logger.info("Extracting balised content as classified documents...")
                classified_markdown, extracted_docs = extract_balised_documents(classified_markdown)
                
                if extracted_docs:
                    logger.info(f"✓ Extracted {len(extracted_docs)} document(s) from balised content")
                    
                    # Merge extracted documents with original documents
                    all_docs = docs + extracted_docs
                    
                    # Regenerate complete markdown with ALL documents (original + extracted)
                    logger.info("Regenerating markdown with extracted documents...")
                    classified_markdown = self._inject_document_headers(tender_ref, all_docs)
                    
                    # Generate and prepend YAML header
                    yaml_header = self._generate_yaml_header(tender_ref, all_docs)
                    classified_markdown = yaml_header + "\n\n" + classified_markdown
                    
                    # Re-running hierarchy restructuring only
                    logger.info("Re-running hierarchy restructuring on complete markdown...")
                    classified_markdown = restructure_by_type(classified_markdown)
                    
                    # Generate S3 metadata from ALL documents (original + extracted)
                    all_found_types = {doc.doc_type for doc in all_docs}
                    s3_metadata = self._generate_s3_metadata_from_types(all_found_types)
                    
                    logger.info(
                        f"✓ Complete document set: {len(all_docs)} documents "
                        f"({len(docs)} original + {len(extracted_docs)} extracted)"
                    )
                else:
                    logger.info("No documents extracted from balises (balised sections may be empty)")
                    # Use newly found types for metadata update only
                    all_found_types = found_types.union(newly_found_types)
                    s3_metadata = self._generate_s3_metadata_from_types(all_found_types)
            else:
                logger.info("No additional missing documents detected")
                # Use original classification results
                s3_metadata = self._generate_s3_metadata(docs)

            
            # Generate output S3 key - REMOVE "_ocr" from filename as per user requirement
            # Example: markdown_tender/TEST_REF/TEST_REF_ocr.md → markdown_tender/TEST_REF/TEST_REF.md
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
            logger.info(f"✓ Successfully processed {tender_ref}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
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
