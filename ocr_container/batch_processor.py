"""
Batch processor for existing tenders in S3.
Scans S3 for unprocessed tenders and sends them to OCR queue.
"""
import argparse
import time
from typing import List, Set
from datetime import datetime

from config import Config
from logger import logger
from s3_utils import S3Client
from sqs_utils import SQSClient


class BatchProcessor:
    """Batch processor for existing tenders."""
    
    def __init__(self, dry_run: bool = False, limit: int = None):
        """
        Initialize batch processor.
        
        Args:
            dry_run: If True, don't send messages to SQS
            limit: Maximum number of tenders to process
        """
        self.s3_client = S3Client()
        self.sqs_client = SQSClient()
        self.dry_run = dry_run
        self.limit = limit
        
        logger.info(f"Batch processor initialized (dry_run={dry_run}, limit={limit})")
    
    def _get_processed_tenders(self) -> Set[str]:
        """
        Get set of already processed tender references.
        
        Returns:
            Set of tender references that have markdown files
        """
        logger.info("Checking for already processed tenders...")
        
        # List all folders in markdown_tender/
        processed_tenders = set()
        
        try:
            # List all files in markdown prefix
            markdown_files = self.s3_client.list_files(
                prefix=f"{Config.MARKDOWN_PREFIX}/",
                extensions=('.md',)
            )
            
            # Extract tender_refs from paths like "markdown_tender/REF123/REF123_ocr.md"
            for file_path in markdown_files:
                parts = file_path.split('/')
                if len(parts) >= 2:
                    tender_ref = parts[1]
                    processed_tenders.add(tender_ref)
            
            logger.info(f"Found {len(processed_tenders)} already processed tenders")
            return processed_tenders
        except Exception as e:
            logger.error(f"Error getting processed tenders: {e}")
            return set()
    
    def _get_unprocessed_tenders(self) -> List[str]:
        """
        Get list of unprocessed tender references.
        
        Returns:
            List of tender references that need processing
        """
        logger.info("Finding unprocessed tenders...")
        
        # Get all tender folders
        all_tenders = self.s3_client.list_tender_folders()
        logger.info(f"Found {len(all_tenders)} total tender folders")
        
        # Get processed tenders
        processed_tenders = self._get_processed_tenders()
        
        # Find unprocessed
        unprocessed = [t for t in all_tenders if t not in processed_tenders]
        logger.info(f"Found {len(unprocessed)} unprocessed tenders")
        
        # Apply limit if specified
        if self.limit and len(unprocessed) > self.limit:
            unprocessed = unprocessed[:self.limit]
            logger.info(f"Limited to {self.limit} tenders")
        
        return unprocessed
    
    def _get_tender_files(self, tender_ref: str) -> List[str]:
        """
        Get list of supported files for a tender.
        
        Args:
            tender_ref: Tender reference
            
        Returns:
            List of S3 keys for supported files
        """
        prefix = f"{Config.FINAL_DOC_PREFIX}/{tender_ref}/"
        
        files = self.s3_client.list_files(
            prefix=prefix,
            extensions=Config.SUPPORTED_EXTENSIONS
        )
        
        return files
    
    def _send_to_queue(self, tender_ref: str, s3_paths: List[str]) -> bool:
        """
        Send tender to OCR queue.
        
        Args:
            tender_ref: Tender reference
            s3_paths: List of S3 keys
            
        Returns:
            True if successful, False otherwise
        """
        if not s3_paths:
            logger.warning(f"No files to process for {tender_ref}")
            return False
        
        # Create message
        message = {
            'tender_ref': tender_ref,
            's3_paths': s3_paths,
            'batch_timestamp': datetime.utcnow().isoformat()
        }
        
        if self.dry_run:
            logger.info(f"DRY RUN: Would send message for {tender_ref} with {len(s3_paths)} files")
            return True
        
        # Send to queue
        success = self.sqs_client.send_message(message, queue_url=Config.OCR_QUEUE_URL)
        
        if success:
            logger.info(f"Sent {tender_ref} to OCR queue with {len(s3_paths)} files")
        else:
            logger.error(f"Failed to send {tender_ref} to OCR queue")
        
        return success
    
    def process(self) -> None:
        """
        Process all unprocessed tenders.
        """
        logger.info("=" * 50)
        logger.info("Starting batch processing")
        logger.info("=" * 50)
        
        # Get unprocessed tenders
        unprocessed_tenders = self._get_unprocessed_tenders()
        
        if not unprocessed_tenders:
            logger.info("No unprocessed tenders found")
            return
        
        # Process each tender
        total = len(unprocessed_tenders)
        success_count = 0
        error_count = 0
        
        for i, tender_ref in enumerate(unprocessed_tenders, 1):
            logger.info(f"Processing tender {i}/{total}: {tender_ref}")
            
            try:
                # Get files
                files = self._get_tender_files(tender_ref)
                
                if not files:
                    logger.warning(f"No supported files found for {tender_ref}")
                    continue
                
                # Send to queue
                if self._send_to_queue(tender_ref, files):
                    success_count += 1
                else:
                    error_count += 1
                
                # Brief pause to avoid rate limiting
                if not self.dry_run:
                    time.sleep(0.5)
            
            except Exception as e:
                logger.error(f"Error processing {tender_ref}: {e}")
                error_count += 1
        
        # Summary
        logger.info("=" * 50)
        logger.info("Batch processing complete")
        logger.info(f"Total tenders: {total}")
        logger.info(f"Successfully queued: {success_count}")
        logger.info(f"Errors: {error_count}")
        logger.info("=" * 50)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Batch process existing tenders')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Dry run mode (no messages sent)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of tenders to process')
    
    args = parser.parse_args()
    
    processor = BatchProcessor(dry_run=args.dry_run, limit=args.limit)
    processor.process()


if __name__ == '__main__':
    main()
