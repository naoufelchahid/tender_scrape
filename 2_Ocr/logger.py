"""
Structured logging module for OCR container.
Provides JSON-formatted logs for CloudWatch.
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record to format.
            
        Returns:
            JSON-formatted log string.
        """
        log_data: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add extra context if available
        if hasattr(record, 'tender_ref'):
            log_data['tender_ref'] = record.tender_ref
        if hasattr(record, 'file_type'):
            log_data['file_type'] = record.file_type
        if hasattr(record, 'processing_time'):
            log_data['processing_time'] = record.processing_time
        if hasattr(record, 'error'):
            log_data['error'] = record.error
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logger(name: str = 'ocr-service', level: int = logging.INFO) -> logging.Logger:
    """
    Set up structured logger.
    
    Args:
        name: Logger name.
        level: Logging level.
        
    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler with JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    # File handler
    log_dir = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(__file__), '..', 'Logs', '2_Ocr'))
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(log_dir, 'ocr.log'))
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger


# Create default logger
logger = setup_logger()


def log_processing_start(tender_ref: str, file_count: int, s3_paths: list = None) -> None:
    """Log start of tender processing with enhanced visibility."""
    separator = "=" * 80
    logger.info(separator)
    logger.info(
        f"🚀 STARTING OCR PROCESSING FOR TENDER: {tender_ref}",
        extra={'tender_ref': tender_ref, 'file_count': file_count, 'event': 'processing_start'}
    )
    logger.info(f"📊 Total files to process: {file_count}")
    
    if s3_paths:
        logger.info(f"📁 S3 Paths:")
        for idx, path in enumerate(s3_paths, 1):
            logger.info(f"   {idx}. {path}")
    
    logger.info(separator)


def log_processing_complete(tender_ref: str, processing_time: float, file_count: int) -> None:
    """Log successful completion of tender processing."""
    logger.info(
        f"Completed OCR processing for tender {tender_ref}",
        extra={
            'tender_ref': tender_ref,
            'processing_time': processing_time,
            'file_count': file_count,
            'status': 'success'
        }
    )


def log_processing_error(tender_ref: str, error: Exception, file_path: Optional[str] = None) -> None:
    """Log processing error."""
    logger.error(
        f"Error processing tender {tender_ref}: {str(error)}",
        extra={
            'tender_ref': tender_ref,
            'error': str(error),
            'file_path': file_path,
            'status': 'failed'
        },
        exc_info=True
    )


def log_file_processing(tender_ref: str, file_path: str, file_type: str, status: str) -> None:
    """Log individual file processing."""
    logger.info(
        f"Processing file: {file_path} ({file_type}) - {status}",
        extra={
            'tender_ref': tender_ref,
            'file_path': file_path,
            'file_type': file_type,
            'status': status
        }
    )
