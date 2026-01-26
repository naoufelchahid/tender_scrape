"""
PDF OCR processor with layout preservation.
Uses direct text extraction for PDFs with text layers.
Uses Google Vision API (Synchronous) for scanned PDFs.
Stage: Extraction Container - OCR Processing
"""
import os
import io
from typing import List, Optional
from pdf2image import convert_from_path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config
from logger import logger
from text_layer_detector import has_text_layer
from processors.text_extractor import extract_text
from google_vision_client import GoogleVisionClient


class PDFProcessor:
    """PDF OCR processor using Google Vision API."""
    
    def __init__(self):
        """Initialize PDF processor with Google Vision client."""
        self.vision_client = GoogleVisionClient()
    
    def _image_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to bytes.
        
        Args:
            image: PIL Image object
            
        Returns:
            Bytes content
        """
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=95)
        return buffered.getvalue()
    
    def _ocr_page_vision(self, image: Image.Image, page_num: int) -> str:
        """
        OCR single page using Google Vision API.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            
        Returns:
            Text content
        """
        try:
            image_bytes = self._image_to_bytes(image)
            text = self.vision_client.detect_document_text(image_bytes)
            
            logger.info(f"Page {page_num} OCR completed with Google Vision")
            return text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with Google Vision: {e}")
            return f"[ERROR: OCR failed for page {page_num}]"
    
    def process(self, pdf_path: str, document_type: str = "tender") -> str:
        """
        Process PDF file and return markdown.
        Detects if PDF has text layer and uses appropriate method.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Type of document (unused for Vision, kept for interface)
            
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
                logger.info(f"Using Google Vision API for scanned PDF")
                return self._ocr_scanned_pdf(pdf_path)
                
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {e}")
            raise
    
    def _ocr_scanned_pdf(self, pdf_path: str) -> str:
        """
        OCR a scanned PDF using parallel processing with Google Vision.
        
        Args:
            pdf_path: Path to PDF file
            
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
                    content = self._ocr_page_vision(image, idx)
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
