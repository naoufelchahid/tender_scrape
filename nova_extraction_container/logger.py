"""
Logging configuration for Nova Extraction Container.
"""
import logging
import sys
from datetime import datetime
from typing import Optional

from config import Config


def setup_logger(name: str = __name__, log_level: Optional[str] = None) -> logging.Logger:
    """
    Set up and configure logger.
    
    Args:
        name: Logger name
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Set log level
    level = log_level or Config.LOG_LEVEL
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    # Detailed formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


# Global logger instance
logger = setup_logger('nova_extraction')


def log_processing_start(tender_ref: str, file_count: int) -> None:
    """Log processing start."""
    logger.info("=" * 80)
    logger.info(f"🚀 STARTING PROCESSING: {tender_ref}")
    logger.info(f"📄 Files to process: {file_count}")
    logger.info("=" * 80)


def log_processing_complete(tender_ref: str, processing_time: float, 
                            files_processed: int, files_skipped: int) -> None:
    """Log processing completion."""
    logger.info("=" * 80)
    logger.info(f"✅ COMPLETED PROCESSING: {tender_ref}")
    logger.info(f"⏱️  Processing time: {processing_time:.2f}s")
    logger.info(f"📄 Files processed: {files_processed}")
    logger.info(f"⏭️  Files skipped: {files_skipped}")
    logger.info("=" * 80)


def log_processing_error(tender_ref: str, error: Exception) -> None:
    """Log processing error."""
    logger.error("=" * 80)
    logger.error(f"❌ ERROR PROCESSING: {tender_ref}")
    logger.error(f"Error: {str(error)}")
    logger.error("=" * 80, exc_info=True)


def log_file_processing(tender_ref: str, filename: str, doc_type: str, status: str) -> None:
    """
    Log individual file processing status.
    
    Args:
        tender_ref: Tender reference
        filename: File name
        doc_type: Document type
        status: Status (started, completed, failed, skipped)
    """
    status_emoji = {
        'started': '🔄',
        'completed': '✅',
        'failed': '❌',
        'skipped': '⏭️'
    }
    
    emoji = status_emoji.get(status, '📄')
    logger.info(f"{emoji} [{tender_ref}] {filename} ({doc_type}) - {status.upper()}")


def log_model_fallback(from_model: str, to_model: str, reason: str) -> None:
    """Log model fallback."""
    logger.warning(f"⚠️  FALLBACK: {from_model} → {to_model} | Reason: {reason}")


def log_extraction_result(tender_ref: str, metadata_items: int, 
                          lots_count: int, products_count: int) -> None:
    """Log extraction results summary."""
    logger.info(f"📊 Extraction Results for {tender_ref}:")
    logger.info(f"   - Metadata fields: {metadata_items}")
    logger.info(f"   - Lots: {lots_count}")
    logger.info(f"   - Products: {products_count}")
