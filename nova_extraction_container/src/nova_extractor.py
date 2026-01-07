"""
Nova Lite Multimodal Extractor using OpenRouter API.
Provides structured data extraction from tender documents with fallback chain.
"""
import json
import base64
from io import BytesIO
from typing import List, Dict, Any, Optional, Union
from PIL import Image
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from logger import logger, log_model_fallback
from src.models import ExtractionOutput, TenderMetadata, LotMetadata, ProductItem, ProductList
from src.document_processor import DocumentProcessor


class NovaExtractor:
    """Multimodal extraction service using OpenRouter API."""
    
    def __init__(self):
        """Initialize Nova extractor."""
        self.client = OpenAI(
            api_key=Config.OPENROUTER_API_KEY,
            base_url=Config.OPENROUTER_BASE_URL
        )
        self.document_processor = DocumentProcessor()
        
        # Model fallback chain
        self.models = [
            Config.PRIMARY_MODEL,
            Config.FALLBACK_MODEL_1,
            Config.FALLBACK_MODEL_2
        ]
        
        logger.info(f"Nova Extractor initialized with fallback chain: {' → '.join(self.models)}")
    
    def extract_tender_data(self, file_path: str, doc_type: str, tender_ref: str = None) -> Optional[ExtractionOutput]:
        """
        Extract structured data from tender document (any file type).
        
        Args:
            file_path: Path to document file (PDF, Word, Excel, Image)
            doc_type: Document type (avis, rc, cps, bdp, etc.)
            tender_ref: Tender reference to set in output (from folder name)
            
        Returns:
            ExtractionOutput with metadata, lots, and products
        """
        logger.info(f"Extracting data from {file_path} (type: {doc_type})")
        
        # Process document (any file type - returns text or images)
        text, images = self.document_processor.process_file(file_path)
        
        # Determine extraction strategy based on document type
        if doc_type in ['avis', 'rc', 'administrative']:
            # Extract metadata and lots
            result = self._extract_metadata(text, images, doc_type)
        elif doc_type in ['bdp', 'product', 'decompte']:
            # Extract products
            result = self._extract_products(text, images, doc_type)
        elif doc_type in ['cps', 'cctp', 'technical']:
            # Extract metadata only (no detailed products)
            result = self._extract_metadata(text, images, doc_type)
        else:
            # Unknown type - try metadata extraction
            logger.warning(f"Unknown document type: {doc_type}, attempting metadata extraction")
            result = self._extract_metadata(text, images, doc_type)
        
        # Set tender_reference from folder name if provided
        if result and tender_ref:
            result.tender_info.tender_reference = tender_ref
        
        return result
    
    def _extract_metadata(self, text: Optional[str], images: Optional[List[Image.Image]], 
                         doc_type: str) -> Optional[ExtractionOutput]:
        """Extract tender metadata and lots."""
        prompt = self._create_metadata_prompt(doc_type)
        
        # Try with fallback
        result = self._try_with_fallback(
            self._process_with_model,
            text, images, prompt, ExtractionOutput
        )
        
        if result and result.tender_info:
            # Post-process lot references
            if result.lots:
                for lot in result.lots:
                    clean_num = lot.lot_number.lower().replace("lot", "").strip()
                    lot.lot_reference = f"{result.tender_info.tender_reference}_{clean_num}"
        
        return result
    
    def _extract_products(self, text: Optional[str], images: Optional[List[Image.Image]], 
                         doc_type: str) -> Optional[ExtractionOutput]:
        """Extract product items from BDP."""
        prompt = self._create_products_prompt(doc_type)
        
        # Try with fallback
        result = self._try_with_fallback(
            self._process_with_model,
            text, images, prompt, ProductList
        )
        
        if result and hasattr(result, '​products'):
            # Wrap in ExtractionOutput
            return ExtractionOutput(
                tender_info=TenderMetadata(),
                lots=[],
                products=result.products
            )
        
        return ExtractionOutput(tender_info=TenderMetadata(), lots=[], products=[])
    
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
        Process document with specified model (with retries).
        
        Args:
            text: Extracted text (if available)
            images: List of images (if document was image-based)
            prompt: Extraction prompt
            output_class: Pydantic class for output parsing
            model_id: Model identifier
            
        Returns:
            Parsed output instance
        """
        # Build messages
        messages = []
        
        if images:
            # Multimodal: send images
            logger.info(f"Processing {len(images)} images with {model_id}")
            messages = self._build_multimodal_messages(prompt, images)
        else:
            # Text-based: send extracted text
            logger.info(f"Processing text ({len(text)} chars) with {model_id}")
            messages = self._build_text_messages(prompt, text)
        
        # Call OpenRouter API
        response = self.client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=4000,
            temperature=0.0
        )
        
        content = response.choices[0].message.content
        
        # Parse output
        return self._parse_output(content, output_class)
    
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
    
    def _build_multimodal_messages(self, prompt: str, images: List[Image.Image]) -> List[Dict]:
        """Build messages for multimodal input."""
        # Limit images to avoid token limits
        max_images = min(len(images), 20)  # Process max 20 pages at a time
        
        content_parts = [{"type": "text", "text": prompt}]
        
        for idx, image in enumerate(images[:max_images], 1):
            image_base64 = self._image_to_base64(image)
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })
        
        return [
            {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
            {"role": "user", "content": content_parts}
        ]
    
    def _build_text_messages(self, prompt: str, text: str) -> List[Dict]:
        """Build messages for text-based input."""
        # Limit text to avoid token overflow
        max_chars = 100000  # ~25K tokens
        text_truncated = text[:max_chars]
        
        full_prompt = f"{prompt}\\n\\nDocument Text:\\n{text_truncated}"
        
        return [
            {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
            {"role": "user", "content": full_prompt}
        ]
    
    def _parse_output(self, content: str, output_class):
        """Parse LLM output to Pydantic model."""
        try:
            # Try direct JSON parsing
            # Remove markdown code blocks if present
            clean_content = content.replace("```json", "").replace("```", "").strip()
            
            # Extract JSON from content
            start_idx = clean_content.find("{")
            end_idx = clean_content.rfind("}")
            
            if start_idx != -1 and end_idx != -1:
                json_str = clean_content[start_idx:end_idx+1]
                data = json.loads(json_str)
                
                # Parse with Pydantic
                return output_class(**data)
            else:
                logger.error("No JSON found in response")
                return None
                
        except Exception as e:
            logger.error(f"Error parsing output: {e}")
            logger.debug(f"Content: {content[:500]}")
            return None
    
    def _create_metadata_prompt(self, doc_type: str) -> str:
        """Create prompt for metadata extraction."""
        return f"""Analyze the tender document images/text and extract structured metadata.

