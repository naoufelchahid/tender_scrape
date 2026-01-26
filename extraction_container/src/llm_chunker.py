"""
LLM-Assisted Intelligent Document Chunking Service.

Uses OpenRouter API via OpenRouterClientWrapper to analyze documents and create
semantically meaningful chunks with proper metadata.
"""

import re
import json
import json_repair
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
LLM_CHUNK_TYPES = {'product', 'specification', 'administrative', 'avis', 'engagement', 'declaration'}

# Standard chunking settings for 'other' documents
STANDARD_CHUNK_SIZE = 500  # tokens (approx chars/4)
STANDARD_CHUNK_OVERLAP = 100

# Large Document Pagination Settings
LARGE_DOC_THRESHOLD = 30000  
PAGINATION_SIZE = 20000      
PAGINATION_OVERLAP = 1000

# LLM Prompt Content Limits (chars to send to LLM)
PROMPT_MAX_CHARS_AVIS = 100_000
PROMPT_MAX_CHARS_ADMIN = 100_000
PROMPT_MAX_CHARS_SPEC = 100_000
PROMPT_MAX_CHARS_PRODUCT = 100_000
PROMPT_MAX_CHARS_ENGAGEMENT = 50_000
PROMPT_MAX_CHARS_DECLARATION = 50_000
PROMPT_MAX_CHARS_OTHER = 50_000

# Integrity Check Thresholds
INTEGRITY_MIN_RETENTION = 70.0   # % minimum content retention
INTEGRITY_MAX_RETENTION = 120.0  # % maximum content retention

@dataclass
class Chunk:
    """Represents a document chunk with metadata."""
    id: str
    content: str
    metadata: Dict[str, Any]


class ChunkingIntegrityError(Exception):
    """Raised when LLM chunking fails to meet content integrity thresholds."""
    pass

