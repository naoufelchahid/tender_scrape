"""
Text layer detector for PDF files.
Determines if a PDF has extractable text or needs OCR.

Stage: Extraction Container - OCR Processing
"""
import pdfplumber
from typing import Tuple
from logger import logger, log_text_layer_detection
from config import Config


def has_text_layer(pdf_path: str, sample_pages: int = None, min_chars: int = None) -> Tuple[bool, float]:
    """
    Check if PDF has extractable text layer.
    
    Args:
        pdf_path: Path to PDF file
        sample_pages: Number of pages to sample (default: from Config)
        min_chars: Minimum characters per page to consider as text (default: from Config)
        
    Returns:
        (has_text, confidence): 
            - has_text: True if PDF has extractable text
            - confidence: 0-1 score indicating text quality
    """
    sample_pages = sample_pages or Config.TEXT_LAYER_SAMPLE_PAGES
    min_chars = min_chars or Config.TEXT_LAYER_MIN_CHARS
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_check = min(sample_pages, total_pages)
            
            text_pages = 0
            total_chars = 0
            
            # Sample first, middle, and last pages
            sample_indices = []
            if total_pages == 1:
                sample_indices = [0]
            elif total_pages == 2:
                sample_indices = [0, 1]
            else:
                sample_indices = [
                    0,  # First page
                    total_pages // 2,  # Middle page
                    total_pages - 1  # Last page
                ][:pages_to_check]
            
            for idx in sample_indices:
                try:
                    page = pdf.pages[idx]
                    text = page.extract_text()
                    
                    if text:
                        char_count = len(text.strip())
                        total_chars += char_count
                        
                        if char_count >= min_chars:
                            text_pages += 1
                            logger.debug(f"Page {idx + 1}: {char_count} characters extracted")
                        else:
                            logger.debug(f"Page {idx + 1}: Only {char_count} characters (below threshold)")
                    else:
                        logger.debug(f"Page {idx + 1}: No text extracted")
                        
                except Exception as e:
                    logger.warning(f"Error extracting text from page {idx + 1}: {e}")
                    continue
            
            # Calculate confidence
            if pages_to_check == 0:
                confidence = 0.0
            else:
                confidence = text_pages / pages_to_check
            
            has_text = confidence >= Config.TEXT_LAYER_CONFIDENCE_THRESHOLD
            
            avg_chars = total_chars / pages_to_check if pages_to_check > 0 else 0
            
            log_text_layer_detection(has_text, confidence, pdf_path)
            logger.debug(f"Average characters per page: {avg_chars:.0f}")
            
            return has_text, confidence
            
    except Exception as e:
        logger.error(f"Error detecting text layer in {pdf_path}: {e}")
        # If detection fails, assume scanned (safer to OCR than skip)
        return False, 0.0


def get_page_count(pdf_path: str) -> int:
    """
    Get the number of pages in a PDF.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Number of pages
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception as e:
        logger.error(f"Error getting page count from {pdf_path}: {e}")
        return 0
