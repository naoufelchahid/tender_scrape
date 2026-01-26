"""
Language detection module for identifying Arabic documents.
Uses langdetect and sample-based detection strategy.
"""
from typing import Optional
from langdetect import detect, LangDetectException
from PIL import Image
from logger import logger


def detect_language_from_text(text: str) -> Optional[str]:
    """
    Detect language from text string.
    
    Args:
        text: Text to analyze
        
    Returns:
        Language code (e.g., 'ar', 'fr', 'en') or None if detection fails
    """
    if not text or len(text.strip()) < 10:
        return None
    
    try:
        lang = detect(text)
        logger.debug(f"Detected language: {lang}")
        return lang
    except LangDetectException as e:
        logger.warning(f"Language detection failed: {e}")
        return None


def is_arabic_text(text: str) -> bool:
    """
    Check if text contains Arabic characters.
    
    Args:
        text: Text to check
        
    Returns:
        True if text contains Arabic, False otherwise
    """
    if not text:
        return False
    
    # Check for Arabic Unicode range (0600-06FF)
    arabic_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF')
    total_chars = sum(1 for char in text if char.isalpha())
    
    if total_chars == 0:
        return False
    
    # If more than 30% of alphabetic characters are Arabic, consider it Arabic
    arabic_ratio = arabic_chars / total_chars
    logger.debug(f"Arabic character ratio: {arabic_ratio:.2%}")
    
    return arabic_ratio > 0.3


def detect_language_from_image(image_path: str, sample_area: Optional[tuple] = None) -> Optional[str]:
    """
    Detect language from image using OCR sampling.
    NOTE: Local Tesseract removed. Returning None to defer to LLM.
    
    Args:
        image_path: Path to image file
        sample_area: Optional (left, top, right, bottom) tuple
        
    Returns:
        None (Detection disabled locally)
    """
    logger.debug("Local image language detection disabled (Tesseract removed)")
    return None


def should_use_nova_lite(file_path: str, file_type: str) -> bool:
    """
    Determine if document should use Nova Lite (Arabic) or OpenRouter.
    
    Args:
        file_path: Path to file
        file_type: File type (pdf, docx, image)
        
    Returns:
        True if should use Nova Lite (Arabic), False otherwise
    """
    return False


def detect_language_from_pdf_page(image: Image.Image) -> Optional[str]:
    """
    Detect language from a PDF page image.
    NOTE: Local Tesseract removed. Returning None.
    
    Args:
        image: PIL Image object
        
    Returns:
        None
    """
    logger.debug("Local PDF language detection disabled (Tesseract removed)")
    return None
