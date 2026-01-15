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
        Extract tender metadata using LLM from avis and cps chunks.
        
        Extraction mapping:
        - deadline: from avis + cps
        - publication_date: from avis
        - location: from cps
        - global_budget: from avis + cps
        - nbre_lots: from cps
        - buyer: from cps
        - buyer_address: from cps
        - buyer_phone: from cps
        - buyer_email: from cps
        - buyer_contact: from cps
        - passation_mode: from cps
        - type: from cps
        - agrements: from lots (will be set later)
        """
        # Concatenate relevant chunks
        avis_content = self._concatenate_chunks(chunks_by_type.get("avis", []))
        cps_content = self._concatenate_chunks(chunks_by_type.get("specification", []))
        admin_content = self._concatenate_chunks(chunks_by_type.get("administrative", []))
        
        # Build context for LLM
        context = f"""=== AVIS (Tender Notice) ===
{avis_content[:5000] if avis_content else 'No avis content available'}

=== CPS (Technical Specifications) ===
{cps_content[:10000] if cps_content else 'No CPS content available'}

=== ADMINISTRATIVE ===
{admin_content[:5000] if admin_content else 'No administrative content available'}
"""
        
        prompt = f"""Extract tender metadata from the following tender documents.

{context}

Extract the following fields in JSON format:
- deadline: Submission deadline (ISO datetime format, e.g. "2026-02-15T15:00:00")
- publication_date: Publication date (ISO datetime format)
- location: Execution location/city
- global_budget: Total estimated budget (number only, no currency)
- nbre_lots: Number of lots (integer)
- buyer: Full name of the buyer organization
- buyer_address: Buyer's address
- buyer_phone: Buyer's phone number
- buyer_email: Buyer's email
- buyer_contact: Contact person name
- passation_mode: Mode of procurement (e.g., "Appel d'offres ouvert")
- type: Type/domain of tender

Return ONLY valid JSON with these fields. Use null for missing values.
"""
        
        try:
            response = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True
            )
            
            # Parse JSON response
            extracted = json.loads(response)
            
            # Build TenderMetadata
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
                "agrements": []  # Will be populated from lots
            }
            
            return TenderMetadata(**tender_data)
            
        except Exception as e:
            logger.error(f"LLM tender info extraction failed: {e}", exc_info=True)
            # Return minimal tender info
            return TenderMetadata(
                tender_reference=tender_ref,
                buyer="Unknown Buyer",
                agrements=[]
            )
    
    def _extract_lots_llm(self, chunks_by_type: Dict[str, List[Dict]], tender_ref: str) -> List[LotMetadata]:
        """
        Extract lots from CPS chunks using LLM.
        
        Only extract REAL lots mentioned in CPS, avoid creating duplicate "Lot 0" or inconsistent lots.
        """
        # Get CPS content
        cps_chunks = chunks_by_type.get("specification", [])
        cps_content = self._concatenate_chunks(cps_chunks)
        
        if not cps_content:
            # No CPS content, return single default lot
            return [LotMetadata(
                lot_number="0",
                lot_reference=f"{tender_ref}_0",
                title="Lot unique",
                budget_lot=None
            )]
        
        prompt = f"""Analyze the CPS (Cahier des Prescriptions Spéciales) below and extract ALL lots mentioned.

{cps_content[:15000]}

CRITICAL RULES:
1. If the tender mentions specific lots (Lot 1, Lot 2, Lot 3, etc.), extract each one
2. If NO specific lots are mentioned (tender is single-lot), return ONLY ONE lot with lot_number="0"
3. DO NOT create both "Lot 0" AND numbered lots - it's either single-lot (0) or multi-lot (1, 2, 3...)
4. Extract: lot_number (just the number as string), title (full description), budget_lot (if mentioned)

Return JSON array of lots:
[
  {{"lot_number": "1", "title": "...", "budget_lot": 500000}},
  {{"lot_number": "2", "title": "...", "budget_lot": null}}
]

If single-lot:
[{{"lot_number": "0", "title": "Lot unique", "budget_lot": null}}]
"""
        
        try:
            response = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True
            )
            
            lots_data = json.loads(response)
            
            # Handle potential wrapped response {"lots": [...]}
            if isinstance(lots_data, dict):
                lots_data = lots_data.get("lots", [])
            
            # Ensure it's a list
            if not isinstance(lots_data, list):
                logger.warning(f"LLM returned non-list for lots: {type(lots_data)}")
                lots_data = []

            # Build LotMetadata objects
            lots = []
            for lot in lots_data:
                # robust handling if lot is not dict
                if not isinstance(lot, dict):
                    logger.warning(f"Skipping invalid lot data: {lot}")
                    continue
                    
                lots.append(LotMetadata(
                    lot_number=str(lot.get("lot_number", "0")),
                    lot_reference=f"{tender_ref}_{lot.get('lot_number', '0')}",
                    title=lot.get("title", "Lot unique"),
                    budget_lot=self._parse_float(lot.get("budget_lot"))
                ))
            
            # Ensure at least one lot
            if not lots:
                lots.append(LotMetadata(
                    lot_number="0",
                    lot_reference=f"{tender_ref}_0",
                    title="Lot unique",
                    budget_lot=None
                ))
            
            logger.info(f"Extracted {len(lots)} lots: {[l.lot_number for l in lots]}")
            return lots
            
        except Exception as e:
            logger.error(f"LLM lot extraction failed: {e}", exc_info=True)
            # Fallback to single lot
            return [LotMetadata(
                lot_number="0",
                lot_reference=f"{tender_ref}_0",
                title="Lot unique",
                budget_lot=None
            )]
    
    def _extract_products_llm(self, chunks_by_type: Dict[str, List[Dict]]) -> List[ProductItem]:
        """
        Extract products from product chunks using LLM.
        """
        products_chunks = chunks_by_type.get("products", [])
        
        if not products_chunks:
            logger.info("No product chunks found")
            return []
        
        # Concatenate product content
        products_content = self._concatenate_chunks(products_chunks[:50])  # Limit to first 50 chunks
        
        prompt = f"""Extract ALL products from the following Bordereau des Prix (Bill of Quantities).

{products_content[:20000]}

For each product row, extract:
- designation: Full product description
- unit: Unit of measurement (m2, kg, U, Ens, etc.)
- quantity: Required quantity (number)
- estimated_price: Unit price (number, null if not available)
- lot_number: Lot this product belongs to (extract from context, "0" if not specified)

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
            
            # Build ProductItem objects
            products = []
            for p in products_data:
                products.append(ProductItem(
                    designation=p.get("designation", ""),
                    unit=p.get("unit", "U"),
                    quantity=float(p.get("quantity", 0)),
                    estimated_price=self._parse_float(p.get("estimated_price")),
                    lot_number=p.get("lot_number", "0")
                ))
            
            logger.info(f"Extracted {len(products)} products")
            return products
            
        except Exception as e:
            logger.error(f"LLM product extraction failed: {e}", exc_info=True)
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
