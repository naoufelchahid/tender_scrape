"""
Direct text extraction from PDFs with text layers.
Extracts text and tables without OCR for faster processing.
"""
import pdfplumber
import pandas as pd
from typing import List, Dict, Any
import abc
import re
import arabic_reshaper
from bidi.algorithm import get_display
from logger import logger


class TextExtractor:
    """Extract text directly from PDFs with text layers."""
    
    def __init__(self):
        """Initialize text extractor."""
        pass
        
    def _fix_arabic_text(self, text: str) -> str:
        """
        Fix Arabic text by reversing if necessary.
        pdfplumber often extracts Arabic in visual order (L-R), so we reverse it to logical (R-L).
        
        Args:
            text: Input text
            
        Returns:
            Corrected text
        """
        if not text:
            return text
            
        # Check if text contains Arabic characters
        arabic_chars = [char for char in text if '\u0600' <= char <= '\u06FF']
        if not arabic_chars:
            return text
            
        # Calculate ratio of Arabic characters
        if len(arabic_chars) / len(text) > 0.3:  # Threshold to treat line as Arabic
            # Reverse the string to convert Visual -> Logical
            reversed_text = text[::-1]
            
            # Re-reverse numbers to restore them (since they were reversed by the line reverse)
            # Find all digit sequences and reverse them back
            return re.sub(r'\d+', lambda m: m.group(0)[::-1], reversed_text)
                
        return text
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text directly from PDF with text layer.
        Preserves tables using pandas.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Markdown formatted text
        """
        logger.info(f"Extracting text from PDF: {pdf_path}")
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"PDF has {total_pages} pages")
                
                markdown_pages = []
                
                for i, page in enumerate(pdf.pages, 1):
                    logger.info(f"Extracting page {i}/{total_pages}")
                    page_markdown = self._extract_page(page, i)
                    markdown_pages.append(f"## Page {i}\n\n{page_markdown}\n")
                
                # Combine all pages
                final_markdown = "\n---\n\n".join(markdown_pages)
                
                logger.info(f"Successfully extracted text from {total_pages} pages")
                return final_markdown
                
        except Exception as e:
            logger.error(f"Error extracting text from PDF {pdf_path}: {e}")
            raise
    
    def _extract_page(self, page: Any, page_num: int) -> str:
        """
        Extract text and tables from a single page.
        
        Args:
            page: pdfplumber page object
            page_num: Page number
            
        Returns:
            Markdown formatted text for the page
        """
        elements = []
        
        try:
            # Extract tables first
            tables = page.extract_tables()
            
            if tables:
                logger.debug(f"Page {page_num}: Found {len(tables)} tables")
                
                # Extract text
                text = page.extract_text()
                
                # Add text before tables
                if text:
                    elements.append(self._fix_arabic_text(text.strip()))
                
                # Add tables as markdown
                for idx, table in enumerate(tables, 1):
                    table_md = self._table_to_markdown(table, idx)
                    if table_md:
                        elements.append(table_md)
            else:
                # No tables, just extract text
                text = page.extract_text()
                if text:
                    elements.append(self._fix_arabic_text(text.strip()))
            
            return "\n\n".join(elements) if elements else "[No text extracted]"
            
        except Exception as e:
            logger.error(f"Error extracting page {page_num}: {e}")
            return f"[Error extracting page {page_num}]"
    
    def _table_to_markdown(self, table: List[List[str]], table_num: int) -> str:
        """
        Convert table to markdown format.
        
        Args:
            table: 2D list of table cells
            table_num: Table number
            
        Returns:
            Markdown formatted table
        """
        try:
            if not table or len(table) < 2:
                return ""
            
            # Clean table data
            cleaned_table = []
            for row in table:
                cleaned_row = [self._fix_arabic_text(str(cell).strip()) if cell else "" for cell in row]
                cleaned_table.append(cleaned_row)
            
            # Create DataFrame
            df = pd.DataFrame(cleaned_table[1:], columns=cleaned_table[0])
            
            # Convert to markdown
            markdown = f"\n**Table {table_num}**\n\n"
            markdown += df.to_markdown(index=False)
            markdown += "\n"
            
            return markdown
            
        except Exception as e:
            logger.warning(f"Error converting table {table_num} to markdown: {e}")
            # Fallback: simple text representation
            return self._table_to_simple_text(table, table_num)
    
    def _table_to_simple_text(self, table: List[List[str]], table_num: int) -> str:
        """
        Convert table to simple text format (fallback).
        
        Args:
            table: 2D list of table cells
            table_num: Table number
            
        Returns:
            Simple text representation of table
        """
        try:
            lines = [f"\n**Table {table_num}**\n"]
            
            for row in table:
                row_text = " | ".join(self._fix_arabic_text(str(cell).strip()) if cell else "" for cell in row)
                lines.append(row_text)
            
            return "\n".join(lines) + "\n"
            
        except Exception as e:
            logger.error(f"Error creating simple text table: {e}")
            return f"\n[Table {table_num} - extraction failed]\n"


def extract_text(pdf_path: str) -> str:
    """
    Convenience function to extract text from PDF.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Markdown formatted text
    """
    extractor = TextExtractor()
    return extractor.extract_text_from_pdf(pdf_path)
