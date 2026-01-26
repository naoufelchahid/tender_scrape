"""
Google Vision API Client.
Handles synchronous text detection for images (and PDF pages converted to images).
"""
import os
from typing import Optional, List
from google.cloud import vision
from google.oauth2 import service_account

from config import Config
from logger import logger


class GoogleVisionClient:
    """Client for Google Cloud Vision API."""
    
    def __init__(self):
        """Initialize Vision API client."""
        self.client = self._get_client()
        
    def _get_client(self) -> vision.ImageAnnotatorClient:
        """
        Get authenticated Vision API client.
        
        Returns:
            Vision API client
        """
        try:
            if Config.GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(Config.GOOGLE_APPLICATION_CREDENTIALS):
                credentials = service_account.Credentials.from_service_account_file(
                    Config.GOOGLE_APPLICATION_CREDENTIALS
                )
                return vision.ImageAnnotatorClient(credentials=credentials)
            else:
                # Fallback to default credentials (environment variable)
                return vision.ImageAnnotatorClient()
        except Exception as e:
            logger.error(f"Failed to initialize Google Vision client: {e}")
            raise

    def detect_document_text(self, image_content: bytes) -> str:
        """
        Detects document features in an image (dense text).
        
        Args:
            image_content: Raw image bytes
            
        Returns:
            Detected text
        """
        try:
            image = vision.Image(content=image_content)
            
            # Use document_text_detection for dense text (PDF pages)
            response = self.client.document_text_detection(image=image)
            
            if response.error.message:
                raise Exception(
                    '{}\nFor more info on error messages, check: '
                    'https://cloud.google.com/apis/design/errors'.format(
                        response.error.message))

            return response.full_text_annotation.text
            
        except Exception as e:
            logger.error(f"Google Vision API error: {e}")
            raise

    def detect_text(self, image_content: bytes) -> str:
        """
        Detects text in an image (sparse text).
        
        Args:
            image_content: Raw image bytes
            
        Returns:
            Detected text
        """
        try:
            image = vision.Image(content=image_content)
            
            # Use text_detection for sparse text
            response = self.client.text_detection(image=image)
            
            if response.error.message:
                raise Exception(
                    '{}\nFor more info on error messages, check: '
                    'https://cloud.google.com/apis/design/errors'.format(
                        response.error.message))

            if response.text_annotations:
                return response.text_annotations[0].description
            return ""
            
        except Exception as e:
            logger.error(f"Google Vision API error: {e}")
            raise
