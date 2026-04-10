"""
Logging configuration for Results OCR container.

Stage: Extraction Container - OCR Processing
"""
import logging
import sys
from typing import Optional
from datetime import datetime


# Configure logging format
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Create logger
logger = logging.getLogger('results_ocr')
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


def log_file_processing(filename: str, file_type: str, status: str, details: str = "") -> None:
    """
    Log file processing events.
    
    Args:
        filename: Name of the file being processed
        file_type: Type of file (pdf, docx, etc.)
        status: Status (started, completed, failed)
        details: Additional details
    """
    if status == "started":
        logger.info(f"📄 Processing {file_type.upper()}: {filename}")
    elif status == "completed":
        logger.info(f"✅ Completed {file_type.upper()}: {filename} {details}")
    elif status == "failed":
        logger.error(f"❌ Failed {file_type.upper()}: {filename} - {details}")


def log_ocr_progress(page_num: int, total_pages: int, model: str) -> None:
    """
    Log OCR progress.
    
    Args:
        page_num: Current page number
        total_pages: Total number of pages
        model: Model used for OCR
    """
    logger.info(f"🔍 OCR Page {page_num}/{total_pages} with {model}")


def log_text_layer_detection(has_text: bool, confidence: float, pdf_path: str) -> None:
    """
    Log text layer detection results.
    
    Args:
        has_text: Whether text layer was detected
        confidence: Confidence score (0-1)
        pdf_path: Path to PDF
    """
    status = "✅ Text layer detected" if has_text else "❌ No text layer detected"
    logger.info(f"{status} (confidence: {confidence:.2f}) - {pdf_path}")


def log_s3_operation(operation: str, key: str, status: str = "success", error: str = "") -> None:
    """
    Log S3 operations.
    
    Args:
        operation: Operation type (download, upload, delete)
        key: S3 key
        status: Status (success, failed)
        error: Error message if failed
    """
    if status == "success":
        logger.info(f"☁️  S3 {operation.upper()}: {key}")
    else:
        logger.error(f"☁️  S3 {operation.upper()} FAILED: {key} - {error}")


def log_processing_summary(filename: str, processing_time: float, num_pages: int, method: str) -> None:
    """
    Log processing summary.
    
    Args:
        filename: Filename processed
        processing_time: Time taken in seconds
        num_pages: Number of pages processed
        method: Processing method (direct_extraction, ocr)
    """
    logger.info(
        f"📊 Summary: {filename} - {num_pages} pages - "
        f"{processing_time:.2f}s - method: {method}"
    )
