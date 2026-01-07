"""
Text layer detection for PDF files.
Determines if a PDF has extractable text or needs OCR/multimodal processing.
"""
import pdfplumber
from typing import Tuple
from logger import logger


def has_text_layer(pdf_path: str, sample_pages: int = 3, min_chars: int = 50) -> Tuple[bool, float]:
    """
    Check if PDF has extractable text layer.
    
    Args:
        pdf_path: Path to PDF file
        sample_pages: Number of pages to sample (default: 3)
        min_chars: Minimum characters per page to consider as text (default: 50)
        
    Returns:
        (has_text, confidence): 
            - has_text: True if PDF has extractable text
            - confidence: 0-1 score indicating text quality
    """
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
            
            has_text = confidence >= 0.5  # At least 50% of sampled pages have text
            
            avg_chars = total_chars / pages_to_check if pages_to_check > 0 else 0
            
            logger.info(
                f"Text layer detection: {has_text} "
                f"(confidence: {confidence:.2f}, "
                f"avg chars/page: {avg_chars:.0f})"
            )
            
            return has_text, confidence
            
    except Exception as e:
        logger.error(f"Error detecting text layer in {pdf_path}: {e}")
        # If detection fails, assume scanned (safer to use multimodal than skip)
        return False, 0.0


def get_text_coverage(pdf_path: str) -> float:
    """
    Get percentage of pages with extractable text.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Float 0-1 representing percentage of pages with text
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            text_pages = 0
            
            for page in pdf.pages:
                text = page.extract_text()
                if text and len(text.strip()) >= 50:
                    text_pages += 1
            
            coverage = text_pages / total_pages if total_pages > 0 else 0.0
            logger.info(f"Text coverage: {coverage:.1%} ({text_pages}/{total_pages} pages)")
            
            return coverage
            
    except Exception as e:
        logger.error(f"Error calculating text coverage: {e}")
        return 0.0
