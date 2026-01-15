"""
DOCX utility functions.

Stage: Extraction Container - OCR Processing
"""
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from typing import List
from logger import logger


def extract_text_from_docx(docx_path: str) -> str:
    """
    Extract text and tables from DOCX file.
    
    Args:
        docx_path: Path to DOCX file
        
    Returns:
        Markdown-formatted text
    """
    try:
        logger.info(f"Extracting text from DOCX: {docx_path}")
        doc = Document(docx_path)
        
        markdown_parts = []
        
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
                table_markdown = table_to_markdown(table)
                if table_markdown:
                    markdown_parts.append(f"\n{table_markdown}\n")
        
        result = "\n".join(markdown_parts)
        logger.info("Successfully extracted text from DOCX")
        return result
    except Exception as e:
        logger.error(f"Error extracting text from DOCX: {e}")
        raise


def table_to_markdown(table: Table) -> str:
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
