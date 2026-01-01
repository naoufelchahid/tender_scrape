"""
PDF OCR processor with layout preservation.
Uses direct text extraction for PDFs with text layers.
Uses Gemini Flash 1.5 OCR for scanned PDFs.
"""
import os
import base64
from typing import List, Optional
from pdf2image import convert_from_path
from PIL import Image
import io
from openai import OpenAI
import boto3
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config
from logger import logger
from prompts import create_ocr_messages
from language_detector import detect_language_from_pdf_page
from text_layer_detector import has_text_layer
from processors.text_extractor import extract_text


class PDFProcessor:
    """PDF OCR processor."""
    
    def __init__(self):
        """Initialize PDF processor with API clients."""
        # OpenRouter client
        self.openrouter_client = OpenAI(
            api_key=Config.OPENROUTER_API_KEY,
            base_url=Config.OPENROUTER_BASE_URL
        )
        
        # Bedrock client
        self.bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=Config.AWS_REGION
        )
    
    def _image_to_base64(self, image: Image.Image) -> str:
        """
        Convert PIL Image to base64 string.
        
        Args:
            image: PIL Image object
            
        Returns:
            Base64-encoded string
        """
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    def _ocr_page_openrouter(self, image: Image.Image, page_num: int, 
                             total_pages: int, document_type: str = "tender",
                             is_arabic: bool = False) -> str:
        """
        OCR single page using OpenRouter API.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            document_type: Type of document
            is_arabic: Whether document is in Arabic
            
        Returns:
            Markdown text
        """
        try:
            image_base64 = self._image_to_base64(image)
            messages = create_ocr_messages(
                image_base64=image_base64,
                document_type=document_type,
                page_number=page_num,
                total_pages=total_pages,
                is_arabic=is_arabic
            )
            
            response = self.openrouter_client.chat.completions.create(
                model=Config.OPENROUTER_MODEL,
                messages=messages,
                max_tokens=4000,
                temperature=0.1
            )
            
            markdown_text = response.choices[0].message.content
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with OpenRouter: {e}")
            return f"[ERROR: OCR failed for page {page_num}]"
    
    def _ocr_page_bedrock(self, image: Image.Image, page_num: int,
                          total_pages: int, document_type: str = "tender") -> str:
        """
        OCR single page using AWS Bedrock Nova Lite.
        
        Args:
            image: PIL Image of page
            page_num: Page number
            total_pages: Total number of pages
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        try:
            # Initialize Bedrock client (Nova models only available in us-east-1)
            bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
            
            image_base64 = self._image_to_base64(image)
            
            # Create Bedrock request with image
            messages = create_ocr_messages(
                image_base64=image_base64,
                document_type=document_type,
                page_number=page_num,
                total_pages=total_pages,
                is_arabic=True
            )
            
            # Nova Lite request format
            request_body = {
                "messages": messages,
                "max_tokens": 4000,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            response = bedrock.invoke_model(
                modelId=Config.BEDROCK_MODEL_ID,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            markdown_text = response_body['content'][0]['text']
            
            return markdown_text
        except Exception as e:
            logger.error(f"Error OCR page {page_num} with Bedrock: {e}")
            # Fallback to OpenRouter
            logger.info(f"Falling back to OpenRouter for page {page_num}")
            return self._ocr_page_openrouter(image, page_num, total_pages, 
                                            document_type, is_arabic=True)
    
    def process(self, pdf_path: str, document_type: str = "tender") -> str:
        """
        Process PDF file and return markdown.
        Detects if PDF has text layer and uses appropriate method.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Type of document (for specialized prompts)
            
        Returns:
            Complete markdown text
        """
        logger.info(f"Processing PDF: {pdf_path}")
        
        try:
            # Step 1: Check if PDF has text layer
            logger.info("Checking for text layer...")
            has_text, confidence = has_text_layer(pdf_path)
            
            if has_text:
                # PDF has text layer - use direct extraction (fast!)
                logger.info(f"✅ Text layer detected (confidence: {confidence:.2f})")
                logger.info("Using direct text extraction (no OCR needed)")
                markdown = extract_text(pdf_path)
                logger.info("Successfully extracted text from PDF")
                return markdown
            else:
                # PDF is scanned - use OCR
                logger.info(f"❌ No text layer detected (confidence: {confidence:.2f})")
                logger.info(f"Using {Config.OPENROUTER_MODEL} OCR for scanned PDF")
                return self._ocr_scanned_pdf(pdf_path, document_type)
                
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {e}")
            raise
    
    def _ocr_scanned_pdf(self, pdf_path: str, document_type: str) -> str:
        """
        OCR a scanned PDF using parallel processing.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Type of document
            
        Returns:
            Markdown text
        """
        try:
            # Convert PDF to images
            logger.info("Converting PDF to images...")
            images = convert_from_path(pdf_path, dpi=300)
            total_pages = len(images)
            logger.info(f"PDF has {total_pages} pages. Starting parallel OCR with {Config.MAX_WORKERS} workers.")
            
            # Helper function for parallel processing
            def process_single_page(args):
                idx, image = args
                try:
                    logger.info(f"Starting OCR page {idx}/{total_pages}...")
                    content = self._ocr_page_openrouter(
                        image, idx, total_pages, document_type, is_arabic=False
                    )
                    return idx, f"## Page {idx}\n\n{content}\n"
                except Exception as e:
                    logger.error(f"Error processing page {idx}: {e}")
                    return idx, f"## Page {idx}\n\n[ERROR: OCR Failed]\n"

            # Execute parallel processing
            markdown_map = {}
            with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
                # Prepare tasks
                tasks = [(i, img) for i, img in enumerate(images, 1)]
                
                # Submit all tasks
                future_to_page = {executor.submit(process_single_page, task): task[0] for task in tasks}
                
                # Process results as they complete
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        idx, content = future.result()
                        markdown_map[idx] = content
                        logger.info(f"Completed OCR page {idx}/{total_pages}")
                    except Exception as e:
                        logger.error(f"Unhandled exception for page {page_num}: {e}")
                        markdown_map[page_num] = f"## Page {page_num}\n\n[ERROR: Exception]\n"

            # Reassemble pages in correct order
            markdown_pages = [markdown_map[i] for i in range(1, total_pages + 1)]
            
            # Combine all pages
            final_markdown = "\n---\n\n".join(markdown_pages)
            
            logger.info(f"Successfully OCR'd PDF with {total_pages} pages")
            return final_markdown
            
        except Exception as e:
            logger.error(f"Error OCR'ing scanned PDF: {e}")
            raise



def process_pdf(pdf_path: str, document_type: str = "tender") -> str:
    """
    Process PDF file to markdown.
    
    Args:
        pdf_path: Path to PDF file
        document_type: Type of document
        
    Returns:
        Markdown text
    """
    processor = PDFProcessor()
    return processor.process(pdf_path, document_type)
