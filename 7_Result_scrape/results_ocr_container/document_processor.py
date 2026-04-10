"""
Document processor for handling different file types.
Orchestrates text extraction and OCR processing.

Stage: Extraction Container - OCR Processing
"""
import os
import time
from pathlib import Path
from typing import Tuple

from config import Config
from logger import logger, log_file_processing, log_processing_summary
from text_layer_detector import has_text_layer, get_page_count
from ocr_service import OCRService
from utils.pdf_utils import extract_text_with_pdfplumber
from utils.docx_utils import extract_text_from_docx


class DocumentProcessor:
    """Document processor for PDFs and DOCX files."""
    
    def __init__(self):
        """Initialize document processor."""
        self.ocr_service = OCRService()
        logger.info("Initialized DocumentProcessor")
    
    def _get_file_type(self, file_path: str) -> str:
        """
        Determine file type from extension.
        
        Args:
            file_path: Path to file
            
        Returns:
            File type ('pdf', 'docx', 'doc', or 'unknown')
        """
        ext = Path(file_path).suffix.lower()
        
        if ext == '.pdf':
            return 'pdf'
        elif ext in ('.docx', '.doc'):
            return 'docx'
        else:
            return 'unknown'
    
    def process_pdf(self, pdf_path: str) -> Tuple[str, str]:
        """
        Process PDF file with intelligent detection.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (markdown_text, processing_method)
        """
        start_time = time.time()
        
        log_file_processing(os.path.basename(pdf_path), 'pdf', 'started')
        
        try:
            # Step 1: Check if PDF has text layer
            logger.info("Checking for text layer...")
            has_text, confidence = has_text_layer(pdf_path)
            
            if has_text:
                # PDF has text layer - use direct extraction (fast!)
                logger.info(f"✅ Text layer detected (confidence: {confidence:.2f})")
                logger.info("Using direct text extraction (no OCR needed)")
                
                markdown = extract_text_with_pdfplumber(pdf_path)
                method = "direct_extraction"
                
                logger.info("Successfully extracted text from PDF")
            else:
                # PDF is scanned - use OCR
                logger.info(f"❌ No text layer detected (confidence: {confidence:.2f})")
                logger.info(f"Using Groq API with {Config.PRIMARY_MODEL} for OCR")
                
                markdown = self.ocr_service.ocr_pdf(pdf_path)
                method = "groq_ocr"
                
                logger.info("Successfully OCR'd PDF")
            
            # Get page count
            num_pages = get_page_count(pdf_path)
            processing_time = time.time() - start_time
            
            log_file_processing(os.path.basename(pdf_path), 'pdf', 'completed', 
                              f"({num_pages} pages, {processing_time:.2f}s, method: {method})")
            log_processing_summary(os.path.basename(pdf_path), processing_time, num_pages, method)
            
            return markdown, method
            
        except Exception as e:
            log_file_processing(os.path.basename(pdf_path), 'pdf', 'failed', str(e))
            raise
    
    def process_docx(self, docx_path: str) -> Tuple[str, str]:
        """
        Process DOCX/DOC file.
        
        Args:
            docx_path: Path to DOCX file
            
        Returns:
            Tuple of (markdown_text, processing_method)
        """
        start_time = time.time()
        
        log_file_processing(os.path.basename(docx_path), 'docx', 'started')
        
        try:
            markdown = extract_text_from_docx(docx_path)
            processing_time = time.time() - start_time
            
            log_file_processing(os.path.basename(docx_path), 'docx', 'completed', 
                              f"({processing_time:.2f}s)")
            
            return markdown, "docx_extraction"
            
        except Exception as e:
            log_file_processing(os.path.basename(docx_path), 'docx', 'failed', str(e))
            raise
    
    def process_document(self, file_path: str) -> Tuple[str, str]:
        """
        Process document and return markdown.
        
        Args:
            file_path: Path to document file
            
        Returns:
            Tuple of (markdown_text, processing_method)
        """
        file_type = self._get_file_type(file_path)
        
        if file_type == 'pdf':
            return self.process_pdf(file_path)
        elif file_type == 'docx':
            return self.process_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path}")
