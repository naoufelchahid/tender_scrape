"""
Metadata Aggregator Service - Extracts metadata using LLM inference from chunks.

This service uses LLM to extract structured tender metadata by analyzing
chunk content grouped by type (avis,cps, products).

Stage: Extraction Container (Chunk-First Architecture)
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.models import ExtractionOutput, TenderMetadata, LotMetadata, ProductItem, ProductList
from src.openrouter_wrapper import OpenRouterClientWrapper

logger = logging.getLogger(__name__)


class MetadataAggregator:
    """Aggregates metadata using LLM inference on chunk content."""
    
    def __init__(self, region_name: str, model_id: str, openrouter_api_key: Optional[str] = None):
        """
        Initialize the metadata aggregator.
        
        Args:
            region_name: AWS region (for compatibility)
            model_id: Model ID for LLM
            openrouter_api_key: API key for OpenRouter
        """
        self.region_name = region_name
        self.model_id = model_id
        self.openrouter_api_key = openrouter_api_key
        
        # Initialize OpenRouter wrapper for LLM inference
        if openrouter_api_key:
            self.llm = OpenRouterClientWrapper(api_key=openrouter_api_key)
        else:
            self.llm = None
            logger.warning("No OpenRouter API key provided. Aggregation will fail.")
    
    def aggregate_metadata(self, chunks: List[Dict[str, Any]], tender_ref: str, tender_id: int = 0) -> ExtractionOutput:
        """
        Aggregate metadata from chunks using LLM inference.
        
        Args:
            chunks: List of chunk dictionaries with content and metadata
            tender_ref: Tender reference string
            tender_id: Tender database ID (optional)
            
        Returns:
            ExtractionOutput with extracted metadata
        """
        logger.info(f"Aggregating metadata from {len(chunks)} chunks using LLM inference...")
        
        # Group chunks by type
        chunks_by_type = self._group_chunks_by_type(chunks)
        logger.info(f"Grouped chunks: {[(k, len(v)) for k, v in chunks_by_type.items()]}")
        
        # Extract tender info from avis + cps chunks
        tender_info = self._extract_tender_info_llm(chunks_by_type, tender_ref)
        
        # Extract lots from cps chunks
        lots = self._extract_lots_llm(chunks_by_type, tender_ref)
        
        # Extract products from product chunks
        products = self._extract_products_llm(chunks_by_type)
        
        logger.info(f"Extracted: {len(lots)} lots, {len(products)} products")
        
        return ExtractionOutput(
            tender_info=tender_info,
            lots=lots,
            products=products
        )
    
    def _group_chunks_by_type(self, chunks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group chunks by their type."""
        grouped = {}
        for chunk in chunks:
            chunk_type = chunk.get("metadata", {}).get("type", "unknown")
            if chunk_type not in grouped:
                grouped[chunk_type] = []
            grouped[chunk_type].append(chunk)
        return grouped
    
    def _extract_tender_info_llm(self, chunks_by_type: Dict[str, List[Dict]], tender_ref: str) -> TenderMetadata:
        """
        Extract tender metadata using LLM with NOVA-inspired logic.
        """
        # Concatenate relevant chunks
        avis_content = self._concatenate_chunks(chunks_by_type.get("avis", []))
        cps_content = self._concatenate_chunks(chunks_by_type.get("specification", []))
        admin_content = self._concatenate_chunks(chunks_by_type.get("administrative", []))
        
        # Build context
        context = f"""=== AVIS (Tender Notice) ===
{avis_content[:5000]}

=== CPS (Technical Specifications) ===
{cps_content[:10000]}

=== ADMINISTRATIVE ===
{admin_content[:5000]}
"""
        
        prompt = f"""You are an expert analyst specializing in Moroccan public tender documents.

Your task is to analyze the provided tender context and extract ALL relevant structured data.

CONTEXT:
{context}

---

## EXTRACTION RULES

### LANGUAGE PRIORITY
1. **PREFER FRENCH**: Always extract values in French if available.
2. **Arabic Fallback**: Only use Arabic if NO French text exists.

### REQUIRED FIELDS MATCHING NOVA LOGIC
Extract the following JSON fields:
- **buyer**: Full organization name (MANDATORY). e.g., "Ministère des Habous..."
- **deadline**: Submission deadline (ISO format).
- **publication_date**: Publication date (ISO format).
- **location**: Execution location (City/Province).
- **global_budget**: Total estimated budget (number).
- **budget**: Estimated budget for the whole tender (sometimes explicitly stated as 'budget').
- **caution**: Caution provisoire amount (number).
- **nbre_lots**: Total number of lots.
- **passation_mode**: Mode of procurement (e.g., "Appel d'offres ouvert").
- **type**: Type/domain of tender.
- **buyer_address**: Address.
- **buyer_phone**: Phone.
- **buyer_email**: Email.
- **buyer_contact**: Contact person.

**CRITICAL**:
- If `buyer` is not found, try to infer from the context but do not leave empty if possible.
- Return `null` for missing fields.

Output JSON only.
"""
        
        try:
            response = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True
            )
            
            extracted = json.loads(response)
            
            # Map to TenderMetadata
            tender_data = {
                "tender_reference": tender_ref,
                "deadline": self._parse_datetime(extracted.get("deadline")),
                "publication_date": self._parse_datetime(extracted.get("publication_date")),
                "location": extracted.get("location"),
                "global_budget": self._parse_float(extracted.get("global_budget")),
                "nbre_lots": extracted.get("nbre_lots"),
                "buyer": extracted.get("buyer", "Unknown Buyer"),
                "buyer_address": extracted.get("buyer_address"),
                "buyer_phone": extracted.get("buyer_phone"),
                "buyer_email": extracted.get("buyer_email"),
                "buyer_contact": extracted.get("buyer_contact"),
                "passation_mode": extracted.get("passation_mode"),
                "type": extracted.get("type"),
                "agrements": [] 
            }
            
            return TenderMetadata(**tender_data)
            
        except Exception as e:
            logger.error(f"LLM tender info extraction failed: {e}", exc_info=True)
            return TenderMetadata(
                tender_reference=tender_ref,
                buyer="Unknown Buyer",
                agrements=[]
            )
    
    def _extract_lots_llm(self, chunks_by_type: Dict[str, List[Dict]], tender_ref: str) -> List[LotMetadata]:
        """
        Extract lots using NOVA-inspired logic.
        """
        # Check both specs and products for lot clues
        cps_chunks = chunks_by_type.get("specification", [])
        product_chunks = chunks_by_type.get("products", [])
        
        # We need content that mentions lots.
        context = self._concatenate_chunks(cps_chunks[:20]) # First 20 spec chunks usually have lot info
        
        # If products exist, they might have lot headers too
        if product_chunks:
            context += "\n\n=== PRODUCT HEADERS ===\n" + self._concatenate_chunks(product_chunks[:10])
            
        if not context:
             return [LotMetadata(
                lot_number="0",
                lot_reference=f"{tender_ref}_0",
                title="Lot unique",
                budget_lot=None
            )]
        
        prompt = f"""Analyze the tender documents below and extract ALL lots mentioned.

{context[:20000]}

## CRITICAL LOT EXTRACTION RULES (NOVA LOGIC)
1. **Ghost Lot 0**: If you find SPECIFIC lots (Lot 1, Lot 2...), DO NOT create a "Lot 0".
2. **Lot 0** is ONLY for tenders with NO distinct lots (single-lot or undivided).
3. **Extraction**:
   - `lot_number`: Just the number "1", "2" (or "0" if single).
   - `title`: Full lot description.
   - `budget_lot`: Estimated budget for this lot (number).

Return JSON array of lots:
[
  {{"lot_number": "1", "title": "...", "budget_lot": 500000}},
  ...
]
"""
        
        try:
            response = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True
            )
            
            lots_data = json.loads(response)
            if isinstance(lots_data, dict): lots_data = lots_data.get("lots", [])
            
            lots = []
            for lot in lots_data:
                lot_num = str(lot.get("lot_number", "0"))
                # Clean lot number
                clean_num = lot_num.lower().replace("lot", "").strip()
                if not clean_num: clean_num = "0"
                
                lots.append(LotMetadata(
                    lot_number=clean_num,
                    lot_reference=f"{tender_ref}_{clean_num}",
                    title=lot.get("title", "Lot unique"),
                    budget_lot=self._parse_float(lot.get("budget_lot"))
                ))
            
            if not lots:
                lots.append(LotMetadata(lot_number="0", lot_reference=f"{tender_ref}_0", title="Lot unique", budget_lot=None))
                
            return lots
            
        except Exception as e:
            logger.error(f"LLM lot extraction failed: {e}")
            return [LotMetadata(lot_number="0", lot_reference=f"{tender_ref}_0", title="Lot unique", budget_lot=None)]

    def _extract_products_llm(self, chunks_by_type: Dict[str, List[Dict]]) -> List[ProductItem]:
        """
        Extract products using NOVA-inspired logic.
        """
        products_chunks = chunks_by_type.get("products", [])
        if not products_chunks:
            return []
        
        products_content = self._concatenate_chunks(products_chunks[:50])
        
        prompt = f"""Extract ALL products from the following Bordereau des Prix (Bill of Quantities).

{products_content[:25000]}

## CRITICAL PRODUCT RULES (NOVA LOGIC)
1. **ONE ROW = ONE PRODUCT**: Create a separate product object for EVERY meaningful table row.
2. **DO NOT MERGE** distinct items.
3. **PRESERVE EXACT TEXT**: Keep technical specs, dimensions, references.
4. **Lot Attribution**: Assign each product to its lot number (use "0" if single lot).

Return JSON array:
{{
  "products": [
    {{"designation": "...", "unit": "m2", "quantity": 100.0, "estimated_price": 50.0, "lot_number": "1"}},
    ...
  ]
}}
"""
        
        try:
            response = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True
            )
            
            result = json.loads(response)
            products_data = result.get("products", [])
            
            products = []
            for p in products_data:
                products.append(ProductItem(
                    designation=p.get("designation", ""),
                    unit=p.get("unit", "U"),
                    quantity=self._parse_float(p.get("quantity")) or 0.0,
                    estimated_price=self._parse_float(p.get("estimated_price")),
                    lot_number=str(p.get("lot_number", "0"))
                ))
            
            return products
            
        except Exception as e:
            logger.error(f"LLM product extraction failed: {e}")
            return []
    
    def _concatenate_chunks(self, chunks: List[Dict[str, Any]], max_chars: int = 50000) -> str:
        """Concatenate chunk content with separator."""
        content_parts = []
        total_chars = 0
        
        for chunk in chunks:
            content = chunk.get("content", "")
            if total_chars + len(content) > max_chars:
                break
            content_parts.append(content)
            total_chars += len(content)
        
        return "\n\n---\n\n".join(content_parts)
    
    def _parse_float(self, value: Any) -> Optional[float]:
        """Parse float value safely."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime value safely."""
        if value is None or value == "null":
            return None
        
        if isinstance(value, datetime):
            return value
        
        try:
            # Try ISO format first
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            # Try common French date formats
            for fmt in ["%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(str(value), fmt)
                except ValueError:
                    continue
            
            logger.warning(f"Could not parse datetime: {value}")
            return None
