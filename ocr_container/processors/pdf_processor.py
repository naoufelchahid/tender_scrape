"""
PDF OCR processor with layout preservation.
Uses direct text extraction for PDFs with text layers.
Uses OpenRouter API with Llama 4 models for scanned PDFs.
Stage: Extraction Container - OCR Processing
"""
import os
import base64
import re
from typing import List, Optional
from pdf2image import convert_from_path
from PIL import Image
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config
from logger import logger
from prompts import create_ocr_messages, TABLE_ENHANCEMENT_PROMPT_MAVERICK
from language_detector import detect_language_from_pdf_page
from text_layer_detector import has_text_layer
from processors.text_extractor import extract_text
from openrouter_client import OpenRouterClient


class PDFProcessor:
    """PDF OCR processor using OpenRouter API."""
    
    def __init__(self):
        """Initialize PDF processor with OpenRouter client."""
        # OpenRouter client for Llama 4 models
        self.openrouter_client = OpenRouterClient()
    
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
    
    def _ocr_page_openrouter(self, image: Image.Image, page_num: int, 
                       total_pages: int, document_type: str = "tender",
                       is_arabic: bool = False) -> str:
        """
        OCR single page using OpenRouter API with Llama 4 models.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            document_type: Type of document
            is_arabic: Whether document is in Arabic
            
        Returns:
            Markdown text
        """
        try:
            image_base64 = self._image_to_base64(image)
            messages = create_ocr_messages(
                image_base64=image_base64,
                document_type=document_type,
                page_number=page_num,
                total_pages=total_pages,
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
            
            logger.info(f"Page {page_num} OCR completed with OpenRouter")
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with OpenRouter: {e}")
            return f"[ERROR: OCR failed for page {page_num}]"
    
    def _enhance_tables_with_openrouter(self, markdown_text: str) -> str:
        """
        Enhance tables in markdown using Llama 4 models for better formatting.
        
        Args:
            markdown_text: Markdown text with tables
            
        Returns:
            Enhanced markdown with improved tables
        """
        if not Config.ENABLE_TABLE_ENHANCEMENT:
            logger.info("Table enhancement disabled, skipping processing")
            return markdown_text
        
        try:
            # Extract tables using regex (simple pipe-based table detection)
            table_pattern = r'(\|[^\n]+\|\n(?:\|[-:| ]+\|\n)?(?:\|[^\n]+\|\n?)+)'
            tables = re.findall(table_pattern, markdown_text)
            
            if not tables:
                logger.info("No tables detected, skipping enhancement")
                return markdown_text
            
            logger.info(f"Found {len(tables)} tables, enhancing with OpenRouter...")
            
            # Enhance each table
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
                    
                    # Replace original table with enhanced version
                    enhanced_text = enhanced_text.replace(table, enhanced_table)
                    logger.info("Table enhanced successfully")
                except Exception as e:
                    logger.warning(f"Failed to enhance table: {e}, keeping original")
                    continue
            
            return enhanced_text
        except Exception as e:
            logger.error(f"Error in table enhancement: {e}")
            return markdown_text  # Return original on error
            
    def _mark_tables_with_tags(self, markdown_text: str) -> str:
        """
        Mark tables with **Table N** headers and <table_start>/<table_end> tags.
        
        Args:
            markdown_text: Markdown text
            
        Returns:
            Markdown text with tagged tables
        """
        try:
            # Regex for tables
            table_pattern = r'(\|[^\n]+\|\n(?:\|[-:| ]+\|\n)?(?:\|[^\n]+\|\n?)+)'
            
            logger.info("Marking tables with tags...")
            
            counter = 1
            def replace_func(match):
                nonlocal counter
                table_content = match.group(0)
                replacement = f"\n**Table {counter}**\n<table_start>\n{table_content}<table_end>\n"
                counter += 1
                return replacement
                
            marked_text = re.sub(table_pattern, replace_func, markdown_text)
            return marked_text
            
        except Exception as e:
            logger.error(f"Error marking tables: {e}")
            return markdown_text
    
    def process(self, pdf_path: str, document_type: str = "tender") -> str:
        """
        Process PDF file and return markdown.
        Detects if PDF has text layer and uses appropriate method.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Type of document (for specialized prompts)
            
        Returns:
            Complete markdown text
        """
        logger.info(f"Processing PDF: {pdf_path}")
        
        try:
            # Step 1: Check if PDF has text layer
            logger.info("Checking for text layer...")
            has_text, confidence = has_text_layer(pdf_path)
            
            if has_text:
                # PDF has text layer - use direct extraction (fast!)
                logger.info(f"✅ Text layer detected (confidence: {confidence:.2f})")
                logger.info("Using direct text extraction (no OCR needed)")
                markdown = extract_text(pdf_path)
                logger.info("Successfully extracted text from PDF")
                return markdown
            else:
                # PDF is scanned - use OCR
                logger.info(f"❌ No text layer detected (confidence: {confidence:.2f})")
                logger.info(f"Using OpenRouter API with {Config.PRIMARY_MODEL} for scanned PDF")
                return self._ocr_scanned_pdf(pdf_path, document_type)
                
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {e}")
            raise
    
    def _ocr_scanned_pdf(self, pdf_path: str, document_type: str) -> str:
        """
        OCR a scanned PDF using parallel processing with OpenRouter.
        Optionally enhances tables.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        try:
            # Convert PDF to images
            logger.info("Converting PDF to images...")
            images = convert_from_path(pdf_path, dpi=300)
            total_pages = len(images)
            logger.info(f"PDF has {total_pages} pages. Starting parallel OCR with {Config.MAX_WORKERS} workers.")
            
            # Helper function for parallel processing
            def process_single_page(args):
                idx, image = args
                try:
                    logger.info(f"Starting OCR page {idx}/{total_pages}...")
                    content = self._ocr_page_openrouter(
                        image, idx, total_pages, document_type, is_arabic=False
                    )
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
            final_markdown = "\n---\n\n".join(markdown_pages)
            
            # Enhance tables if enabled
            if Config.ENABLE_TABLE_ENHANCEMENT:
                logger.info("Enhancing tables with OpenRouter...")
                final_markdown = self._enhance_tables_with_openrouter(final_markdown)
            
            # Appply table tags
            final_markdown = self._mark_tables_with_tags(final_markdown)
            
            logger.info(f"Successfully OCR'd PDF with {total_pages} pages")
            return final_markdown
            
        except Exception as e:
            logger.error(f"Error OCR'ing scanned PDF: {e}")
            raise



def process_pdf(pdf_path: str, document_type: str = "tender") -> str:
    """
    Process PDF file to markdown.
    
    Args:
        pdf_path: Path to PDF file
        document_type: Type of document
        
    Returns:
        Markdown text
    """
    processor = PDFProcessor()
    return processor.process(pdf_path, document_type)
