"""
Main service for Results OCR processing.
Polls SQS, processes documents, uploads markdown and JSON.

Stage: Extraction Container - OCR Processing
"""
import os
import sys
import time
import json
import shutil
from pathlib import Path
from datetime import datetime

from config import Config
from logger import logger, log_s3_operation
from sqs_poller import SQSPoller
from s3_poller import S3Poller  # Keep for S3 operations
from document_processor import DocumentProcessor
from data_extractor import DataExtractor


class ResultsOCRService:
    """Main OCR service for processing tender results."""
    
    def __init__(self):
        """Initialize the OCR service."""
        self.sqs_poller = SQSPoller()
        self.s3_poller = S3Poller()  # Keep for S3 file operations
        self.document_processor = DocumentProcessor()
        self.data_extractor = DataExtractor()
        self.temp_dir = '/tmp/results_ocr'
        
        # Create temp directory
        os.makedirs(self.temp_dir, exist_ok=True)
        
        logger.info("Results OCR Service initialized (SQS-based with data extraction)")
        Config.print_config()
    
    def _get_local_path(self, s3_key: str) -> str:
        """
        Get local path for downloaded file.
        
        Args:
            s3_key: S3 key
            
        Returns:
            Local file path
        """
        filename = Path(s3_key).name
        return os.path.join(self.temp_dir, filename)
    
    def _get_output_key(self, s3_key: str) -> str:
        """
        Get output S3 key for markdown file.
        
        Args:
            s3_key: Original S3 key
            
        Returns:
            Output S3 key
        """
        filename = Path(s3_key).stem  # Filename without extension
        return f"{Config.OUTPUT_PREFIX}{filename}.md"
    
    def _cleanup_temp_file(self, file_path: str) -> None:
        """
        Clean up temporary file.
        
        Args:
            file_path: Path to file to clean up
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Cleaned up temp file: {file_path}")
        except Exception as e:
            logger.warning(f"Error cleaning up {file_path}: {e}")
    
    def _process_message(self, message: dict) -> bool:
        """
        Process a message from RESULTS_QUEUE.
        
        Args:
            message: Message dictionary with 'body' containing:
                - tender_ref: Tender reference
                - s3_paths: List of S3 keys for files
                - bucket: S3 bucket name
                
        Returns:
            True if successful, False otherwise
        """
        body = message['body']
        tender_ref = body.get('tender_ref')
        s3_paths = body.get('s3_paths', [])
        bucket = body.get('bucket', Config.S3_BUCKET_NAME)
        
        if not tender_ref or not s3_paths:
            logger.error(f"Invalid message format: {body}")
            return False
        
        try:
            logger.info("=" * 80)
            logger.info(f"Processing tender: {tender_ref}")
            logger.info(f"Files to process: {len(s3_paths)}")
            logger.info("=" * 80)
            
            markdown_parts = []
            processed_files = 0
            missing_files = 0
            
            for s3_key in s3_paths:
                try:
                    # Only process files from tender_results/ (not already processed ones from results_lambda_ocr/)
                    if not s3_key.startswith('tender_results/'):
                        logger.info(f"Skipping {s3_key} (not from tender_results/)")
                        continue
                    
                    logger.info(f"Processing file: {s3_key}")
                    
                    # Step 1: Download file
                    filename = Path(s3_key).name
                    local_path = os.path.join(self.temp_dir, filename)
                    
                    if not self.s3_poller.download_file(s3_key, local_path):
                        log_s3_operation('download', s3_key, 'failed')
                        missing_files += 1
                        continue
                    
                    log_s3_operation('download', s3_key, 'success')
                    
                    # Step 2: Process document
                    markdown_text, method = self.document_processor.process_document(local_path)
                    
                    # Add to combined markdown
                    markdown_parts.append(f"# File: {filename}\n\n{markdown_text}\n\n---\n\n")
                    processed_files += 1
                    
                    # Clean up temp file
                    self._cleanup_temp_file(local_path)
                    
                except Exception as e:
                    logger.error(f"Error processing file {s3_key}: {e}")
                    continue
            
            if not markdown_parts:
                if missing_files > 0:
                    logger.warning(f"All {missing_files} files for {tender_ref} were missing (404). Deleting message to avoid retries.")
                    return True
                logger.warning(f"No files were successfully processed for {tender_ref}")
                return False
            
            # Step 3: Combine all markdown and upload
            combined_markdown = "".join(markdown_parts)
            # Sanitize tender_ref for local naming
            safe_tender_ref = tender_ref.replace('/', '_').replace(' ', '_')
            markdown_local_path = os.path.join(self.temp_dir, f"{safe_tender_ref}_combined.md")
            
            with open(markdown_local_path, 'w', encoding='utf-8') as f:
                f.write(combined_markdown)
            
            # Upload to Results_markdown/markdown_files/
            output_key = f"{Config.MARKDOWN_PREFIX}{safe_tender_ref}.md"
            metadata = {
                'tender_ref': tender_ref.encode('ascii', 'ignore').decode('ascii'),
                'files_processed': str(processed_files),
                'processed_date': datetime.utcnow().isoformat(),
                'ocr_version': '1.0'
            }
            
            if not self.s3_poller.upload_file(markdown_local_path, output_key, metadata):
                log_s3_operation('upload', output_key, 'failed')
                return False
            
            log_s3_operation('upload', output_key, 'success')
            
            # Step 4: Extract structured data and generate JSON
            logger.info("Extracting structured data for database...")
            structured_data = self.data_extractor.extract_structured_data(combined_markdown, tender_ref)
            
            if structured_data:
                # Format for database
                db_records = self.data_extractor.format_for_database(structured_data, tender_ref)
                
                # Save JSON file
                json_filename = f"Results_{safe_tender_ref}.json"
                json_local_path = os.path.join(self.temp_dir, json_filename)
                
                with open(json_local_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'tender_reference': tender_ref,
                        'extracted_data': structured_data,
                        'database_records': db_records,
                        'metadata': {
                            'files_processed': processed_files,
                            'extraction_date': datetime.utcnow().isoformat(),
                            'version': '1.0'
                        }
                    }, f, indent=2, ensure_ascii=False)
                
                # Upload JSON to S3 (specific metadata folder)
                json_output_key = f"{Config.METADATA_PREFIX}{json_filename}"
                
                if self.s3_poller.upload_file(json_local_path, json_output_key):
                    log_s3_operation('upload', json_output_key, 'success')
                    logger.info(f"✅ Uploaded structured data JSON")
                    
                    # Send message to RESULTS_FILLER queue
                    if Config.RESULTS_FILLER_QUEUE_URL:
                        filler_message = {
                            'tender_reference': tender_ref,
                            'json_s3_key': json_output_key,
                            'json_s3_uri': f"s3://{Config.S3_BUCKET_NAME}/{json_output_key}",
                            'bucket': Config.S3_BUCKET_NAME,
                            'timestamp': datetime.utcnow().isoformat(),
                            'record_count': len(db_records)
                        }
                        
                        if self.sqs_poller.send_message(Config.RESULTS_FILLER_QUEUE_URL, filler_message):
                            logger.info(f"📨 Sent JSON file info to RESULTS_FILLER queue")
                        else:
                            logger.warning("Failed to send message to RESULTS_FILLER queue")
                    
                else:
                    log_s3_operation('upload', json_output_key, 'failed')
                
                # Clean up JSON temp file
                self._cleanup_temp_file(json_local_path)
            else:
                logger.warning("Failed to extract structured data - JSON not generated")
            
            # Step 5: Delete source files if configured
            if Config.DELETE_SOURCE_FILES:
                for s3_key in s3_paths:
                    if s3_key.startswith('tender_results/'):
                        if self.s3_poller.delete_file(s3_key):
                            log_s3_operation('delete', s3_key, 'success')
                        else:
                            log_s3_operation('delete', s3_key, 'failed')
            
            # Clean up temp markdown
            self._cleanup_temp_file(markdown_local_path)
            
            logger.info(f"✅ Successfully processed tender: {tender_ref} ({processed_files} files)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing tender {tender_ref}: {e}", exc_info=True)
            return False
    
    def run(self) -> None:
        """Main service loop - polls RESULTS_QUEUE for messages."""
        logger.info("=" * 80)
        logger.info("Starting Results OCR Service (SQS Mode)")
        logger.info("=" * 80)
        
        while True:
            try:
                # Receive message from RESULTS_QUEUE
                message = self.sqs_poller.receive_message()
                
                if not message:
                    # No messages available (after 20s long poll)
                    logger.debug("No messages in queue, continuing to poll...")
                    continue
                
                logger.info(f"Received message: {message['message_id']}")
                
                # Process the message
                success = self._process_message(message)
                
                # Delete message only if successful
                if success:
                    self.sqs_poller.delete_message(message['receipt_handle'])
                    logger.info("Message processed and deleted successfully")
                else:
                    logger.error("Message processing failed - will retry")
                    # Don't delete message - let it become visible again for retry
                
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(5)  # Brief pause before retrying


def main():
    """Main entry point."""
    try:
        service = ResultsOCRService()
        service.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