Document Type: {doc_type}

LANGUAGE PRIORITY:
1. **Prefer FRENCH**: Always extract values in French if available in the document.
2. **Arabic Fallback**: Only use Arabic if NO French text exists for that specific field.
3. **ARABIC TEXT handling**: If you must extract Arabic, ensure it is written in the correct logical order (Right-to-Left safe). Do NOT output disjointed or reversed characters.


Extract the following information:

1. **Tender Info**:
   - tender_reference: Format as XX_YYYY_ACRONYM_ORGANIZATION (e.g., "01_2026_DAMPS_MDT_DELM_DIRAPPMEDPROSAN")
   - buyer: Full organization name - MANDATORY (e.g., "Ministère des Habous et des Affaires Islamiques")
   - location: Execution location - City/Region/Province (e.g., "Provinces d'Al Haouz et de Marrakech")
   - global_budget: Total estimated budget (look in CPS or RC documents)
   - nbre_lots: Total number of lots (if mentioned)
   - passation_mode: Mode of procurement (e.g., "Appel d'offres ouvert au rabais ou majoration")
   - type: Type/domain of tender (e.g., "REHABILITATION DES LIEUX D'EXERCICE DE CULTE MUSULMAN")
   - agrements: List of required certifications (D-codes like ["D1", "D2", "D13"])

2. **Lots** (if multiple lots exist):
   - lot_number: Use "0" for single/no lot, otherwise "1", "2", etc.
   - lot_reference: Combine tender_ref + lot_number (e.g., "MOD-HABOUS-2025-210_unique")
   - title: Full description of the lot (can be multi-line)
   - budget_lot: Estimated budget for this specific lot

CRITICAL RULES:
- DO NOT include: deadline, publication_date, buyer_initials, buyer_address, buyer_phone, buyer_email, buyer_contact, status
- For single/no lot tenders: nbre_lots: 0, lot_number: "0", lot_reference: "{{tender_ref}}_0"
- tender_reference MUST follow format: XX_YYYY_ACRONYM_ORGANIZATION
- buyer field is MANDATORY
- agrements should be empty list [] if none found

Return ONLY valid JSON matching this exact structure:
{{
  "tender_info": {{
    "tender_reference": "01_2026_EXAMPLE_ORGANIZATION",
    "location": "City/Province",
    "global_budget": 1000000.0,
    "nbre_lots": 0,
    "buyer": "Organization Name",
    "passation_mode": "Appel d'offres ouvert",
    "type": "Project Type",
    "agrements": []
  }},
  "lots": [
    {{"lot_number": "0", "lot_reference": "REF_0", "title": "Description", "budget_lot": 500000.0}}
  ],
  "products": []
}}

Return ONLY JSON, no explanations. If a field is not found, use null (except agrements which should be []).
"""

    
    def _create_products_prompt(self, doc_type: str) -> str:
        """Create prompt for product extraction."""
        return f"""Analyze the tender document (Bordereau des Prix / BDP) and extract all product line items.

Document Type: {doc_type}

For each row in the price table, extract:
- designation (product/service description)
- unit (measurement unit: m2, kg, u, etc.)
- quantity (required quantity)
- estimated_price (unit price if available)
- lot_number (which lot this belongs to)

Return ONLY valid JSON in this structure:
{{
  "products": [
    {{
      "designation": "...",
      "unit": "...",
      "quantity": 100.0,
      "estimated_price": 50.0,
      "lot_number": "1"
    }},
    ...
  ]
}}

CRITICAL RULES:
- Create ONE JSON object per table row
- Do NOT calculate or estimate any values
- If a value is missing, use null
- Ignore headers, subtotals, and summary rows
- Return ONLY JSON, no explanations
"""
