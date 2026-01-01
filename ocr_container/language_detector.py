"""
Language detection module for identifying Arabic documents.
Uses langdetect and sample-based detection strategy.
"""
import io
from typing import Optional
from langdetect import detect, LangDetectException
from PIL import Image
import pytesseract
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
    
    Args:
        image_path: Path to image file
        sample_area: Optional (left, top, right, bottom) tuple for sampling specific area
        
    Returns:
        Language code or None if detection fails
    """
    try:
        image = Image.open(image_path)
        
        # Crop to sample area if provided, otherwise use top 25% of image
        if sample_area:
            image = image.crop(sample_area)
        else:
            width, height = image.size
            image = image.crop((0, 0, width, int(height * 0.25)))
        
        # Extract text using Tesseract with Arabic support
        custom_config = r'--oem 3 --psm 6 -l ara+fra+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        logger.debug(f"Extracted sample text: {text[:100]}...")
        
        # Check for Arabic characters first
        if is_arabic_text(text):
            return 'ar'
        
        # Fallback to langdetect
        return detect_language_from_text(text)
    except Exception as e:
        logger.error(f"Error detecting language from image: {e}")
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
    try:
        # For images, detect directly
        if file_type in ['jpeg', 'jpg', 'png']:
            lang = detect_language_from_image(file_path)
            return lang == 'ar'
        
        # For PDFs, we'll detect during conversion to images
        # For DOCX/XLSX, we'll detect from extracted text
        # This is handled in the respective processors
        return False
    except Exception as e:
        logger.error(f"Error determining language for {file_path}: {e}")
        # Default to OpenRouter if detection fails
        return False


def detect_language_from_pdf_page(image: Image.Image) -> Optional[str]:
    """
    Detect language from a PDF page image.
    
    Args:
        image: PIL Image object
        
    Returns:
        Language code or None
    """
    try:
        # Sample top 25% of page
        width, height = image.size
        sample = image.crop((0, 0, width, int(height * 0.25)))
        
        # Extract text
        custom_config = r'--oem 3 --psm 6 -l ara+fra+eng'
        text = pytesseract.image_to_string(sample, config=custom_config)
        
        # Check for Arabic
        if is_arabic_text(text):
            return 'ar'
        
        return detect_language_from_text(text)
    except Exception as e:
        logger.error(f"Error detecting language from PDF page: {e}")
        return None
