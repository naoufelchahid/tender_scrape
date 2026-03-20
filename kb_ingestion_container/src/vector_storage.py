import json
import logging
import boto3
from typing import List
from .config import settings
from .uri_builder import slugify

logger = logging.getLogger(__name__)

class VectorStorage:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=settings.AWS_REGION)
        self.bucket = settings.S3_BUCKET_NAME
        self.prefix = settings.VECTOR_S3_PREFIX

    def save_vector(self, tender_ref: str, vector_type: str, vector: List[float]) -> str:
        """
        Save vector to S3 and return the S3 URI.
        vector_type: 'specification', 'administrative' or 'article_{idx}'
        """
        slug = slugify(tender_ref)
        key = f"{self.prefix}{slug}/{vector_type}_vector.json"
        
        data = {
            "tender_ref": tender_ref,
            "type": vector_type,
            "vector": vector
        }
        
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data),
                ContentType="application/json"
            )
            s3_uri = f"s3://{self.bucket}/{key}"
            logger.info(f"Saved {vector_type} vector to {s3_uri}")
            return s3_uri
        except Exception as e:
            logger.error(f"Failed to save vector to S3: {str(e)}")
            raise
