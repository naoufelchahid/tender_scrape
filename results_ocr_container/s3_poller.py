"""
S3 polling service for monitoring new files.

Stage: Extraction Container - OCR Processing
"""
import boto3
import time
from typing import List, Set, Dict, Optional
from datetime import datetime
from logger import logger
from config import Config


class S3Poller:
    """S3 polling service for detecting new files."""
    
    def __init__(self):
        """Initialize S3 poller."""
        self.s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
        self.bucket_name = Config.S3_BUCKET_NAME
        self.input_prefix = Config.INPUT_PREFIX
        self.processed_files: Set[str] = set()
        
        logger.info(f"Initialized S3 Poller for bucket: {self.bucket_name}")
        logger.info(f"Monitoring prefix: {self.input_prefix}")
    
    def list_files(self, prefix: str = None) -> List[Dict[str, any]]:
        """
        List all files in S3 prefix.
        
        Args:
            prefix: S3 prefix to list (default: INPUT_PREFIX)
            
        Returns:
            List of file metadata dictionaries
        """
        prefix = prefix or self.input_prefix
        
        try:
            files = []
            paginator = self.s3_client.get_paginator('list_objects_v2')
            
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Skip directory markers
                        if obj['Key'].endswith('/'):
                            continue
                        
                        # Check if file has supported extension
                        if any(obj['Key'].lower().endswith(ext) for ext in Config.SUPPORTED_EXTENSIONS):
                            files.append({
                                'key': obj['Key'],
                                'size': obj['Size'],
                                'last_modified': obj['LastModified']
                            })
            
            return files
        except Exception as e:
            logger.error(f"Error listing S3 files: {e}")
            return []
    
    def get_new_files(self) -> List[Dict[str, any]]:
        """
        Get list of new files that haven't been processed.
        
        Returns:
            List of new file metadata dictionaries
        """
        all_files = self.list_files()
        new_files = [f for f in all_files if f['key'] not in self.processed_files]
        
        if new_files:
            logger.info(f"Found {len(new_files)} new files to process")
        
        return new_files
    
    def mark_processed(self, file_key: str) -> None:
        """
        Mark a file as processed.
        
        Args:
            file_key: S3 key of the file
        """
        self.processed_files.add(file_key)
        logger.debug(f"Marked as processed: {file_key}")
    
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Download file from S3 to local path.
        
        Args:
            s3_key: S3 key of the file
            local_path: Local path to save file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Downloading: {s3_key} -> {local_path}")
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            return True
        except Exception as e:
            if "404" in str(e):
                logger.warning(f"File not found (404) in S3: {s3_key}")
            else:
                logger.error(f"Error downloading {s3_key}: {e}")
            return False
    
    def upload_file(self, local_path: str, s3_key: str, metadata: Dict[str, str] = None) -> bool:
        """
        Upload file to S3.
        
        Args:
            local_path: Local file path
            s3_key: S3 key to upload to
            metadata: Optional metadata to attach
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Uploading: {local_path} -> {s3_key}")
            extra_args = {}
            if metadata:
                extra_args['Metadata'] = metadata
            
            self.s3_client.upload_file(local_path, self.bucket_name, s3_key, ExtraArgs=extra_args)
            return True
        except Exception as e:
            logger.error(f"Error uploading to {s3_key}: {e}")
            return False
    
    def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from S3.
        
        Args:
            s3_key: S3 key of the file to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Deleting: {s3_key}")
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except Exception as e:
            logger.error(f"Error deleting {s3_key}: {e}")
            return False
    
    def move_file(self, source_key: str, dest_key: str) -> bool:
        """
        Move file within S3 (copy + delete).
        
        Args:
            source_key: Source S3 key
            dest_key: Destination S3 key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Copy
            copy_source = {'Bucket': self.bucket_name, 'Key': source_key}
            self.s3_client.copy_object(
                CopySource=copy_source,
                Bucket=self.bucket_name,
                Key=dest_key
            )
            
            # Delete original
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=source_key)
            
            logger.info(f"Moved: {source_key} -> {dest_key}")
            return True
        except Exception as e:
            logger.error(f"Error moving {source_key} to {dest_key}: {e}")
            return False
