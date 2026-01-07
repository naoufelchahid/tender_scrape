"""
Main OCR service script.
Polls SQS queue, processes tender documents, and uploads markdown to S3.
"""
import os
import time
import shutil
from typing import List, Dict, Any
from datetime import datetime

from config import Config
from logger import logger, log_processing_start, log_processing_complete, log_processing_error, log_file_processing
from s3_utils import S3Client
from sqs_utils import SQSClient
from processors import get_processor, get_file_type, is_supported_file


class OCRService:
    """Main OCR service class."""
    
    def __init__(self):
        """Initialize OCR service."""
        self.s3_client = S3Client()
        self.sqs_client = SQSClient()
        self.temp_dir = '/app/temp'
        
        # Create temp directory
        os.makedirs(self.temp_dir, exist_ok=True)
        
        logger.info("OCR Service initialized")
        Config.print_config()
    
    def _cleanup_temp_files(self, tender_ref: str) -> None:
        """
        Clean up temporary files for a tender.
        
        Args:
            tender_ref: Tender reference
        """
        tender_temp_dir = os.path.join(self.temp_dir, tender_ref)
        if os.path.exists(tender_temp_dir):
            shutil.rmtree(tender_temp_dir)
            logger.info(f"Cleaned up temp files for {tender_ref}")
    
    def _download_tender_files(self, tender_ref: str, s3_paths: List[str]) -> List[str]:
        """
        Download tender files from S3.
        Handles both individual file paths and folder paths.
        
        Args:
            tender_ref: Tender reference
            s3_paths: List of S3 keys (can be files or folders)
            
        Returns:
            List of local file paths
        """
        tender_temp_dir = os.path.join(self.temp_dir, tender_ref)
        os.makedirs(tender_temp_dir, exist_ok=True)
        
        local_paths = []
        all_s3_file_keys = [] # This will store all actual file keys to download
        
        for s3_item_path in s3_paths:
            # Check if this is a folder path (ends with /)
            if s3_item_path.endswith('/'):
                logger.info(f"Detected folder path: {s3_item_path}, listing contents...")
                # List ALL files in folder (Lambda sanitizes filenames, so extensions may not have dots)
                file_keys = self.s3_client.list_files(s3_item_path)
                
                if not file_keys:
                    logger.warning(f"No files found in folder {s3_item_path}")
                else:
                    all_s3_file_keys.extend(file_keys)
            else:
                # It's a single file path
                all_s3_file_keys.append(s3_item_path)
        
        # Now, download all collected file keys
        for s3_key in all_s3_file_keys:
            # Get filename from S3 key
            filename = os.path.basename(s3_key)
            local_path = os.path.join(tender_temp_dir, filename)
            
            # Download file
            if self.s3_client.download_file(s3_key, local_path):
                local_paths.append(local_path)
            else:
                logger.warning(f"Failed to download {s3_key}")
        
        return local_paths
    
    def _process_file(self, file_path: str, tender_ref: str) -> str:
        """
        Process single file and return markdown.
        
        Args:
            file_path: Path to file
            tender_ref: Tender reference
            
        Returns:
            Markdown text
        """
        # Get file type
        file_type = get_file_type(file_path)
        
        if not file_type:
            logger.warning(f"Unsupported file type: {file_path}")
            return f"[UNSUPPORTED FILE: {os.path.basename(file_path)}]"
        
        log_file_processing(tender_ref, file_path, file_type, "started")
        
        try:
            # Get processor and process
            processor = get_processor(file_path)
            markdown_text = processor(file_path)
            
            log_file_processing(tender_ref, file_path, file_type, "completed")
            return markdown_text
        except Exception as e:
            log_file_processing(tender_ref, file_path, file_type, "failed")
            logger.error(f"Error processing {file_path}: {e}")
            return f"[ERROR PROCESSING: {os.path.basename(file_path)}]\n{str(e)}"
    
    def _upload_markdown(self, tender_ref: str, markdown_text: str) -> bool:
        """
        Upload markdown to S3.
        
        Args:
            tender_ref: Tender reference
            markdown_text: Markdown content
            
        Returns:
            True if successful, False otherwise
        """
        # Create local markdown file
        # Replace slashes with underscores in tender_ref for S3 path
        tender_ref_safe = tender_ref.replace('/', '_')
        markdown_filename = f"{tender_ref_safe}_ocr.md"
        local_markdown_path = os.path.join(self.temp_dir, markdown_filename)
        
        with open(local_markdown_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        
        # Upload to S3 - single folder with tender_ref_safe
        s3_key = f"{Config.MARKDOWN_PREFIX}/{tender_ref_safe}/{markdown_filename}"
        
        metadata = {
            'tender_ref': tender_ref,
            'processed_date': datetime.utcnow().isoformat(),
            'ocr_version': '1.0'
        }
        
        success = self.s3_client.upload_file(local_markdown_path, s3_key, metadata)
        
        # Cleanup local file
        os.remove(local_markdown_path)
        
        return success
    
    def _process_tender(self, message_body: Dict[str, Any]) -> bool:
        """
        Process tender documents from SQS message.
        
        Args:
            message_body: SQS message body
            
        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()
        
        tender_ref = message_body.get('tender_ref')
        s3_paths = message_body.get('s3_paths', [])
        
        if not tender_ref or not s3_paths:
            logger.error("Invalid message format: missing tender_ref or s3_paths")
            return False
        
        log_processing_start(tender_ref, len(s3_paths))
        
        try:
            # Download files
            local_paths = self._download_tender_files(tender_ref, s3_paths)
            
            if not local_paths:
                logger.error(f"No files downloaded for {tender_ref}")
                return False
            
            # Process each file
            markdown_parts = []
            
            for local_path in local_paths:
                if not is_supported_file(local_path):
                    logger.warning(f"Skipping unsupported file: {local_path}")
                    continue
                
                filename = os.path.basename(local_path)
                markdown_parts.append(f"# File: {filename}\n\n")
                
                file_markdown = self._process_file(local_path, tender_ref)
                markdown_parts.append(file_markdown)
                markdown_parts.append("\n\n---\n\n")
            
            # Combine all markdown
            final_markdown = "".join(markdown_parts)
            
            # Upload to S3
            if not self._upload_markdown(tender_ref, final_markdown):
                logger.error(f"Failed to upload markdown for {tender_ref}")
                return False
            
            # Send completion message to EXTRACTION_QUEUE
            tender_ref_safe = tender_ref.replace('/', '_')
            extraction_message = {
                'tender_ref': tender_ref,
                'markdown_paths': [f"{Config.MARKDOWN_PREFIX}/{tender_ref_safe}/{tender_ref_safe}_ocr.md"]
            }
            
            if not self.sqs_client.send_message(extraction_message):
                logger.error(f"Failed to send extraction queue message for {tender_ref}")
                return False
            
            # Cleanup
            self._cleanup_temp_files(tender_ref)
            
            # Log completion
            processing_time = time.time() - start_time
            log_processing_complete(tender_ref, processing_time, len(local_paths))
            
            return True
        except Exception as e:
            log_processing_error(tender_ref, e)
            self._cleanup_temp_files(tender_ref)
            return False
    
    def run(self) -> None:
        """
        Main service loop.
        Continuously polls SQS queue and processes messages.
        """
        logger.info("Starting OCR service main loop")
        
        while True:
            try:
                # Receive message
                message = self.sqs_client.receive_message()
                
                if not message:
                    # No messages, continue polling
                    continue
                
                logger.info(f"Processing message: {message['message_id']}")
                
                # Process tender
                success = self._process_tender(message['body'])
                
                # Delete message only if successful
                if success:
                    self.sqs_client.delete_message(message['receipt_handle'])
                    logger.info("Message processed and deleted successfully")
                else:
                    logger.error("Message processing failed, will retry")
                    # Don't delete message - let it become visible again for retry
            
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(5)  # Brief pause before retrying


def main():
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("OCR Service Starting")
    logger.info("=" * 50)
    
    service = OCRService()
    service.run()


if __name__ == '__main__':
    main()
