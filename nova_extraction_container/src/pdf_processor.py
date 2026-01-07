"""
PDF processor with text extraction and image conversion capabilities.
"""
import os
import base64
from typing import List, Optional
from io import BytesIO
from PIL import Image
import pdfplumber
from pdf2image import convert_from_path
import re
import arabic_reshaper
from bidi.algorithm import get_display

from logger import logger
from src.text_layer_detector import has_text_layer


class PDFProcessor:
    """PDF processor for text extraction and image conversion."""
    
    def __init__(self):
        """Initialize PDF processor."""
        pass
    
    def _fix_arabic_text(self, text: str) -> str:
        """
        Fix Arabic text by reversing if necessary.
        pdfplumber often extracts Arabic in visual order (L-R), reverse to logical (R-L).
        
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
        if len(arabic_chars) / len(text) > 0.3:  # Threshold to treat as Arabic
            # Reverse the string to convert Visual → Logical
            reversed_text = text[::-1]
            
            # Re-reverse numbers to restore them
            return re.sub(r'\d+', lambda m: m.group(0)[::-1], reversed_text)
        
        return text
    
    def extract_text(self, pdf_path: str) -> str:
        """
        Extract text from PDF with text layer.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text
        """
        logger.info(f"Extracting text from PDF: {pdf_path}")
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"PDF has {total_pages} pages")
                
                text_parts = []
                
                for i, page in enumerate(pdf.pages, 1):
                    logger.debug(f"Extracting page {i}/{total_pages}")
                    
                    # Extract text
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
                logger.info(f"Successfully extracted {len(full_text)} characters from {total_pages} pages")
                return full_text
                
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise
    
    def _table_to_text(self, table: List[List[str]], table_num: int) -> str:
        """
        Convert table to text format.
        
        Args:
            table: 2D list of table cells
            table_num: Table number
            
        Returns:
            Text representation
        """
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
    
    def convert_to_images(self, pdf_path: str, dpi: int = 300) -> List[Image.Image]:
        """
        Convert PDF pages to images.
        
        Args:
            pdf_path: Path to PDF file
            dpi: Resolution in DPI (default: 300)
            
        Returns:
            List of PIL Image objects
        """
        logger.info(f"Converting PDF to images at {dpi} DPI: {pdf_path}")
        
        try:
            images = convert_from_path(pdf_path, dpi=dpi)
            logger.info(f"Converted {len(images)} pages to images")
            return images
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            raise
    
    def image_to_base64(self, image: Image.Image, format: str = 'JPEG', quality: int = 95) -> str:
        """
        Convert PIL Image to base64 string.
        
        Args:
            image: PIL Image object
            format: Image format (JPEG, PNG)
            quality: JPEG quality (1-100)
            
        Returns:
            Base64-encoded string
        """
        buffered = BytesIO()
        
        # Convert RGBA to RGB for JPEG
        if format == 'JPEG' and image.mode == 'RGBA':
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[3])  # Use alpha channel as mask
            image = rgb_image
        
        image.save(buffered, format=format, quality=quality)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    def process(self, pdf_path: str) -> tuple[str, Optional[List[Image.Image]]]:
        """
        Process PDF: detect text layer and extract text or convert to images.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            (text, images): Extracted text if has text layer, else images
                           One of them will be None
        """
        logger.info(f"Processing PDF: {os.path.basename(pdf_path)}")
        
        # Detect text layer
        has_text, confidence = has_text_layer(pdf_path)
        
        if has_text:
            logger.info(f"✅ Text layer detected (confidence: {confidence:.2f})")
            text = self.extract_text(pdf_path)
            return text, None
        else:
            logger.info(f"❌ No text layer detected (confidence: {confidence:.2f})")
            logger.info("Converting to images for multimodal processing")
            images = self.convert_to_images(pdf_path)
            return None, images
