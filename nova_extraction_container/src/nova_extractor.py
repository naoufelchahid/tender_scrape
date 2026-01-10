"""
Nova Lite Multimodal Extractor using Groq API with LangChain.
Provides structured data extraction from tender documents with fallback chain.
"""
import json
import base64
from io import BytesIO
from typing import List, Dict, Any, Optional, Union
from PIL import Image
from langchain_groq import ChatGroq
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from logger import logger, log_model_fallback
from src.models import ExtractionOutput, TenderMetadata, LotMetadata, ProductItem, ProductList
from src.document_processor import DocumentProcessor


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
        
        # Initialize LangChain Groq clients for each model
        self.llm_clients = {}
        for model in self.models:
            self.llm_clients[model] = ChatGroq(
                api_key=Config.GROQ_API_KEY,
                model_name=model,
                temperature=0.0
            )
        
        self.document_processor = DocumentProcessor()
        
        logger.info(f"Nova Extractor initialized with Groq fallback chain: {' → '.join(self.models)}")
    
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
            # Post-process lots
            if result.lots:
                # Ghost Lot 0 filtering: If we have real lots (lots with number != "0"), remove any lot "0"
                real_lots = [l for l in result.lots if l.lot_number and l.lot_number != "0"]
                if real_lots and len(result.lots) > len(real_lots):
                    logger.info(f"Removing ghost 'Lot 0' because {len(real_lots)} real lots were found.")
                    result.lots = real_lots
                
                # Update references
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
        
        # Validation and Filtering
        if result and hasattr(result, 'products'):
            valid_products = []
            if result.products:
                for p in result.products:
                    # Filter: Name "Unknown" AND Quantity 0
                    is_unknown = p.designation and "unknown" in p.designation.lower()
                    is_zero_qty = p.quantity is None or p.quantity == 0
                    
                    if is_unknown and is_zero_qty:
                        continue
                    valid_products.append(p)
            
            # Fallback: If no products found, create one generic product
            if not valid_products:
                logger.warning("No valid products found after filtering. Creating default product.")
                default_prod = ProductItem(
                    designation=f"Prestation pour appel d'offres",
                    unit="Forfait",
                    quantity=1.0,
                    lot_number="0"
                )
                valid_products.append(default_prod)
            
            return ExtractionOutput(
                tender_info=TenderMetadata(),
                lots=[],
                products=valid_products
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
        # Get the LLM client for this model
        llm = self.llm_clients[model_id]
        
        # Create JSON output parser
        parser = JsonOutputParser(pydantic_object=output_class)
        
        if images:
            # Multimodal: send images
            logger.info(f"Processing {len(images)} images with {model_id}")
            content = self._build_multimodal_content(prompt, images)
            
            # Build messages directly (avoid ChatPromptTemplate to prevent variable parsing)
            messages = [
                {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
                {"role": "user", "content": content}
            ]
            
        else:
            # Text-based: send extracted text
            logger.info(f"Processing text ({len(text)} chars) with {model_id}")
            
            # Limit text to avoid token overflow
            max_chars = 100000  # ~25K tokens
            text_truncated = text[:max_chars]
            
            full_prompt = f"{prompt}\n\nDocument Text:\n{text_truncated}"
            
            # Build messages directly
            messages = [
                {"role": "system", "content": "You are an expert in Moroccan tender document analysis. Extract structured data accurately."},
                {"role": "user", "content": full_prompt}
            ]
        
        # Call LLM directly and parse output
        response = llm.invoke(messages)
        
        # Parse the response content to dict
        parsed_dict = parser.parse(response.content)
        
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
   - 
   - buyer: Full organization name - MANDATORY (e.g., "Ministère des Habous et des Affaires Islamiques")
   - location: Execution location - City/Region/Province (e.g., "Provinces d'Al Haouz et de Marrakech")
   - global_budget: Total estimated budget (look in CPS or RC documents)
   - nbre_lots: Total number of lots (if mentioned)
   - passation_mode: Mode of procurement (e.g., "Appel d'offres ouvert au rabais ou majoration")
   - type: Type/domain of tender (e.g., "REHABILITATION DES LIEUX D'EXERCICE DE CULTE MUSULMAN")
   - agrements: List of required certifications (D-codes like ["D1", "D2", "D13"])

2. **Lots** (if multiple lots exist):
   - lot_number: Use "0" for single/no lot, otherwise "1", "2", etc.
   - lot_reference: Combine {{tender_ref}} + lot_number (e.g., "MOD-HABOUS-2025-210_unique")
   - title: Full description of the lot (can be multi-line)
   - budget_lot: Estimated budget for this specific lot

CRITICAL RULES:
- **LANGUAGE**: Write ALL text values in FRENCH. Use Arabic only if the document is 100% Arabic.
- DO NOT include: deadline, publication_date, buyer_initials, buyer_address, buyer_phone, buyer_email, buyer_contact, status
- **LOTS**: If you find specific lots (Lot 1, Lot 2...), DO NOT create a "Lot 0". "Lot 0" is ONLY for tenders with NO distinct lots.
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
- **LANGUAGE**: Write ALL text values in FRENCH. Use Arabic only if the document is 100% Arabic.
- **DESIGNATION**: Extract the FULL, EXACT text of the description. Do NOT summarize. Copy the whole paragraph if necessary.
- **TABLE ROW**: Create ONE JSON object per meaningful table row.
- **MANDATORY**: You MUST extract at least one product. If the document is a list of prices, extract them.
- If a value is missing, use null.
- Ignore headers, subtotals, and summary rows.
- **Lot 0**: If the item belongs to the main tender (single lot), use lot_number="0".
- Return ONLY JSON, no explanations
"""
