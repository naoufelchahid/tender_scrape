"""
OCR service using Groq API with Llama 4 models.
Supports primary and fallback models with automatic retry.

Stage: Extraction Container - OCR Processing
"""
import base64
import io
from typing import List
from PIL import Image
from groq import Groq
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config
from logger import logger, log_ocr_progress
from prompts import create_ocr_messages, create_openrouter_messages
from utils.pdf_utils import convert_pdf_to_images, combine_page_markdown


class OCRService:
    """OCR service using Groq API with multi-model fallback."""
    
    def __init__(self):
        """Initialize OCR service with Groq client."""
        # Groq client for Llama 4 Scout and Maverick
        self.groq_client = Groq(api_key=Config.GROQ_API_KEY)
        
        # Optional OpenRouter client for additional fallback
        self.openrouter_client = None
        if Config.OPENROUTER_API_KEY:
            self.openrouter_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=Config.OPENROUTER_API_KEY,
            )
            logger.info("OpenRouter fallback enabled")
        
        logger.info(f"Initialized OCR service with primary model: {Config.PRIMARY_MODEL}")
        logger.info(f"Fallback model: {Config.FALLBACK_MODEL}")
    
    def _image_to_base64(self, image: Image.Image) -> str:
        """
        Convert PIL Image to base64 string.
        
        Args:
            image: PIL Image object
            
        Returns:
            Base64-encoded string
        """
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    def _sanitize_image(self, image: Image.Image) -> Image.Image:
        """
        Resize image if it exceeds pixel limits for API.
        Groq limit is ~33M pixels. We'll use 25M as a safe limit.
        """
        PIXEL_LIMIT = 25_000_000
        width, height = image.size
        total_pixels = width * height
        
        if total_pixels > PIXEL_LIMIT:
            scale = (PIXEL_LIMIT / total_pixels) ** 0.5
            new_size = (int(width * scale), int(height * scale))
            logger.warning(f"Image too large ({total_pixels} pixels). Resizing to {new_size[0]}x{new_size[1]}")
            return image.resize(new_size, Image.Resampling.LANCZOS)
        return image

    def _ocr_page_groq(self, image: Image.Image, page_num: int, total_pages: int, model: str) -> str:
        """
        OCR single page using Groq API.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            model: Model to use
            
        Returns:
            Markdown text
        """
        try:
            # Resize if too large
            image = self._sanitize_image(image)
            
            image_base64 = self._image_to_base64(image)
            messages = create_ocr_messages(image_base64, page_num, total_pages)
            
            response = self.groq_client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4000,
                temperature=0.1
            )
            
            markdown_text = response.choices[0].message.content
            log_ocr_progress(page_num, total_pages, model)
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with {model}: {e}")
            raise
    
    def _ocr_page_openrouter(self, image: Image.Image, page_num: int, total_pages: int) -> str:
        """
        OCR single page using OpenRouter API (final fallback).
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            
        Returns:
            Markdown text
        """
        if not self.openrouter_client:
            raise ValueError("OpenRouter client not configured")
        
        try:
            # Resize if too large
            image = self._sanitize_image(image)
            
            image_base64 = self._image_to_base64(image)
            messages = create_openrouter_messages(image_base64, page_num, total_pages)
            
            response = self.openrouter_client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://github.com/naoufelchahid/AO_scrape",
                    "X-Title": "AO Scrape Results OCR",
                },
                model=Config.OPENROUTER_MODEL,
                messages=messages
            )
            
            markdown_text = response.choices[0].message.content
            log_ocr_progress(page_num, total_pages, Config.OPENROUTER_MODEL)
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with OpenRouter: {e}")
            raise
    
    def _ocr_single_page(self, image: Image.Image, page_num: int, total_pages: int) -> str:
        """
        OCR a single page with automatic fallback.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            
        Returns:
            Markdown text
        """
        # Try primary model (Scout)
        try:
            return self._ocr_page_groq(image, page_num, total_pages, Config.PRIMARY_MODEL)
        except Exception as e:
            logger.warning(f"Primary model failed for page {page_num}: {e}")
        
        # Try fallback model (Maverick)
        try:
            logger.info(f"Trying fallback model for page {page_num}")
            return self._ocr_page_groq(image, page_num, total_pages, Config.FALLBACK_MODEL)
        except Exception as e:
            logger.warning(f"Fallback model failed for page {page_num}: {e}")
        
        # Try OpenRouter if configured
        if self.openrouter_client:
            try:
                logger.info(f"Trying OpenRouter fallback for page {page_num}")
                return self._ocr_page_openrouter(image, page_num, total_pages)
            except Exception as e:
                logger.error(f"OpenRouter fallback failed for page {page_num}: {e}")
        
        # All models failed
        return f"[ERROR: OCR failed for page {page_num}]"
    
    def ocr_pdf(self, pdf_path: str) -> str:
        """
        OCR a scanned PDF using parallel processing.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Complete markdown text
        """
        logger.info(f"Starting OCR for PDF: {pdf_path}")
        
        try:
            # Convert PDF to images
            images = convert_pdf_to_images(pdf_path)
            total_pages = len(images)
            
            logger.info(f"PDF has {total_pages} pages. Starting parallel OCR with {Config.MAX_WORKERS} workers")
            
            # Helper function for parallel processing
            def process_single_page(args):
                idx, image = args
                try:
                    content = self._ocr_single_page(image, idx, total_pages)
                    return idx, f"## Page {idx}\n\n{content}\n"
                except Exception as e:
                    logger.error(f"Error processing page {idx}: {e}")
                    return idx, f"## Page {idx}\n\n[ERROR: OCR Failed]\n"
            
            # Execute parallel processing
            markdown_map = {}
            with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
                # Prepare tasks
                tasks = [(i, img) for i, img in enumerate(images, 1)]
                
                # Submit all tasks
                future_to_page = {executor.submit(process_single_page, task): task[0] for task in tasks}
                
                # Process results as they complete
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        idx, content = future.result()
                        markdown_map[idx] = content
                        logger.info(f"Completed OCR page {idx}/{total_pages}")
                    except Exception as e:
                        logger.error(f"Unhandled exception for page {page_num}: {e}")
                        markdown_map[page_num] = f"## Page {page_num}\n\n[ERROR: Exception]\n"
            
            # Reassemble pages in correct order
            markdown_pages = [markdown_map[i] for i in range(1, total_pages + 1)]
            
            # Combine all pages
            final_markdown = combine_page_markdown(markdown_pages)
            
            logger.info(f"Successfully OCR'd PDF with {total_pages} pages")
            return final_markdown
            
        except Exception as e:
            logger.error(f"Error OCR'ing PDF: {e}")
            raise
