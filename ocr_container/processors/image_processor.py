"""
Image (JPEG/PNG) OCR processor.
Uses OpenRouter API with Llama 4 models for all images.
Stage: Extraction Container - OCR Processing
"""
import os
import base64
import re
from typing import Optional
from PIL import Image
import io

from config import Config
from logger import logger
from prompts import create_ocr_messages, TABLE_ENHANCEMENT_PROMPT_MAVERICK
from language_detector import detect_language_from_image
from openrouter_client import OpenRouterClient


class ImageProcessor:
    """Image OCR processor using OpenRouter API."""
    
    def __init__(self):
        """Initialize image processor with OpenRouter client."""
        # OpenRouter client for Llama 4 models
        self.openrouter_client = OpenRouterClient()
    
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
        OCR image using OpenRouter API with Llama 4 models.
        
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
            
            # Extract system and user content
            system_prompt = messages[0]["content"]
            user_content = messages[1]["content"]
            
            # Extract text from user content
            user_prompt = ""
            for item in user_content:
                if item["type"] == "text":
                    user_prompt = item["text"]
                    break
            
            # Use OpenRouter client for OCR
            markdown_text = self.openrouter_client.ocr_image(
                image_base64=image_base64,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=4000,
                temperature=0.1
            )
            
            logger.info(f"Image OCR completed with OpenRouter")
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR image with OpenRouter: {e}")
            return f"[ERROR: OCR failed]"
    
    def _enhance_tables_with_openrouter(self, markdown_text: str) -> str:
        """
        Enhance tables in markdown using Llama 4 models.
        
        Args:
            markdown_text: Markdown text with tables
            
        Returns:
            Enhanced markdown with improved tables
        """
        if not Config.ENABLE_TABLE_ENHANCEMENT:
            return markdown_text
        
        try:
            # Extract tables using regex
            table_pattern = r'(\|[^\n]+\|\n(?:\|[-:| ]+\|\n)?(?:\|[^\n]+\|\n?)+)'
            tables = re.findall(table_pattern, markdown_text)
            
            if not tables:
                return markdown_text
            
            logger.info(f"Found {len(tables)} tables, enhancing with OpenRouter...")
            
            enhanced_text = markdown_text
            for table in tables:
                try:
                    # Use OpenRouter client for enhancement
                    enhanced_table = self.openrouter_client.enhance_text(
                        text=table,
                        enhancement_prompt=TABLE_ENHANCEMENT_PROMPT_MAVERICK,
                        max_tokens=2000,
                        temperature=0.1
                    )
                    
                    enhanced_text = enhanced_text.replace(table, enhanced_table)
                except Exception as e:
                    logger.warning(f"Failed to enhance table: {e}")
                    continue
            
            return enhanced_text
        except Exception as e:
            logger.error(f"Error in table enhancement: {e}")
            return markdown_text
    
    def process(self, image_path: str, document_type: str = "tender") -> str:
        """
        Process image file and return markdown using OpenRouter API.
        
        Args:
            image_path: Path to image file
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        logger.info(f"Processing image: {image_path}")
        
        try:
            # Detect language (for logging purposes)
            lang = detect_language_from_image(image_path)
            is_arabic = (lang == 'ar')
            logger.info(f"Detected language: {'Arabic' if is_arabic else 'Other'}")
            
            # Convert to base64
            image_base64 = self._image_to_base64(image_path)
            
            # OCR with OpenRouter (handles all languages)
            markdown_text = self._ocr_image_openrouter(image_base64, document_type, is_arabic)
            
            # Enhance tables if enabled
            if Config.ENABLE_TABLE_ENHANCEMENT:
                logger.info("Enhancing tables with OpenRouter...")
                markdown_text = self._enhance_tables_with_openrouter(markdown_text)
            
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
