"""
S3 utility functions for file operations.
Handles downloads, uploads, and file listing.
"""
import os
from typing import List, Optional
import boto3
from botocore.exceptions import ClientError
from config import Config
from logger import logger


class S3Client:
    """S3 client wrapper with error handling and retries."""
    
    def __init__(self):
        """Initialize S3 client."""
        self.client = boto3.client('s3', region_name=Config.AWS_REGION)
        self.bucket = Config.S3_BUCKET_NAME
    
    def download_file(self, key: str, local_path: str) -> bool:
        """
        Download file from S3.
        
        Args:
            key: S3 object key
            local_path: Local file path to save to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            logger.info(f"Downloading s3://{self.bucket}/{key} to {local_path}")
            self.client.download_file(self.bucket, key, local_path)
            logger.info(f"Successfully downloaded {key}")
            return True
        except ClientError as e:
            logger.error(f"Error downloading {key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading {key}: {e}")
            return False
    
    def upload_file(self, local_path: str, key: str, metadata: Optional[dict] = None) -> bool:
        """
        Upload file to S3.
        
        Args:
            local_path: Local file path to upload
            key: S3 object key
            metadata: Optional metadata dict
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Uploading {local_path} to s3://{self.bucket}/{key}")
            
            extra_args = {}
            if metadata:
                extra_args['Metadata'] = metadata
            
            self.client.upload_file(local_path, self.bucket, key, ExtraArgs=extra_args)
            logger.info(f"Successfully uploaded {key}")
            return True
        except ClientError as e:
            logger.error(f"Error uploading {key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error uploading {key}: {e}")
            return False
    
    def list_files(self, prefix: str, extensions: Optional[tuple] = None) -> List[str]:
        """
        List files in S3 prefix.
        
        Args:
            prefix: S3 prefix to list
            extensions: Optional tuple of file extensions to filter
            
        Returns:
            List of S3 keys
        """
        try:
            logger.info(f"Listing files in s3://{self.bucket}/{prefix}")
            
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            
            files = []
            for page in pages:
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    key = obj['Key']
                    
                    # Filter by extensions if provided
                    if extensions:
                        if not any(key.lower().endswith(ext) for ext in extensions):
                            continue
                    
                    files.append(key)
            
            logger.info(f"Found {len(files)} files in {prefix}")
            return files
        except ClientError as e:
            logger.error(f"Error listing files in {prefix}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing files in {prefix}: {e}")
            return []
    
    def file_exists(self, key: str) -> bool:
        """
        Check if file exists in S3.
        
        Args:
            key: S3 object key
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            logger.error(f"Error checking if {key} exists: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking if {key} exists: {e}")
            return False
    
    def list_tender_folders(self, prefix: str = None) -> List[str]:
        """
        List all tender reference folders in S3.
        
        Args:
            prefix: S3 prefix (default: final_doc_tender/)
            
        Returns:
            List of tender reference strings
        """
        if prefix is None:
            prefix = f"{Config.FINAL_DOC_PREFIX}/"
        
        try:
            logger.info(f"Listing tender folders in s3://{self.bucket}/{prefix}")
            
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=prefix,
                Delimiter='/'
            )
            
            tender_refs = []
            for page in pages:
                if 'CommonPrefixes' not in page:
                    continue
                
                for prefix_obj in page['CommonPrefixes']:
                    folder_path = prefix_obj['Prefix']
                    # Extract tender_ref from path like "final_doc_tender/REF123/"
                    tender_ref = folder_path.rstrip('/').split('/')[-1]
                    tender_refs.append(tender_ref)
            
            logger.info(f"Found {len(tender_refs)} tender folders")
            return tender_refs
        except ClientError as e:
            logger.error(f"Error listing tender folders: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing tender folders: {e}")
            return []
