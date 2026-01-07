import logging
import json
from typing import List, Dict, Any, Optional
from src.models import ExtractionOutput

logger = logging.getLogger(__name__)

class IntegrityCheckError(Exception):
    """Raised when data integrity check fails."""
    pass

class IntegrityChecker:
    """Checks data validity before downstream processing."""

    @staticmethod
    def check_metadata(metadata: ExtractionOutput) -> bool:
        """
        Validates extracted metadata.
        Criteria:
        - Buyer name must be present.
        - Tender reference must be present.
        """
        info = metadata.tender_info
        
        if not info.buyer or not info.buyer.strip():
            logger.error("Integrity Check Failed: Missing mandatory 'buyer' field.")
            return False
            
        if not info.tender_reference or not info.tender_reference.strip():
            logger.error("Integrity Check Failed: Missing mandatory 'tender_reference' field.")
            return False
            
        return True

    @staticmethod
    def check_chunks(chunks: List[Dict[str, Any]]) -> bool:
        """
        Validates generated chunks.
        Criteria:
        - List must not be empty.
        - Each chunk must have an ID and Content.
        - Content must be non-trivial (> 10 chars).
        """
        if not chunks:
            logger.error("Integrity Check Failed: Chunk list is empty.")
            return False
            
        for i, chunk in enumerate(chunks):
            if "id" not in chunk or not chunk["id"]:
                logger.error(f"Integrity Check Failed: Chunk {i} missing 'id'.")
                return False
            
            if "content" not in chunk or not chunk["content"]:
                logger.error(f"Integrity Check Failed: Chunk {i} missing 'content'.")
                return False
                
            if len(chunk["content"].strip()) < 10:
                logger.error(f"Integrity Check Failed: Chunk {i} content too short (<10 chars).")
                return False
                
        return True
