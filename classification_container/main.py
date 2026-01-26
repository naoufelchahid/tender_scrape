"""
Pipeline Stage: Classification Container
Main service - polls SQS, classifies documents, and injects headers
"""

import os
import json
import time
import logging
import boto3
from typing import Dict, Any, List

from src.config import Config
from src.classifier import DocumentClassifier
from src.document_splitter import split_concatenated_file, LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.bdp_extractor import identify_and_tag_french_boq

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
    
    def _upload_markdown(self, s3_key: str, content: str) -> None:
        """
        Upload classified markdown to S3.
        
        Args:
            s3_key: S3 object key
            content: Markdown content
        """
        try:
            self.s3.put_object(
                Bucket=Config.S3_BUCKET_NAME,
                Key=s3_key,
                Body=content.encode('utf-8'),
                ContentType='text/markdown'
            )
            logger.info(f"Uploaded classified markdown to {s3_key}")
        except Exception as e:
            logger.error(f"Failed to upload {s3_key}: {e}")
            raise
    
    def _inject_document_headers(self, docs: List[LogicalDocument]) -> str:
        """
        Inject document type headers and reconstruct markdown.
        
        Args:
            docs: List of classified LogicalDocument objects
            
        Returns:
            Reconstructed markdown with headers
        """
        markdown_parts = []
        
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
            
            # Inject headers and reconstruct markdown
            classified_markdown = self._inject_document_headers(docs)
            
            # Identify and tag BoQ tables
            logger.info("Running BoQ detection...")
            classified_markdown = identify_and_tag_french_boq(classified_markdown)
            
            # Generate output S3 key - REMOVE "_ocr" from filename as per user requirement
            # Example: markdown_tender/TEST_REF/TEST_REF_ocr.md → markdown_tender/TEST_REF/TEST_REF.md
            output_key = markdown_paths[0].replace('_ocr.md', '.md')
            
            # Upload classified markdown
            self._upload_markdown(output_key, classified_markdown)
            
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