class LLMChunker:
    """LLM-assisted intelligent document chunking using OpenRouterClientWrapper."""
    
    def __init__(self, region_name: str, openrouter_api_key: Optional[str] = None):
        """Initialize the LLM chunker.
        
        Args:
            region_name: AWS region (maintained for compatibility)
            openrouter_api_key: API Key for OpenRouter
        """
        self.region_name = region_name
        
        # Initialize centralized OpenRouter Wrapper
        self.llm = OpenRouterClientWrapper(api_key=openrouter_api_key)
        
        # Standard text splitter for fallback/other documents
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE * 4,  # chars approx
            chunk_overlap=STANDARD_CHUNK_OVERLAP * 4,
            separators=["\n\n", "\n", ". ", " "]
        )
        
        # Splitter for pagination (large docs)
        self.pagination_splitter = RecursiveCharacterTextSplitter(
            chunk_size=PAGINATION_SIZE,
            chunk_overlap=PAGINATION_OVERLAP,
            separators=["\n\n", "\n", ". ", " "]
        )
    
    def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int, tender_ref: str) -> List[Dict[str, Any]]:
        """Process all documents and generate chunks.
        
        Args:
            docs: List of LogicalDocument objects
            tender_id: Database ID of the tender
            tender_ref: Tender Reference string
            
        Returns:
            List of chunk dictionaries with id, content, metadata
        """
        all_chunks = []
        
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
        
        # Check if we have any product documents (BDP)
        has_bdp = any(d.doc_type == 'product' for d in valid_docs)
        if not has_bdp:
            logger.info("No separate BDP found. Enabling product extraction from CPS.")
        
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

                doc_chunks = self._chunk_single_document(doc, tender_id, tender_ref, default_lot_ref, has_bdp=has_bdp)
                
                # Integrity Check
                self._validate_content_integrity(doc, doc_chunks)
                
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
        default_lot_ref: str,
        has_bdp: bool = True
    ) -> List[Dict[str, Any]]:
        """Process a single document with LLM. Handles pagination for large docs."""
        
        # Check for large document pagination
        if len(doc.content) > LARGE_DOC_THRESHOLD:
            logger.info(f"Large document detected ({len(doc.content)} chars). Using pagination strategy.")
            return self._chunk_paginated_document(doc, tender_id, tender_ref, default_lot_ref, has_bdp)

        prompt = self._get_single_doc_prompt(doc, tender_ref, has_bdp)
        
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
            response_data = json_repair.loads(response)
            
            # Auto-fix: If LLM returned a list directly instead of {"chunks": [...]}
            if isinstance(response_data, list):
                logger.info("LLM returned a list directly, wrapping in 'chunks' object.")
                response_data = {"chunks": response_data}
                
            parsed_output = ChunkingOutput(**response_data)
            logger.info(f"  -> Parsed {len(parsed_output.chunks)} chunks")
        except Exception as parse_err:
            logger.error(f"Parsing failed for {doc.original_filename}: {parse_err}")
            return self._standard_chunk_document(doc, tender_id, default_lot_ref)
        
        # Convert to Clean Chunks
        chunks = self._convert_to_chunk_dicts(
            parsed_output.chunks, 
            tender_id, 
            tender_ref, 
            default_lot_ref
        )
        
        return chunks

    def _chunk_paginated_document(
        self,
        doc: LogicalDocument,
        tender_id: int,
        tender_ref: str,
        default_lot_ref: str,
        has_bdp: bool = True
    ) -> List[Dict[str, Any]]:
        """Chunk a specific large document by splitting it into pages/segments."""
        
        # Split content into macro-segments (pages)
        segments = self.pagination_splitter.split_text(doc.content)
        total_segments = len(segments)
        logger.info(f"--> Paginating heavy document into {total_segments} segments (Size: {len(doc.content)} chars)")
        
        all_chunk_items: List[ChunkItem] = []
        
        for idx, segment_content in enumerate(segments):
            logger.info(f"  -> Processing Segment {idx+1}/{total_segments}")
            
            # Create a temporary 'view' of the doc for this segment
            # We preserve metadata but swap content
            segment_doc = LogicalDocument(
                original_filename=doc.original_filename,
                doc_type=doc.doc_type,
                content=segment_content,
                page_start=idx * 20 + 1, # Rough estimation if needed, or 0
                page_end=(idx + 1) * 20
            )
            
            # Use standard prompt generator but potentially we could inject "Part X/Y" info if the prompt builder supported it.
            # For now, the standard prompt handles "content" well even if partial.
            # We'll just run it as a normal LLM call on this segment.
            prompt = self._get_single_doc_prompt(segment_doc, tender_ref, has_bdp)
            
            try:
                response = self.llm.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    json_mode=True
                )
                
                if response and len(response) > 10:
                     response_data = json_repair.loads(response)
                     
                     # Auto-fix for list responses
                     if isinstance(response_data, list):
                         response_data = {"chunks": response_data}
                         
                     parsed = ChunkingOutput(**response_data)
                     all_chunk_items.extend(parsed.chunks)
                     logger.info(f"     Extracted {len(parsed.chunks)} items from segment {idx+1}")
                else:
                    logger.warning(f"     Empty response for segment {idx+1}")

            except Exception as e:
                logger.error(f"     Failed segment {idx+1}: {e}")
        
        # Convert all pooled items to chunks
        if not all_chunk_items:
            logger.error(f"Pagination yielded 0 chunks for {doc.original_filename}")
            return []
            
        return self._convert_to_chunk_dicts(all_chunk_items, tender_id, tender_ref, default_lot_ref)
    
    def _convert_to_chunk_dicts(
        self, 
        chunk_items: List[ChunkItem],
        tender_id: int,
        tender_ref: str,
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
            # Default to {tender_ref}_{num} since we don't have metadata yet
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
            if item.metadata.estimated_price is not None:
                 metadata["estimated_price"] = item.metadata.estimated_price
            
            # Common/Other fields
            if item.metadata.title:
                metadata["title"] = item.metadata.title
            if item.metadata.article_id:
                metadata["article_id"] = item.metadata.article_id
            
            # Specific types
            if item.metadata.spec_type:
                metadata["spec_type"] = item.metadata.spec_type
            if item.metadata.clause_type:
                metadata["clause_type"] = item.metadata.clause_type
            
            # Avis fields
            if item.metadata.budget is not None: metadata["budget"] = item.metadata.budget
            if item.metadata.location: metadata["location"] = item.metadata.location
            if item.metadata.deadline: metadata["deadline"] = item.metadata.deadline
            if item.metadata.caution is not None: metadata["caution"] = item.metadata.caution
            if item.metadata.lot_structure: metadata["lot_structure"] = item.metadata.lot_structure
            
            chunks.append({
                "id": chunk_id,
                "content": item.content.strip(),
                "metadata": metadata
            })
        
        return chunks
    
    def _should_skip_document(self, doc: LogicalDocument) -> bool:
        """
        Check if document should be excluded from processing.
        Excluded if it's an Arabic Avis (Avis type + >40% Arabic content).
        """
        # Check for Arabic Avis
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
    
    def _get_single_doc_prompt(self, doc: LogicalDocument, tender_ref: str, has_bdp: bool = True) -> str:
        """Create a tailored prompt based on document type."""
        
        base_context = f"""You are a STRICT TEXT SEGMENTATION ENGINE. You are NOT a summarizer.
TENDER REF: {tender_ref}
DOC TYPE: {doc.doc_type.upper()}
FILENAME: {doc.original_filename}

CRITICAL RULES:
1. **NO LOSS**: The "content" field in your output JSON must contain the EXACT, VERBATIM text from the source.
2. **NO SUMMARIZATION**: Do not summarize, paraphrase, or truncate the text.
3. **NO OMISSIONS**: Do not use placeholders like "[...]" or "Rest of text...".
4. **INTEGRITY**: The sum of all "content" fields in your output must equal the length of the input text (minus protocol/header overhead).
"""
        
        # 1. AVIS (Tender Notice)
        if doc.doc_type == 'avis':
            return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_AVIS]}

