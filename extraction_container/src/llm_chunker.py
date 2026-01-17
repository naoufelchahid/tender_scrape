"""
LLM-Assisted Intelligent Document Chunking Service.

Uses OpenRouter API via OpenRouterClientWrapper to analyze documents and create
semantically meaningful chunks with proper metadata.
"""

import re
import json
import logging
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

from src.cleaning import DocumentCleaners, LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.models import ChunkingOutput, ChunkItem

logger = logging.getLogger(__name__)


# Document types that use LLM-assisted chunking
LLM_CHUNK_TYPES = {'product', 'specification', 'administrative', 'avis'}

# Document types to skip entirely (no chunking)
SKIP_TYPES = {'engagement', 'declaration'}

# Standard chunking settings for 'other' documents
STANDARD_CHUNK_SIZE = 500  # tokens (approx chars/4)
STANDARD_CHUNK_OVERLAP = 100


@dataclass
class Chunk:
    """Represents a document chunk with metadata."""
    id: str
    content: str
    metadata: Dict[str, Any]


class LLMChunker:
    """LLM-assisted intelligent document chunking using OpenRouterClientWrapper."""
    
    def __init__(self, region_name: str, model_id: str, openrouter_api_key: Optional[str] = None):
        """Initialize the LLM chunker.
        
        Args:
            region_name: AWS region (maintained for compatibility)
            model_id: Model ID (OpenRouter)
            openrouter_api_key: API Key for OpenRouter
        """
        self.region_name = region_name
        self.model_id = model_id
        
        # Initialize centralized OpenRouter Wrapper
        self.llm = OpenRouterClientWrapper(api_key=openrouter_api_key)
        
        # Standard text splitter for fallback/other documents
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE * 4,  # chars approx
            chunk_overlap=STANDARD_CHUNK_OVERLAP * 4,
            separators=["\n\n", "\n", ". ", " "]
        )
    
    def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int, tender_ref: str, lots: List[Any]) -> List[Dict[str, Any]]:
        """Process all documents and generate chunks.
        
        Args:
            docs: List of LogicalDocument objects
            tender_id: Database ID of the tender
            tender_ref: Tender Reference string
            lots: List of LotMetadata objects
            
        Returns:
            List of chunk dictionaries with id, content, metadata
        """
        all_chunks = []
        
        # Create a mapping of lot_number -> lot_reference
        # If no lots, we use "0" -> "{tender_ref}_0"
        lot_map = {}
        if lots:
            for lot in lots:
                # normalize lot number to string "1", "2"
                num = lot.lot_number.lower().replace("lot", "").strip()
                lot_map[num] = lot.lot_reference
        
        # Fallback default
        default_lot_ref = f"{tender_ref}_0"
        
        # Filter out excluded documents
        valid_docs = []
        for doc in docs:
            if self._should_skip_document(doc):
                logger.info(f"Skipping excluded document: {doc.original_filename} (Type: {doc.doc_type})")
                continue
            valid_docs.append(doc)
        
        if not valid_docs:
            logger.warning("No valid documents to chunk")
            return []
        
        logger.info(f"Processing {len(valid_docs)} documents individually")
        
        for i, doc in enumerate(valid_docs):
            logger.info(f"[{i+1}/{len(valid_docs)}] Processing doc: {doc.original_filename} (Type: {doc.doc_type})")
            
            # Logic: We send almost all reasonable documents to LLM for smarter extraction
            # unless we specifically want to save cost on 'other' or very small files.
            # But the requirement is to fix "incomplete extraction", so we maximize LLM usage.
            
            try:
                # Basic size check or type check could go here if needed
                if len(doc.content.strip()) < 50:
                    continue

                doc_chunks = self._chunk_single_document(doc, tender_id, tender_ref, lot_map, default_lot_ref)
                all_chunks.extend(doc_chunks)
            except Exception as e:
                logger.error(f"Failed to chunk document {doc.original_filename}: {e}", exc_info=True)
                # Fallback to standard chunking for this doc
                fallback_chunks = self._standard_chunk_document(doc, tender_id, default_lot_ref)
                all_chunks.extend(fallback_chunks)
        
        logger.info(f"Total chunks generated from all documents: {len(all_chunks)}")
        return all_chunks

    def _chunk_single_document(
        self, 
        doc: LogicalDocument, 
        tender_id: int, 
        tender_ref: str, 
        lot_map: Dict[str, str], 
        default_lot_ref: str
    ) -> List[Dict[str, Any]]:
        """Process a single document with LLM."""
        
        # Quick size check: if document is huge (> 300k chars), 
        # we warn. Llama-4 supports 128k context (~500k chars), so we are safe-ish.
        if len(doc.content) > 400000:
             logger.warning(f"Document {doc.original_filename} is very large ({len(doc.content)} chars). LLM might struggle.")

        prompt = self._get_single_doc_prompt(doc, tender_ref)
        
        # Execute LLM call
        response = self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True
        )
        
        if not response or len(response) < 10:
            logger.warning(f"Empty/Tiny LLM response for {doc.original_filename}, falling back")
            return self._standard_chunk_document(doc, tender_id, default_lot_ref)
            
        # Parse JSON
        try:
            response_data = json.loads(response)
            parsed_output = ChunkingOutput(**response_data)
            logger.info(f"  -> Parsed {len(parsed_output.chunks)} chunks")
        except Exception as parse_err:
            logger.error(f"Parsing failed for {doc.original_filename}: {parse_err}")
            # Try to recover partial json? For now, fallback.
            return self._standard_chunk_document(doc, tender_id, default_lot_ref)
        
        # Convert to Clean Chunks
        chunks = self._convert_to_chunk_dicts(
            parsed_output.chunks, 
            tender_id, 
            tender_ref, 
            lot_map, 
            default_lot_ref
        )
        
        return chunks
    
    def _convert_to_chunk_dicts(
        self, 
        chunk_items: List[ChunkItem],
        tender_id: int,
        tender_ref: str,
        lot_map: Dict[str, str],
        default_lot_ref: str
    ) -> List[Dict[str, Any]]:
        """Convert Pydantic ChunkItem objects to chunk dictionaries with proper IDs."""
        chunks = []
        type_counters: Dict[str, int] = {}
        
        for item in chunk_items:
            # Skip empty or trivial chunks
            if not item.content or len(item.content.strip()) < 10:
                continue
            
            # Resolve lot number (normalize to "1", "2", "0")
            raw_lot = str(item.metadata.lot) if item.metadata.lot else "0"
            clean_lot_num = raw_lot.lower().replace("lot", "").strip()
            
            # Ensure we have a valid lot number string (e.g. "1")
            # If empty or invalid, default to "0"
            if not clean_lot_num or clean_lot_num == "none":
                clean_lot_num = "0"

            # Determine lot_reference (used for grouping in aggregator)
            # logic: if map has it, use it. else construct {tender_ref}_{num}
            if clean_lot_num in lot_map:
                lot_ref = lot_map[clean_lot_num]
            else:
                lot_ref = f"{tender_ref}_{clean_lot_num}"

            # ------------------------------------------------------------------
            # ID GENERATION (User Requirement)
            # Structure: {tender_ref}_0(lot number)_type_1 increment
            # Example: TENDER1_01_specification_1
            # ------------------------------------------------------------------
            chunk_type = item.metadata.type
            
            # Format lot number with leading zero if needed (simple heuristic: 0 -> 00, 1 -> 01)
            # User example was "0 (lot number)". We will format as 2 digits if numeric.
            try:
                lot_int = int(clean_lot_num)
                formatted_lot = f"{lot_int:02d}" # 0 -> 00, 1 -> 01, 10 -> 10
            except ValueError:
                # If "all" or non-numeric, just use it safely
                formatted_lot = f"0{clean_lot_num}"
            
            # Increment counter
            # Key difference: we count based on Type + Lot to ensure uniqueness per content stream
            counter_key = f"{formatted_lot}_{chunk_type}"
            if counter_key not in type_counters:
                type_counters[counter_key] = 1
            idx = type_counters[counter_key]
            type_counters[counter_key] += 1
            
            # Final ID
            chunk_id = f"{tender_ref}_{formatted_lot}_{chunk_type}_{idx}"
            
            # Build metadata dictionary
            # "merge the two fild article_id and lot" -> The ID now carries this uniqueness.
            # We still keep key metadata for downstream aggregation.
            metadata = {
                "type": chunk_type,
                "lot_reference": lot_ref,
                "lot_number": clean_lot_num
            }
            
            # Add optional product-specific fields
            if item.metadata.designation:
                metadata["designation"] = item.metadata.designation
            if item.metadata.quantity is not None:
                metadata["quantity"] = item.metadata.quantity
            if item.metadata.unit:
                metadata["unit"] = item.metadata.unit
            
            # Add optional specification fields
            if item.metadata.article_id:
                metadata["article_id"] = item.metadata.article_id
            
            chunks.append({
                "id": chunk_id,
                "content": item.content.strip(),
                "metadata": metadata
            })
        
        return chunks
    
    def _should_skip_document(self, doc: LogicalDocument) -> bool:
        """
        Check if document should be excluded from processing.
        Excluded if:
        1. It's in SKIP_TYPES (engagement, declaration, etc)
        2. Filename contains exclusion patterns
        3. It's an Arabic Avis (Avis type + >40% Arabic content)
        """
        # 1. Check Type
        if doc.doc_type in SKIP_TYPES:
            return True
            
        # 2. Check Filename Patterns
        fname_lower = doc.original_filename.lower()
        exclude_patterns = [
            'acte', 'engagement', 'declaration', 'honneur',
            'attestation', 'caution', 'cautionnement'
        ]
        if any(pattern in fname_lower for pattern in exclude_patterns):
            return True
            
        # 3. Check for Arabic Avis
        # Logic: If type is 'avis' and content is predominantly Arabic -> Skip
        if doc.doc_type == 'avis':
            # Count arabic characters in first 1000 chars to be fast
            sample = doc.content[:1000]
            # Arabic unicode block: 0600-06FF
            arabic_chars = len(re.findall(r'[\u0600-\u06FF]', sample))
            total_chars = len(sample.strip())
            
            if total_chars > 0:
                ratio = arabic_chars / total_chars
                if ratio > 0.4: # If > 40% Arabic text
                    logger.info(f"Skipping Arabic Avis detected: {doc.original_filename} (Ratio: {ratio:.2f})")
                    return True
                    
        return False
    
    def _get_single_doc_prompt(self, doc: LogicalDocument, tender_ref: str) -> str:
        """Create a prompt for chunking a SINGLE document using NOVA-inspired logic."""
        return f"""You are an expert document analyst specializing in Moroccan public tender documents.

TENDER REFERENCE: {tender_ref}
DOCUMENT NAME: {doc.original_filename}
DOCUMENT TYPE: {doc.doc_type.upper()}

Your task is to properly segment this document into semantic chunks using the rules below.

---

## DOCUMENT CONTENT

{doc.content}

---

## SEGMENTATION STRATEGIES BY CONTENT TYPE

### STRATEGY 1: PRICING TABLES (BDP, Décompte, Bordereau)
**DETECTION**: Tables with Designation, Quantity, Unit, Price.
**RULES**:
1. **ONE ITEM = ONE CHUNK**: Create a separate chunk for EVERY atomic product/service row.
2. **DO NOT MERGE** multiple distinct items into one chunk.
3. **DO NOT SPLIT** a single item's multi-line description.
4. **PRESERVE EXACT TEXT**: Keep technical specs, dimensions, norms.
5. **METADATA**:
   - `type`: "products"
   - `designation`: The full product description.
   - `quantity`: Number (e.g. 100).
   - `unit`: Unit (e.g. m2, U).
   - `lot`: The lot number this product belongs to (look for section headers like "LOT 1"). Use "0" if single-lot.
6. ** DO NOT DUPLICATE PRODUCTS .
### STRATEGY 2: TECHNICAL SPECIFICATIONS (CPS, CCTP, Technical Specs)
**DETECTION**: Articles describing technical requirements, methodology, or specific materials.
**RULES**:
1. **Article-Level Chunking**: Each "ARTICLE" is ONE chunk.
2. **NEVER MERGE** distinct articles (e.g. Art. 1 and Art. 2 must be separate).
3. **METADATA**:
   - `type`: "specification" (or "products_specs" if describing specific equipment specs)
   - `article_id`: The article number/title (e.g. "Article 5").
   - `lot`: "0" usually, unless specifications are specific to a "Lot 1" section.

### STRATEGY 3: ADMINISTRATIVE DOCUMENTS (RC, CCAP, Regulations)
**DETECTION**: Clauses about guarantees, eligibility, judgment criteria.
**RULES**:
1. One Article/Clause = One Chunk.
2. **METADATA**:
   - `type`: "administrative"
   - `article_id`: Article title.

### STRATEGY 4: TENDER NOTICES (Avis)
**RULES**:
1. Keep the entire notice as ONE comprehensive chunk.
2. `type`: "avis"

### GENERAL RULES
- **Language**: Prefer French.
- **Empty Chunks**: Do not return chunks with empty content.

---

## OUTPUT FORMAT (STRICT JSON)

Return a single JSON object with a "chunks" array.

```json
{{
  "chunks": [
    {{
      "content": "Full text content of the chunk...",
      "metadata": {{
        "type": "avis|specification|administrative|products",
        "lot": "1",          // "0" if single lot or not specified
        "designation": "...",  // Optional, for products
        "quantity": 100.0,     // Optional, for products
        "unit": "m2"           // Optional, for products
      }}
    }},
    ...
  ]
}}
Return ONLY valid JSON matching the schema. 
CRITICAL: Ensure the JSON string is properly closed and escaped.
"""
    
    def _extract_lot_from_content(self, content: str) -> str:
        """Extract lot identifier from chunk content."""
        lot_match = re.search(r'lot\s*[:\s]*(\d+)', content, re.IGNORECASE)
        if lot_match:
            return lot_match.group(1)
        return "ALL"
    
    def _standard_chunk_document(self, doc: LogicalDocument, tender_id: int, default_lot_ref: str) -> List[Dict[str, Any]]:
        """Apply standard text splitting for non-LLM documents.
        
        Args:
            doc: LogicalDocument to chunk
            tender_id: Database ID of the tender
            default_lot_ref: Default lot reference
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        text_chunks = self.text_splitter.split_text(doc.content)
        
        # Default type for unknown docs
        c_type = "general_technical_specs"
        
        for i, chunk_text in enumerate(text_chunks):
            if len(chunk_text.strip()) < 50:  # Skip very small chunks
                continue
            
            # ID: lot_ref_type_increment (using simple i as increment here, or should we track?)
            # Since standard chunking is one-pass per doc, 'i+1' is fine.
            generated_id = f"{default_lot_ref}_{c_type}_{i+1}"
            
            chunks.append({
                "id": generated_id,
                "content": chunk_text.strip(),
                "metadata": {
                    "type": c_type,
                    "tender_id": tender_id,
                    "source_doc": doc.original_filename,
                    "lot_reference": default_lot_ref
                }
            })
        
        return chunks
