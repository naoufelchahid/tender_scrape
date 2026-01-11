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
            # Check if file exists
            if not os.path.exists(word_path):
                logger.error(f"Word file not found: {word_path}")
                return None, None
            
            # Check file size (skip if too small or empty)
            file_size = os.path.getsize(word_path)
            if file_size < 100:  # Less than 100 bytes is likely corrupted
                logger.warning(f"Word file too small ({file_size} bytes), likely corrupted: {word_path}")
                return None, None
            
            if word_path.endswith('.docx'):
                try:
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
                    
                    # Check if we extracted any text
                    if not full_text.strip():
                        logger.warning(f"No text extracted from Word document: {os.path.basename(word_path)}")
                        return None, None
                    
                    logger.info(f"Extracted {len(full_text)} characters from Word document")
                    return full_text, None
                    
                except Exception as docx_error:
                    # Specific handling for corrupted .docx files
                    error_msg = str(docx_error)
                    if "Package not found" in error_msg or "BadZipFile" in error_msg:
                        logger.warning(f"Corrupted or invalid .docx file: {os.path.basename(word_path)} - {error_msg}")
                    else:
                        logger.error(f"Error reading .docx file: {error_msg}")
                    return None, None
            else:
                # .doc files need conversion to .docx
                logger.info(f"Converting .doc file to .docx: {os.path.basename(word_path)}")
                docx_path = self._convert_doc_to_docx(word_path)
                if docx_path:
                    # Recursively process the converted .docx file
                    return self._process_word(docx_path)
                else:
                    logger.warning(f"Failed to convert .doc file: {os.path.basename(word_path)}")
                    return None, None
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
                # .xls files need conversion to .xlsx
                logger.info(f"Converting .xls file to .xlsx: {os.path.basename(excel_path)}")
                xlsx_path = self._convert_xls_to_xlsx(excel_path)
                if xlsx_path:
                    # Recursively process the converted .xlsx file
                    return self._process_excel(xlsx_path)
                else:
                    logger.warning(f"Failed to convert .xls file: {os.path.basename(excel_path)}")
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
    
    def _convert_doc_to_docx(self, doc_path: str) -> Optional[str]:
        """Convert .doc file to .docx using LibreOffice.
        
        Args:
            doc_path: Path to .doc file
            
        Returns:
            Path to converted .docx file, or None if conversion failed
        """
        import subprocess
        import tempfile
        
        try:
            # Create temp directory for conversion
            temp_dir = os.path.dirname(doc_path)
            
            # Run LibreOffice conversion
            # --headless: run without GUI
            # --convert-to docx: convert to .docx format
            # --outdir: output directory
            cmd = [
                'libreoffice',
                '--headless',
                '--convert-to', 'docx',
                '--outdir', temp_dir,
                doc_path
            ]
            
            logger.info(f"Running LibreOffice conversion: {' '.join(cmd)}")
            
            # Run conversion with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode == 0:
                # Conversion successful - find the output file
                base_name = os.path.splitext(os.path.basename(doc_path))[0]
                docx_path = os.path.join(temp_dir, f"{base_name}.docx")
                
                if os.path.exists(docx_path):
                    logger.info(f"✅ Successfully converted .doc to .docx: {os.path.basename(docx_path)}")
                    return docx_path
                else:
                    logger.error(f"Conversion succeeded but output file not found: {docx_path}")
                    return None
            else:
                logger.error(f"LibreOffice conversion failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error(f"LibreOffice conversion timed out for {os.path.basename(doc_path)}")
            return None
        except FileNotFoundError:
            logger.error("LibreOffice not found - cannot convert .doc files")
            return None
        except Exception as e:
            logger.error(f"Error converting .doc file: {e}")
            return None

    def _convert_xls_to_xlsx(self, xls_path: str) -> Optional[str]:
        """Convert .xls file to .xlsx using LibreOffice.
        
        Args:
            xls_path: Path to .xls file
            
        Returns:
            Path to converted .xlsx file, or None if conversion failed
        """
        import subprocess
        
        try:
            # Create temp directory for conversion
            temp_dir = os.path.dirname(xls_path)
            
            # Run LibreOffice conversion
            cmd = [
                'libreoffice',
                '--headless',
                '--convert-to', 'xlsx',
                '--outdir', temp_dir,
                xls_path
            ]
            
            logger.info(f"Running LibreOffice conversion: {' '.join(cmd)}")
            
            # Run conversion with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode == 0:
                # Conversion successful - find the output file
                base_name = os.path.splitext(os.path.basename(xls_path))[0]
                xlsx_path = os.path.join(temp_dir, f"{base_name}.xlsx")
                
                if os.path.exists(xlsx_path):
                    logger.info(f"✅ Successfully converted .xls to .xlsx: {os.path.basename(xlsx_path)}")
                    return xlsx_path
                else:
                    logger.error(f"Conversion succeeded but output file not found: {xlsx_path}")
                    return None
            else:
                logger.error(f"LibreOffice conversion failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error(f"LibreOffice conversion timed out for {os.path.basename(xls_path)}")
            return None
        except FileNotFoundError:
            logger.error("LibreOffice not found - cannot convert .xls files")
            return None
        except Exception as e:
            logger.error(f"Error converting .xls file: {e}")
            return None