TASK:
Return the document as ONE single chunk. Content must be STRICTLY IDENTICAL to input.
Extract metadata fields from the text. if there is other tenders informations in the document, ignore them, extract only the informations of the tender we are processing. 

METADATA TO EXTRACT:
- `budget`: Total budget (number), extract budget of tender we are processing if there is other tenders informations in the document, ignore them, extract only the budget of the tender we are processing. 
- `location`: Execution location.
- `deadline`: Submission deadline.
- `caution`: Caution amount (number).
- `lot_structure`: return list of lot number and titles if there is no lot structure in the document return "Single lot".

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "FULL VERBATIM CONTENT HERE...",
      "metadata": {{
        "type": "avis",
        "budget": 120000.00,
        "location": "Rabat",
        "deadline": "2024-01-01",
        "caution": 5000.00,
        "lot_structure": "Single lot"
      }}
    }}
  ]
}}
"""


        # 2. ADMINISTRATIVE (RC, Reglement)
        elif doc.doc_type == 'administrative':
            return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_ADMIN]}

TASK:
Segment the text by ARTICLE or MAJOR SECTION.
Each chunk's content must be the EXACT RAW TEXT of that section.
**CRITICAL**: IF YOU FIND A PRICING TABLE OR LIST OF PRODUCTS/PRICES (Bordereau/Détail Estimatif) embedded in this document, EXTRACT EACH ROW as a separate 'products' chunk.

METADATA TO EXTRACT:
For CLAUSES/ARTICLES:
- `title`: Header/Title of the section. should be in french.
- `clause_type`: [general_clause, bidding_modalities, bid_eval_critera, contractor_eval_criterea, attribution_criterea].
- `lot`: "{tender_ref}_0" (or specific lot if stated).

For PRODUCTS (if found):
- `type`: "products"
- `designation`: Full item designation as mentioned in the table.
- `quantity`: Number.
- `unit`: Unit.
- `estimated_price`: Price.
- `lot`: "{tender_ref}_0" (or specific lot if stated).

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "RAW TEXT OF ARTICLE 1...",
      "metadata": {{
        "type": "administrative",
        "title": "Objet du règlement",
        "clause_type": "general_clause",
        "lot": "{tender_ref}_0"
      }}
    }},
    {{
      "content": "Line item text...",
      "metadata": {{
        "type": "products",
        "designation": "Concrete C25/30",
        "quantity": 100,
        "unit": "m3",
        "estimated_price": 500.00,
        "lot": "{tender_ref}_1"
      }}
    }}
  ]
}}
"""


        # 3. SPECIFICATIONS (CPS, CCTP)
        elif doc.doc_type == 'specification':
            # AGGRESSIVE PRODUCT SEARCH: Always look for products even if has_bdp was True (to catch missed ones)
            task_instruction = """TASK:
Segment by CLAUSE, ARTICLE, or TECHNICAL SECTION.
Content must be VERBATIM. Do not summarize technical details. RETURN the raw text of the section.
**AGGRESSIVELY SEARCH FOR PRICING TABLES/BILLS OF QUANTITIES (Bordereau/Détail Estimatif).**
If found, extract EACH ROW as a 'products' chunk. Do not miss any items.
"""
            metadata_instruction = """METADATA TO EXTRACT:
For SPECIFICATIONS:
- `type`: "specification"
- `title`: Title , should be in french and be small generated description of the section don't include "Article 1" or "Clause 1" and generique terms.
- `spec_type`: [product_spec, contractor_requirement, general_spec, administratif_spec, legal_normal].

For PRICING/PRODUCTS (BDP Items):
- `type`: "products"
- `designation`: Full item designation as mentioned in the table.
- `quantity`: Number.
- `unit`: Unit.
- `estimated_price`: Price.
- `lot`: Lot number (if specified, else "{tender_ref}_0").
"""
            example_json = """{{
  "chunks": [
    {{
      "content": "RAW TEXT OF ARTICLE 1...",
      "metadata": {{ "type": "specification", "title": "Généralités", "spec_type": "general_spec", "lot": "{tender_ref}_0" }}
    }},
    {{
      "content": "Item description row...",
      "metadata": {{ "type": "products", "designation": "Mur en brique", "quantity": 150, "unit": "m2", "estimated_price": 45.0, "lot": "{tender_ref}_1" }}
    }}
  ]
}}"""

            return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_SPEC]}

