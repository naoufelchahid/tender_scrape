"""
Processor factory for routing files to appropriate processors.
"""
import os
from typing import Optional
from logger import logger


# File extension to processor mapping
PROCESSOR_MAP = {
    '.pdf': 'pdf_processor',
    '.docx': 'docx_processor',
    # '.doc': 'docx_processor',  # Legacy .doc not supported by python-docx
    '.xlsx': 'xlsx_processor',
    '.xls': 'xlsx_processor',
    '.jpeg': 'image_processor',
    '.jpg': 'image_processor',
    '.png': 'image_processor',
}


def get_file_type(file_path: str) -> Optional[str]:
    """
    Get file type from file extension.
    
    Args:
        file_path: Path to file
        
    Returns:
        File type string or None if unsupported
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in PROCESSOR_MAP:
        return PROCESSOR_MAP[ext].replace('_processor', '')
    
    return None


def get_processor(file_path: str):
    """
    Get appropriate processor for file type.
    
    Args:
        file_path: Path to file
        
    Returns:
        Processor module
        
    Raises:
        ValueError: If file type is not supported
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext not in PROCESSOR_MAP:
        raise ValueError(f"Unsupported file type: {ext}")
    
    processor_name = PROCESSOR_MAP[ext]
    
    # Dynamic import
    if processor_name == 'pdf_processor':
        from processors.pdf_processor import process_pdf
        return process_pdf
    elif processor_name == 'docx_processor':
        from processors.docx_processor import process_docx
        return process_docx
    elif processor_name == 'xlsx_processor':
        from processors.xlsx_processor import process_xlsx
        return process_xlsx
    elif processor_name == 'image_processor':
        from processors.image_processor import process_image
        return process_image
    else:
        raise ValueError(f"Unknown processor: {processor_name}")


def is_supported_file(file_path: str) -> bool:
    """
    Check if file type is supported.
    
    Args:
        file_path: Path to file
        
    Returns:
        True if supported, False otherwise
    """
    ext = os.path.splitext(file_path)[1].lower()
    return ext in PROCESSOR_MAP
