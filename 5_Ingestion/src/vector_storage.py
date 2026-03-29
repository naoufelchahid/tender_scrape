import asyncio
import json
import logging
import boto3
from typing import List, Optional
from .config import settings
from .uri_builder import slugify

logger = logging.getLogger(__name__)


class VectorStorage:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=settings.AWS_REGION)
        self.bucket = settings.S3_BUCKET_NAME
        self.prefix = settings.VECTOR_S3_PREFIX

    def save_vector(
        self,
        tender_ref: str,
        doc_type: str,
        chunk_index: int,
        h3_header: Optional[str],
        vector: List[float]
    ) -> Optional[str]:
        """
        Save a per-chunk vector to S3 and return the S3 key.
        Specifically for arn:aws:s3vectors:eu-west-3:034791378578:bucket/my-tender-vectors-bucket/index/tender-index

        Args:
            tender_ref: tender folder reference.
            doc_type: 'specification' or 'administrative'.
            chunk_index: zero-based chunk index within the document.
            h3_header: H3 header text that identifies this chunk (may be None).
            vector: embedding float list.

        Returns:
            S3 key string (e.g. index/tender-index/slug/specification_chunk_0_vector.json).
        """
        slug = slugify(tender_ref)
        key = f"{self.prefix}{slug}/{doc_type}_chunk_{chunk_index}_vector.json"

        # Metadata format: {type:specification/administrative, tender_ref: <tender_ref>}
        # We also include content and other flags for completeness, but core metadata is key.
        data = {
            "metadata": {
                "type": doc_type,
                "tender_ref": tender_ref
            },
            "h3_header": h3_header or "",
            "vector": vector,
        }

        try:
            self.s3.put_object(
                Bucket=settings.VECTOR_S3_BUCKET,
                Key=key,
                Body=json.dumps(data),
                ContentType="application/json",
            )
            logger.info(f"Saved {doc_type} vector to {key} in {settings.VECTOR_S3_BUCKET}")
            return key
        except Exception as e:
            logger.error(f"Failed to save vector to S3: {str(e)}")
            return None

    def save_vectors_batch(
        self,
        tender_ref: str,
        doc_type: str,
        chunks_with_vectors: List[dict],
    ) -> List[Optional[str]]:
        """
        Save multiple chunk vectors in sequence.

        Args:
            chunks_with_vectors: list of dicts with keys: h3_header, vector, chunk_index.

        Returns:
            List of S3 URIs in chunk order.
        """
        uris = []
        for item in chunks_with_vectors:
            uri = self.save_vector(
                tender_ref=tender_ref,
                doc_type=doc_type,
                chunk_index=item["chunk_index"],
                h3_header=item.get("h3_header"),
                vector=item["vector"],
            )
            uris.append(uri)
        return uris

    # ------------------------------------------------------------------ #
    # Async wrapper                                                        #
    # ------------------------------------------------------------------ #

    async def async_save_vector(
        self,
        tender_ref: str,
        doc_type: str,
        chunk_index: int,
        h3_header: Optional[str],
        vector: List[float],
    ) -> Optional[str]:
        """Run the blocking save_vector in an executor for concurrency."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.save_vector, tender_ref, doc_type, chunk_index, h3_header, vector
        )
