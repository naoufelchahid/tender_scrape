"""
Image (JPEG/PNG) OCR processor.
Uses Google Vision API for all images.
Stage: Extraction Container - OCR Processing
"""
import io
from typing import Optional

from logger import logger
from google_vision_client import GoogleVisionClient


class ImageProcessor:
    """Image OCR processor using Google Vision API."""
    
    def __init__(self):
        """Initialize image processor with Google Vision client."""
        self.vision_client = GoogleVisionClient()
    
    def _read_image_file(self, image_path: str) -> bytes:
        """
        Read image file to bytes.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Image content in bytes
        """
        with open(image_path, 'rb') as img_file:
            return img_file.read()
    
    def process(self, image_path: str, document_type: str = "tender") -> str:
        """
        Process image file and return text using Google Vision API.
        
        Args:
            image_path: Path to image file
            document_type: Type of document (unused)
            
        Returns:
            Markdown text
        """
        logger.info(f"Processing image: {image_path}")
        
        try:
            # Read image
            image_content = self._read_image_file(image_path)
            
            # OCR with Google Vision (Document Text Detection for dense text)
            # Use detect_document_text for scanned documents/forms as it preserves structure better
            text = self.vision_client.detect_document_text(image_content)
            
            logger.info("Successfully processed image with Google Vision")
            return text
            
        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}")
            raise


def process_image(image_path: str, document_type: str = "tender") -> str:
    """
    Process image file to markdown.
    
    Args:
        image_path: Path to image file
        document_type: Type of document
        
    Returns:
        Markdown text
    """
    processor = ImageProcessor()
    return processor.process(image_path, document_type)
