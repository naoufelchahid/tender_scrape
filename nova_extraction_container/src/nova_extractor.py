"""
Nova Lite Multimodal Extractor using Groq API with LangChain.
Provides structured data extraction from tender documents with fallback chain.
"""
import json
import base64
from io import BytesIO
from typing import List, Dict, Any, Optional, Union
from PIL import Image
from groq import Groq
from langchain_core.output_parsers import JsonOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from logger import logger, log_model_fallback
from src.models import ExtractionOutput, TenderMetadata, LotMetadata, ProductItem, ProductList
from src.document_processor import DocumentProcessor
from src.prompts import get_extraction_prompt


class NovaExtractor:
    """Multimodal extraction service using Groq API with LangChain."""
    
    def __init__(self):
        """Initialize Nova extractor."""
        # Model fallback chain
        self.models = [
            Config.PRIMARY_MODEL,
            Config.FALLBACK_MODEL_1,
            Config.FALLBACK_MODEL_2
        ]
        
        # Initialize Groq client
        self.client = Groq(api_key=Config.GROQ_API_KEY)
        
        self.document_processor = DocumentProcessor()
        
        logger.info(f"Nova Extractor initialized with Groq fallback chain: {' → '.join(self.models)}")
    
    def extract_tender_data(self, file_path: str, doc_type: str, tender_ref: str = None) -> Optional[ExtractionOutput]:
        """
        Extract structured data from tender document (any file type).
        
        Args:
            file_path: Path to document file (PDF, Word, Excel, Image)
            doc_type: Document type (avis, rc, cps, bdp, etc.) - used for logging only
            tender_ref: Tender reference to set in output (from folder name)
            
        Returns:
            ExtractionOutput with metadata, lots, and products
        """
        logger.info(f"Extracting data from {file_path} (type: {doc_type})")
        
        # Process document (any file type - returns text or images)
        text, images = self.document_processor.process_file(file_path)
        
        # Check if we got any usable content
        if text is None and images is None:
            logger.warning(f"No content extracted from {file_path} - file may be corrupted or empty")
            return None
        
        # If we have text but it's empty, also skip
        if text is not None and not text.strip():
            logger.warning(f"Empty text extracted from {file_path}")
            return None
        
        # Use universal extraction prompt for ALL documents
        # The LLM will determine what to extract based on content
        prompt = get_extraction_prompt()
        
        # Try with fallback through model chain
        result = self._try_with_fallback(
            self._process_with_model,
            text, images, prompt, ExtractionOutput
        )
        
        # Post-process results
        if result:
            # Set tender_reference from folder name if provided
            if tender_ref and result.tender_info:
                result.tender_info.tender_reference = tender_ref
            
            # Post-process lots
            if result.lots:
                # Ghost Lot 0 filtering: If we have real lots, remove any lot "0"
                real_lots = [l for l in result.lots if l.lot_number and l.lot_number != "0"]
                if real_lots and len(result.lots) > len(real_lots):
                    logger.info(f"Removing ghost 'Lot 0' because {len(real_lots)} real lots were found.")
                    result.lots = real_lots
                
                # Update lot references
                for lot in result.lots:
                    clean_num = lot.lot_number.lower().replace("lot", "").strip()
                    lot.lot_reference = f"{result.tender_info.tender_reference}_{clean_num}"
            
            # Post-process products
            if result.products:
                valid_products = []
                for p in result.products:
                    # Filter: Name "Unknown" AND Quantity 0
                    is_unknown = p.designation and "unknown" in p.designation.lower()
                    is_zero_qty = p.quantity is None or p.quantity == 0
                    
                    if is_unknown and is_zero_qty:
                        continue
                    valid_products.append(p)
                
                result.products = valid_products
        
        return result
    

    
    def _try_with_fallback(self, func, *args, **kwargs):
        """Execute function with fallback through model chain."""
        last_error = None
        
        for model_id in self.models:
            try:
                logger.info(f"Attempting with model: {model_id}")
                result = func(*args, model_id=model_id, **kwargs)
                if result:
                    logger.info(f"✅ Success with {model_id}")
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"❌ Failed with {model_id}: {str(e)}")
                
                # Log fallback if not last model
                current_idx = self.models.index(model_id)
                if current_idx < len(self.models) - 1:
                    next_model = self.models[current_idx + 1]
                    log_model_fallback(model_id, next_model, str(e))
                continue
        
        # All models failed
        logger.error(f"All models failed. Last error: {last_error}")
        return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True
    )
    def _process_with_model(self, text: Optional[str], images: Optional[List[Image.Image]], 
                           prompt: str, output_class, model_id: str):
        """
        Process document with specified model using LangChain (with retries).
        
        Args:
            text: Extracted text (if available)
            images: List of images (if document was image-based)
            prompt: Extraction prompt
            output_class: Pydantic class for output parsing
            model_id: Model identifier
            
        Returns:
            Parsed output instance
        """
        # Create JSON output parser
        parser = JsonOutputParser(pydantic_object=output_class)
        
        if images:
            # Multimodal: send images
            logger.info(f"Processing {len(images)} images with {model_id}")
            content = self._build_multimodal_content(prompt, images)
            
            # Call Groq API with vision support
            response = self.client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
                    {"role": "user", "content": content}
                ],
                temperature=0.0,
                max_tokens=4000
            )
            
        else:
            # Text-based: send extracted text
            logger.info(f"Processing text ({len(text)} chars) with {model_id}")
            
            # Limit text to avoid token overflow
            max_chars = 100000  # ~25K tokens
            text_truncated = text[:max_chars]
            
            full_prompt = f"{prompt}\n\nDocument Text:\n{text_truncated}"
            
            # Call Groq API
            response = self.client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
                    {"role": "user", "content": full_prompt}
                ],
                temperature=0.0,
                max_tokens=4000
            )
        
        # Parse the response content to dict
        response_content = response.choices[0].message.content
        parsed_dict = parser.parse(response_content)
        
        # Convert dict to Pydantic object
        result = output_class(**parsed_dict)
        
        return result
    
    def _image_to_base64(self, image: Image.Image, format: str = 'JPEG', quality: int = 95) -> str:
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
            rgb_image.paste(image, mask=image.split()[3])
            image = rgb_image
        
        image.save(buffered, format=format, quality=quality)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    def _build_multimodal_content(self, prompt: str, images: List[Image.Image]) -> List[Dict]:
        """Build content for multimodal input (LangChain format)."""
        # Groq limit: maximum 5 images per request
        max_images = min(len(images), 5)
        
        content_parts = [{"type": "text", "text": prompt}]
        
        for idx, image in enumerate(images[:max_images], 1):
            image_base64 = self._image_to_base64(image)
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })
        
        return content_parts
