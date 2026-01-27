"""
DOCX processor with text extraction and table conversion.
"""
import os
from typing import List
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from config import Config
from logger import logger
from language_detector import detect_language_from_text, is_arabic_text


class DOCXProcessor:
    """DOCX text extraction and table conversion processor."""
    
    def __init__(self):
        """Initialize DOCX processor."""
        pass
    
    def _table_to_markdown(self, table: Table) -> str:
        """
        Convert DOCX table to markdown format.
        
        Args:
            table: python-docx Table object
            
        Returns:
            Markdown table string
        """
        if not table.rows:
            return ""
        
        markdown_lines = []
        
        # Process first row as header
        header_row = table.rows[0]
        header_cells = [cell.text.strip() for cell in header_row.cells]
        
        # Create header
        markdown_lines.append("| " + " | ".join(header_cells) + " |")
        
        # Create separator
        separator = "|" + "|".join(["---" for _ in header_cells]) + "|"
        markdown_lines.append(separator)
        
        # Process data rows
        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]
            markdown_lines.append("| " + " | ".join(cells) + " |")
        
        return "\n".join(markdown_lines)
    
    def _extract_text(self, doc: Document) -> str:
        """
        Extract text from DOCX with structure preservation.
        
        Args:
            doc: python-docx Document object
            
        Returns:
            Markdown-formatted text
        """
        markdown_parts = []
        table_count = 0
        
        for element in doc.element.body:
            # Handle paragraphs
            if element.tag.endswith('p'):
                para = Paragraph(element, doc)
                text = para.text.strip()
                
                if not text:
                    continue
                
                # Check for heading styles
                style_name = para.style.name if para.style else ""
                
                if 'Heading 1' in style_name:
                    markdown_parts.append(f"\n# {text}\n")
                elif 'Heading 2' in style_name:
                    markdown_parts.append(f"\n## {text}\n")
                elif 'Heading 3' in style_name:
                    markdown_parts.append(f"\n### {text}\n")
                elif 'Title' in style_name:
                    markdown_parts.append(f"\n# {text}\n")
                else:
                    # Handle list items
                    if style_name and 'List' in style_name:
                        markdown_parts.append(f"- {text}")
                    else:
                        # Regular paragraph
                        markdown_parts.append(text)
            
            # Handle tables
            elif element.tag.endswith('tbl'):
                table = Table(element, doc)
                table_markdown = self._table_to_markdown(table)
                if table_markdown:
                    table_count += 1
                    markdown_parts.append(f"\n**Table {table_count}**\n<table_start>\n{table_markdown}\n<table_end>\n")
        
        return "\n".join(markdown_parts)
    
    def process(self, docx_path: str) -> str:
        """
        Process DOCX file and return markdown.
        
        Args:
            docx_path: Path to DOCX file
            
        Returns:
            Markdown text
        """
        logger.info(f"Processing DOCX: {docx_path}")
        
        try:
            doc = Document(docx_path)
            
            # Extract text and tables
            markdown_content = self._extract_text(doc)
            
            # Detect language
            lang = detect_language_from_text(markdown_content[:500])
            is_arabic = is_arabic_text(markdown_content[:500])
            
            if is_arabic:
                logger.info("Detected Arabic content in DOCX")
            
            logger.info(f"Successfully processed DOCX file")
            return markdown_content
        except Exception as e:
            logger.error(f"Error processing DOCX {docx_path}: {e}")
            raise


def process_docx(docx_path: str) -> str:
    """
    Process DOCX file to markdown.
    
    Args:
        docx_path: Path to DOCX file
        
    Returns:
        Markdown text
    """
    processor = DOCXProcessor()
    return processor.process(docx_path)
