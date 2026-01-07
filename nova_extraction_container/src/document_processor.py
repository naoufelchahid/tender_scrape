"""
Document processor supporting multiple file types (PDF, Word, Excel, Images).
Intelligently detects text layers and uses text extraction when available.
"""
import os
from typing import Optional, List, Tuple
from PIL import Image
import pdfplumber
from pdf2image import convert_from_path
import docx
import openpyxl
import re

from logger import logger
from src.text_layer_detector import has_text_layer


class DocumentProcessor:
    """Universal document processor for all supported file types."""
    
    def __init__(self):
        """Initialize document processor."""
        pass
    
    def _fix_arabic_text(self, text: str) -> str:
        """
        Fix Arabic text by reversing if necessary.
        
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
        if len(arabic_chars) / len(text) > 0.3:
            # Reverse the string to convert Visual → Logical
            reversed_text = text[::-1]
            # Re-reverse numbers
            return re.sub(r'\d+', lambda m: m.group(0)[::-1], reversed_text)
        
        return text
    
    def process_file(self, file_path: str) -> Tuple[Optional[str], Optional[List[Image.Image]]]:
        """
        Process any supported file type.
        
        Args:
            file_path: Path to file
            
        Returns:
            (text, images): Either extracted text or images for multimodal processing
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        logger.info(f"Processing {file_ext} file: {os.path.basename(file_path)}")
        
        if file_ext == '.pdf':
            return self._process_pdf(file_path)
        elif file_ext in ['.docx', '.doc']:
            return self._process_word(file_path)
        elif file_ext in ['.xlsx', '.xls']:
            return self._process_excel(file_path)
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            return self._process_image(file_path)
        else:
            logger.warning(f"Unsupported file type: {file_ext}")
            return None, None
    
    def _process_pdf(self, pdf_path: str) -> Tuple[Optional[str], Optional[List[Image.Image]]]:
        """Process PDF file."""
        # Check for text layer
        has_text, confidence = has_text_layer(pdf_path)
        
        if has_text:
            logger.info(f"✅ PDF has text layer (confidence: {confidence:.2f}) - using text extraction")
            return self._extract_pdf_text(pdf_path), None
        else:
            logger.info(f"❌ PDF has no text layer (confidence: {confidence:.2f}) - converting to images")
            images = convert_from_path(pdf_path, dpi=300)
            logger.info(f"Converted {len(images)} pages to images")
            return None, images
    
    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF with text layer."""
        text_parts = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    fixed_text = self._fix_arabic_text(text.strip())
                    text_parts.append(f"=== Page {i} ===\n\n{fixed_text}\n")
                
                # Extract tables
                tables = page.extract_tables()
                if tables:
                    for table_idx, table in enumerate(tables, 1):
                        table_text = self._table_to_text(table, table_idx)
                        text_parts.append(table_text)
        
        full_text = "\n".join(text_parts)
        logger.info(f"Extracted {len(full_text)} characters from PDF")
        return full_text
    
    def _table_to_text(self, table: List[List[str]], table_num: int) -> str:
        """Convert table to text format."""
        try:
            lines = [f"\n--- Table {table_num} ---\n"]
            for row in table:
                row_text = " | ".join(
                    self._fix_arabic_text(str(cell).strip()) if cell else ""
                    for cell in row
                )
                lines.append(row_text)
            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.warning(f"Error converting table {table_num}: {e}")
            return f"\n[Table {table_num} - extraction failed]\n"
    
    def _process_word(self, word_path: str) -> Tuple[Optional[str], None]:
        """Process Word document (.docx, .doc)."""
        try:
            if word_path.endswith('.docx'):
                doc = docx.Document(word_path)
                text_parts = []
                
                for i, para in enumerate(doc.paragraphs):
                    if para.text.strip():
                        text_parts.append(self._fix_arabic_text(para.text))
                
                # Extract tables
                for table_idx, table in enumerate(doc.tables, 1):
                    table_text = self._extract_word_table(table, table_idx)
                    if table_text:
                        text_parts.append(table_text)
                
                full_text = "\n".join(text_parts)
                logger.info(f"Extracted {len(full_text)} characters from Word document")
                return full_text, None
            else:
                # .doc files need conversion - fallback to image processing
                logger.warning(".doc files require conversion - using image fallback")
                # Convert doc to images using LibreOffice (if available)
                return None, self._convert_doc_to_images(word_path)
        except Exception as e:
            logger.error(f"Error processing Word document: {e}")
            return None, None
    
    def _extract_word_table(self, table, table_num: int) -> str:
        """Extract table from Word document."""
        try:
            lines = [f"\n--- Table {table_num} ---\n"]
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                lines.append(self._fix_arabic_text(row_text))
            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.warning(f"Error extracting Word table {table_num}: {e}")
            return ""
    
    def _process_excel(self, excel_path: str) -> Tuple[Optional[str], None]:
        """Process Excel file (.xlsx, .xls)."""
        try:
            if excel_path.endswith('.xlsx'):
                workbook = openpyxl.load_workbook(excel_path, data_only=True)
                text_parts = []
                
                for sheet_name in workbook.sheetnames:
                    sheet = workbook[sheet_name]
                    text_parts.append(f"\n=== Sheet: {sheet_name} ===\n")
                    
                    for row in sheet.iter_rows(values_only=True):
                        row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
                        if row_text.strip():
                            text_parts.append(self._fix_arabic_text(row_text))
                
                full_text = "\n".join(text_parts)
                logger.info(f"Extracted {len(full_text)} characters from Excel file")
                return full_text, None
            else:
                # .xls files need xlrd library or conversion
                logger.warning(".xls files require xlrd library - feature not implemented")
                return None, None
        except Exception as e:
            logger.error(f"Error processing Excel file: {e}")
            return None, None
    
    def _process_image(self, image_path: str) -> Tuple[None, Optional[List[Image.Image]]]:
        """Process image file (.png, .jpg, .jpeg)."""
        try:
            image = Image.open(image_path)
            logger.info(f"Loaded image: {image.size[0]}x{image.size[1]}")
            return None, [image]
        except Exception as e:
            logger.error(f"Error loading image: {e}")
            return None, None
    
    def _convert_doc_to_images(self, doc_path: str) -> Optional[List[Image.Image]]:
        """Convert .doc file to images (requires LibreOffice)."""
        # This would require LibreOffice installed in the container
        # For now, return None to skip
        logger.warning(".doc conversion not implemented")
        return None
