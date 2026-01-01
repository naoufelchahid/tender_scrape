"""
Image (JPEG/PNG) OCR processor.
Uses OpenRouter API for non-Arabic images and Bedrock Nova Lite for Arabic.
"""
import os
import base64
from typing import Optional
from PIL import Image
import io
from openai import OpenAI
import boto3
import json

from config import Config
from logger import logger
from prompts import create_ocr_messages
from language_detector import detect_language_from_image


class ImageProcessor:
    """Image OCR processor."""
    
    def __init__(self):
        """Initialize image processor with API clients."""
        # OpenRouter client
        self.openrouter_client = OpenAI(
            api_key=Config.OPENROUTER_API_KEY,
            base_url=Config.OPENROUTER_BASE_URL
        )
        
        # Bedrock client
        self.bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=Config.AWS_REGION
        )
    
    def _image_to_base64(self, image_path: str) -> str:
        """
        Convert image file to base64 string.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64-encoded string
        """
        with open(image_path, 'rb') as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')
    
    def _ocr_image_openrouter(self, image_base64: str, document_type: str = "tender",
                              is_arabic: bool = False) -> str:
        """
        OCR image using OpenRouter API.
        
        Args:
            image_base64: Base64-encoded image
            document_type: Type of document
            is_arabic: Whether image contains Arabic
            
        Returns:
            Markdown text
        """
        try:
            messages = create_ocr_messages(
                image_base64=image_base64,
                document_type=document_type,
                page_number=1,
                total_pages=1,
                is_arabic=is_arabic
            )
            
            response = self.openrouter_client.chat.completions.create(
                model=Config.OPENROUTER_MODEL,
                messages=messages,
                max_tokens=4000,
                temperature=0.1
            )
            
            markdown_text = response.choices[0].message.content
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR image with OpenRouter: {e}")
            return f"[ERROR: OCR failed]"
    
    def _ocr_image_bedrock(self, image_base64: str, document_type: str = "tender") -> str:
        """
        OCR image using AWS Bedrock Nova Lite.
        
        Args:
            image_base64: Base64-encoded image
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        try:
            messages = create_ocr_messages(
                image_base64=image_base64,
                document_type=document_type,
                page_number=1,
                total_pages=1,
                is_arabic=True
            )
            
            # Nova Lite request format
            request_body = {
                "messages": messages,
                "max_tokens": 4000,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            response = self.bedrock_runtime.invoke_model(
                modelId=Config.BEDROCK_MODEL_ID,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            markdown_text = response_body['content'][0]['text']
            
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR image with Bedrock: {e}")
            # Fallback to OpenRouter
            logger.info("Falling back to OpenRouter")
            return self._ocr_image_openrouter(image_base64, document_type, is_arabic=True)
    
    def process(self, image_path: str, document_type: str = "tender") -> str:
        """
        Process image file and return markdown.
        
        Args:
            image_path: Path to image file
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        logger.info(f"Processing image: {image_path}")
        
        try:
            # Detect language
            lang = detect_language_from_image(image_path)
            is_arabic = (lang == 'ar')
            logger.info(f"Detected language: {'Arabic' if is_arabic else 'Other'}")
            
            # Convert to base64
            image_base64 = self._image_to_base64(image_path)
            
            # OCR based on language
            if is_arabic:
                markdown_text = self._ocr_image_bedrock(image_base64, document_type)
            else:
                markdown_text = self._ocr_image_openrouter(
                    image_base64, document_type, is_arabic=False
                )
            
            logger.info("Successfully processed image")
            return markdown_text
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
