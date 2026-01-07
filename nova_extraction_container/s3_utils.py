"""
S3 client utilities for downloading and uploading tender documents.
"""
import json
from typing import List, Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

from config import Config
from logger import logger


class S3Client:
    """S3 client for tender document operations."""
    
    def __init__(self):
        """Initialize S3 client."""
        self.s3 = boto3.client('s3', region_name=Config.AWS_REGION)
        self.bucket = Config.S3_BUCKET_NAME
    
    def list_tender_files(self, tender_ref: str) -> List[str]:
        """
        List all files in tender folder.
        
        Args:
            tender_ref: Tender reference
            
        Returns:
            List of S3 keys
        """
        prefix = f"{Config.S3_SOURCE_PREFIX}{tender_ref}/"
        
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                logger.warning(f"No files found in {prefix}")
                return []
            
            files = [
                obj['Key'] for obj in response['Contents']
                if not obj['Key'].endswith('/')  # Exclude folder markers
            ]
            
            logger.info(f"Found {len(files)} files in {prefix}")
            return files
            
        except ClientError as e:
            logger.error(f"Error listing S3 files: {e}")
            raise
    
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Download file from S3.
        
        Args:
            s3_key: S3 object key
            local_path: Local file path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3.download_file(self.bucket, s3_key, local_path)
            logger.debug(f"Downloaded {s3_key} to {local_path}")
            return True
        except ClientError as e:
            logger.error(f"Error downloading {s3_key}: {e}")
            return False
    
    def upload_json(self, data: Dict[str, Any], s3_key: str, 
                    metadata: Optional[Dict[str, str]] = None) -> bool:
        """
        Upload JSON data to S3.
        
        Args:
            data: Dictionary to upload as JSON
            s3_key: S3 object key
            metadata: Optional metadata tags
            
        Returns:
            True if successful, False otherwise
        """
        try:
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            
            put_args = {
                'Bucket': self.bucket,
                'Key': s3_key,
                'Body': json_str.encode('utf-8'),
                'ContentType': 'application/json'
            }
            
            if metadata:
                put_args['Metadata'] = metadata
            
            self.s3.put_object(**put_args)
            logger.info(f"Uploaded JSON to {s3_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error uploading JSON to {s3_key}: {e}")
            return False
    
    def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from S3 (for rollback).
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info(f"Deleted {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting {s3_key}: {e}")
            return False
    
    def file_exists(self, s3_key: str) -> bool:
        """
        Check if file exists in S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if exists, False otherwise
        """
        try:
            self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except ClientError:
            return False

    def download_files(self, s3_keys: List[str], local_dir: str) -> List[str]:
        """
        Download multiple files from S3.
        
        Args:
            s3_keys: List of S3 object keys
            local_dir: Local directory to download to
            
        Returns:
            List of local file paths
        """
        import os
        local_paths = []
        
        for s3_key in s3_keys:
            filename = os.path.basename(s3_key)
            local_path = os.path.join(local_dir, filename)
            
            if self.download_file(s3_key, local_path):
                local_paths.append(local_path)
        
        return local_paths