{task_instruction}

{metadata_instruction}

OUTPUT JSON:
{example_json}
"""

        # 4. PRODUCTS (BDP, Bordereau)
        elif doc.doc_type == 'product':
            # NOTE: Products are the EXCEPTION to the "Verbatim" rule because they are tabular data.
            # We specifically want to parse them into metadata.
            return f"""You are a DATA EXTRACTION ENGINE.
TENDER REF: {tender_ref}
DOC TYPE: {doc.doc_type.upper()}

TASK:
Extract structured data from the PRICING TABLE. 
Create **ONE CHUNK PER LINE ITEM**.

METADATA TO EXTRACT:
- `designation`: Full item designation.
- `quantity`: Quantity (number).
- `unit`: Unit (e.g., m2, U).
- `estimated_price`: Unit price (if available).
- `lot`: Lot number.

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "Full text of the line item...",
      "metadata": {{
        "type": "products",
        "designation": "Mur en béton armé...",
        "quantity": 500.0,
        "unit": "m3",
        "estimated_price": 1200.0,
        "lot": "1"
      }}
    }}
  ]
}}
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_PRODUCT]}
"""

        # 5. ENGAGEMENT (Acte d'engagement)
        elif doc.doc_type == 'engagement':
            return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_ENGAGEMENT]}

TASK:
Return as ONE single chunk. Content must be IDENTICAL to input.


OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "FULL VERBATIM CONTENT...",
      "metadata": {{
        "type": "engagement"   
      }}
    }}
  ]
}}
"""

        # 6. DECLARATION (Sur l'honneur)
        elif doc.doc_type == 'declaration':
            return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_DECLARATION]}

TASK:
Return as ONE single chunk. Content must be IDENTICAL to input.



OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "FULL VERBATIM CONTENT...",
      "metadata": {{
        "type": "declaration",
      }}
    }}
  ]
}}
"""

        # DEFAULT / FALLBACK
        else:
             return base_context + f"""
CONTENT:
{doc.content[:PROMPT_MAX_CHARS_OTHER]}

TASK:
Segment into logical sections. Content must be VERBATIM.

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "RAW TEXT...",
      "metadata": {{
        "type": "other",
        "title": "Section title"
      }}
    }}
  ]
}}
"""
    
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
                    "source_doc": doc.original_filename,
                    "lot_reference": default_lot_ref
                }
            })
        
        return chunks

    def _validate_content_integrity(self, doc: LogicalDocument, chunks: List[Dict[str, Any]]) -> float:
        """
        Validates that the chunked content roughly matches the original content size.
        Returns the retention percentage (0.0 to 100+).
        """
        if not chunks:
            return 0.0

        # 1. content mass (ignore whitespace)
        original_mass = len(re.sub(r'\s+', '', doc.content))
        
        chunk_mass = 0
        for c in chunks:
            # For product chunks, the 'content' might be small (just designation), 
            # but meaningful data is in metadata. 
            # Ideally we check metadata values too, but for now lets check purely text content.
            # If doc_type is product/bdp, we expect MASSIVE shrinking (text -> structured data).
            chunk_mass += len(re.sub(r'\s+', '', c.get('content', '')))
        
        if original_mass == 0:
            return 100.0

        ratio = chunk_mass / original_mass
        percentage = ratio * 100
        
        # BDP/Product documents are exceptions: they transform text to data, so size drops naturally.
        # We skip strict validation for them to avoid false alarms.
        if doc.doc_type == 'product':
             logger.info(f"Integrity Check (Product): retained {percentage:.1f}% of text mass (Expected behavior for structured extraction).")
             return 100.0 # Treat as passing

        # Thresholds
        if percentage < INTEGRITY_MIN_RETENTION:
            logger.warning(f"Integrity Check FAILED for {doc.original_filename}: Only {percentage:.1f}% of content retained! (Possible Data Loss)")
        elif percentage > INTEGRITY_MAX_RETENTION:
            logger.warning(f"Integrity Check WARNING for {doc.original_filename}: Output is {percentage:.1f}% of input! (Possible Hallucination/Repetition)")
        else:
            logger.debug(f"Integrity Check PASSED for {doc.original_filename}: {percentage:.1f}% retention.")
            
        return percentage
