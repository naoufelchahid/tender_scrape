"""
PDF utility functions.

Stage: Extraction Container - OCR Processing
"""
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from typing import List
from logger import logger
from config import Config


def extract_text_with_pdfplumber(pdf_path: str) -> str:
    """
    Extract text from PDF using pdfplumber.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted text in markdown format
    """
    try:
        markdown_parts = []
        
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"Extracting text from {total_pages} pages")
            
            for page_num, page in enumerate(pdf.pages, 1):
                # Extract text
                text = page.extract_text()
                
                if text:
                    markdown_parts.append(f"## Page {page_num}\n\n{text}\n")
                
                # Extract tables as markdown
                tables = page.extract_tables()
                if tables:
                    for table_idx, table in enumerate(tables, 1):
                        table_md = _table_to_markdown(table)
                        markdown_parts.append(f"\n### Table {table_idx}\n\n{table_md}\n")
        
        return "\n---\n\n".join(markdown_parts)
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise


def _table_to_markdown(table: List[List[str]]) -> str:
    """
    Convert table to markdown format.
    
    Args:
        table: 2D list of table cells
        
    Returns:
        Markdown table string
    """
    if not table or len(table) < 2:
        return ""
    
    markdown_lines = []
    
    # Header row
    header = table[0]
    header_cells = [str(cell or "").strip() for cell in header]
    markdown_lines.append("| " + " | ".join(header_cells) + " |")
    
    # Separator
    separator = "|" + "|".join(["---" for _ in header_cells]) + "|"
    markdown_lines.append(separator)
    
    # Data rows
    for row in table[1:]:
        cells = [str(cell or "").strip() for cell in row]
        # Pad row if needed
        while len(cells) < len(header_cells):
            cells.append("")
        markdown_lines.append("| " + " | ".join(cells[:len(header_cells)]) + " |")
    
    return "\n".join(markdown_lines)


def convert_pdf_to_images(pdf_path: str, dpi: int = None) -> List[Image.Image]:
    """
    Convert PDF pages to images.
    
    Args:
        pdf_path: Path to PDF file
        dpi: DPI for image conversion (default: from Config)
        
    Returns:
        List of PIL Image objects
    """
    dpi = dpi or Config.PDF_DPI
    
    try:
        logger.info(f"Converting PDF to images at {dpi} DPI")
        images = convert_from_path(pdf_path, dpi=dpi)
        logger.info(f"Converted PDF to {len(images)} images")
        return images
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}")
        raise


def combine_page_markdown(pages: List[str]) -> str:
    """
    Combine page markdown into a single document.
    
    Args:
        pages: List of page markdown strings
        
    Returns:
        Combined markdown
    """
    return "\n\n---\n\n".join(pages)
