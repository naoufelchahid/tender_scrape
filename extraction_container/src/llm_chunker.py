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
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

from src.cleaning import DocumentCleaners, LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.models import ChunkingOutput, ChunkItem
from src.prompts import (
    BASE_CONTEXT, AVIS_INSTRUCTION, AVIS_PROMPT,
    FORM_INSTRUCTION, FORM_PROMPT,
    ADMIN_SPEC_INSTRUCTION, ADMIN_SPEC_PROMPT,
    PRODUCT_INSTRUCTION, PRODUCT_EXAMPLE, PRODUCT_PROMPT,
    FALLBACK_PROMPT
)

logger = logging.getLogger(__name__)


# Document types that use LLM-assisted chunking
LLM_CHUNK_TYPES = {'product', 'specification', 'administrative', 'avis', 'form'}

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
INTEGRITY_MIN_RETENTION = 80.0   # % minimum content retention
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
    
    async def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int, tender_ref: str) -> List[Dict[str, Any]]:
        """Process all documents and generate chunks asynchronously.
        
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
        

        
        logger.info(f"Processing {len(valid_docs)} documents with concurrency...")
        
        # Semaphore to limit concurrent LLM requests
        semaphore = asyncio.Semaphore(5)

        async def process_doc(doc, index):
            async with semaphore:
                logger.info(f"[{index+1}/{len(valid_docs)}] Processing doc: {doc.original_filename} (Type: {doc.doc_type})")
                try:
                    # Basic size check
                    if len(doc.content.strip()) < 50:
                        return []

                    doc_chunks = await self._chunk_single_document(doc, tender_id, tender_ref, default_lot_ref)
                    
                    # Integrity Check
                    self._validate_content_integrity(doc, doc_chunks)
                    
                    return doc_chunks
                except Exception as e:
                    logger.error(f"Failed to chunk document {doc.original_filename}: {e}", exc_info=True)
                    # Fallback to standard chunking
                    return self._standard_chunk_document(doc, tender_id, default_lot_ref)

        tasks = [process_doc(doc, i) for i, doc in enumerate(valid_docs)]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            all_chunks.extend(res)
        
        logger.info(f"Total chunks generated from all documents: {len(all_chunks)}")
        return all_chunks

    async def _chunk_single_document(
        self, 
        doc: LogicalDocument, 
        tender_id: int, 
        tender_ref: str, 
        default_lot_ref: str
    ) -> List[Dict[str, Any]]:
        """Process a single document with LLM. Handles pagination for Admin/Spec."""
        
        # Pagination Logic for Admin/Spec
        if doc.doc_type in ['administrative', 'specification']:
            # Use '## Page' splitting logic
            return await self._chunk_paginated_pages(doc, tender_id, tender_ref, default_lot_ref)
            
        # Standard Single-Shot for others (Avis, Form, Product)
        # Note: Product might be large, but user said "keep all what between balises as one chunk".
        # If it's too huge, LLM might truncate. Ideally we trust BDP extractor provided manageable blocks.
        if len(doc.content) > LARGE_DOC_THRESHOLD and doc.doc_type not in ['product', 'avis', 'form']:
             logger.info(f"Fallback pagination for large {doc.doc_type}")
             # Only fallback if not one of the mandated 'single chunk' types
             return await self._chunk_paginated_document(doc, tender_id, tender_ref, default_lot_ref)

        prompt = self._get_single_doc_prompt(doc, tender_ref)
        
        response = await self.llm.chat_completion_async(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True
        )
        
        if not response or len(response) < 10:
             logger.warning(f"Empty/Tiny LLM response for {doc.original_filename}, falling back")
             return self._standard_chunk_document(doc, tender_id, default_lot_ref)

        try:
            response_data = json_repair.loads(response)
            if isinstance(response_data, list):
                response_data = {"chunks": response_data}
            
            parsed_output = ChunkingOutput(**response_data)
            return self._convert_to_chunk_dicts(parsed_output.chunks, tender_id, tender_ref, default_lot_ref)
        except Exception as e:
            logger.error(f"Failed to parse LLM output for {doc.original_filename}: {e}")
            return self._standard_chunk_document(doc, tender_id, default_lot_ref)


    async def _chunk_paginated_pages(
        self,
        doc: LogicalDocument,
        tender_id: int,
        tender_ref: str,
        default_lot_ref: str
    ) -> List[Dict[str, Any]]:
        """
        Split document by '## Page' markers and process in groups of 3 pages asynchronously.
        """
        # Split by ## Page (case insensitive)
        page_pattern = r'(?i)(##\s*Page\s*\d+)'
        parts = re.split(page_pattern, doc.content)
        
        pages = []
        if parts[0].strip():
            pages.append(parts[0])
            
        i = 1
        while i < len(parts):
            header = parts[i] if i < len(parts) else ""
            content = parts[i+1] if i+1 < len(parts) else ""
            pages.append(header + content)
            i += 2
            
        if not pages:
            logger.info(f"No '## Page' headers found in {doc.original_filename}, falling back to character pagination.")
            return await self._chunk_paginated_document(doc, tender_id, tender_ref, default_lot_ref)
            
        # Group by 3
        page_groups = [pages[i:i+3] for i in range(0, len(pages), 3)]
        
        logger.info(f"Paginating {doc.original_filename} into {len(page_groups)} groups (3 pages each). Total Pages: {len(pages)}")
        
        all_chunks = []

        async def process_group(idx, group):
            group_content = "\n".join(group)
            
            group_doc = LogicalDocument(
                original_filename=f"{doc.original_filename} (Pages {idx*3+1}-{idx*3+len(group)})",
                content=group_content,
                doc_type=doc.doc_type
            )
            
            prompt = self._get_single_doc_prompt(group_doc, tender_ref)
            
            try:
                response = await self.llm.chat_completion_async(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    json_mode=True
                )
                
                if response:
                    data = json_repair.loads(response)
                    if isinstance(data, list): data = {"chunks": data}
                    parsed = ChunkingOutput(**data)
                    return self._convert_to_chunk_dicts(parsed.chunks, tender_id, tender_ref, default_lot_ref)
            except Exception as e:
                 logger.error(f"Error chunking page group {idx} for {doc.original_filename}: {e}")
            return []

        tasks = [process_group(idx, group) for idx, group in enumerate(page_groups)]
        results = await asyncio.gather(*tasks)
        
        for chks in results:
            all_chunks.extend(chks)
        
        return all_chunks

    async def _chunk_paginated_document(
        self,
        doc: LogicalDocument,
        tender_id: int,
        tender_ref: str,
        default_lot_ref: str
    ) -> List[Dict[str, Any]]:
        """Chunk a specific large document by splitting it into pages/segments asynchronously."""
        
        # Split content into macro-segments (pages)
        segments = self.pagination_splitter.split_text(doc.content)
        total_segments = len(segments)
        logger.info(f"--> Paginating heavy document into {total_segments} segments (Size: {len(doc.content)} chars)")
        
        all_chunk_items: List[ChunkItem] = []
        
        async def process_segment(idx, segment_content):
            logger.info(f"  -> Processing Segment {idx+1}/{total_segments}")
            
            segment_doc = LogicalDocument(
                original_filename=doc.original_filename,
                doc_type=doc.doc_type,
                content=segment_content,
                page_start=idx * 20 + 1, 
                page_end=(idx + 1) * 20
            )
            
            prompt = self._get_single_doc_prompt(segment_doc, tender_ref)
            
            try:
                response = await self.llm.chat_completion_async(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    json_mode=True
                )
                
                if response and len(response) > 10:
                     response_data = json_repair.loads(response)
                     if isinstance(response_data, list):
                         response_data = {"chunks": response_data}
                     parsed = ChunkingOutput(**response_data)
                     return parsed.chunks
                else:
                    logger.warning(f"     Empty response for segment {idx+1}")
            except Exception as e:
                logger.error(f"     Failed segment {idx+1}: {e}")
            return []

        tasks = [process_segment(i, seg) for i, seg in enumerate(segments)]
        results = await asyncio.gather(*tasks)
        
        for chks in results:
            all_chunk_items.extend(chks)
        
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
            raw_lot = str(item.metadata.lot_number) if item.metadata.lot_number else "0"
            clean_lot_num = raw_lot.lower().replace("lot", "").strip()
            
            # Ensure we have a valid lot number string (e.g. "1")
            # If empty or invalid, default to "0"
            if not clean_lot_num or clean_lot_num == "none":
                clean_lot_num = "0"



            # ------------------------------------------------------------------
            # ID GENERATION
            # Structure: {tender_ref}_0(lot number)_type_1 increment
            # ------------------------------------------------------------------
            chunk_type = item.metadata.type
            
            # Format lot number (0 -> 00, 1 -> 01)
            try:
                lot_int = int(clean_lot_num)
                formatted_lot = f"{lot_int:02d}" 
            except ValueError:
                formatted_lot = f"0{clean_lot_num}"
            
            # Increment counter
            counter_key = f"{formatted_lot}_{chunk_type}"
            if counter_key not in type_counters:
                type_counters[counter_key] = 1
            idx = type_counters[counter_key]
            type_counters[counter_key] += 1
            
            # Final ID
            chunk_id = f"{tender_ref}_{formatted_lot}_{chunk_type}_{idx}"
            
            # Build metadata dictionary
            metadata = {
                "type": chunk_type
            }
            
            # Dump all Pydantic fields to dict
            raw_meta = item.metadata.model_dump(exclude_none=True)
            
            # Merge raw fields (preserving our calculated ones)
            for k, v in raw_meta.items():
                if k not in metadata:
                    metadata[k] = v
            
            chunks.append({
                "id": chunk_id,
                "content": item.content.strip(),
                "metadata": metadata
            })
        
        return chunks

    # Updated LLM Chunk Types per user request
    LLM_CHUNK_TYPES = {'product', 'specification', 'administrative', 'avis', 'form'}

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

    def _get_single_doc_prompt(self, doc: LogicalDocument, tender_ref: str) -> str:
        """Create a tailored prompt based on document type."""
        
        base_context = BASE_CONTEXT.format(
            tender_ref=tender_ref,
            doc_type=doc.doc_type.upper(),
            filename=doc.original_filename
        )
        
        # 1. AVIS
        if doc.doc_type == 'avis':
            return AVIS_PROMPT.format(
                base_context=base_context,
                content=doc.content[:PROMPT_MAX_CHARS_AVIS],
                instruction=AVIS_INSTRUCTION
            )

        # 2. FORM
        elif doc.doc_type == 'form':
            instruction = FORM_INSTRUCTION.format(
                tender_ref=tender_ref
            )
            return FORM_PROMPT.format(
                base_context=base_context,
                content=doc.content[:PROMPT_MAX_CHARS_ENGAGEMENT],
                instruction=instruction,
                tender_ref=tender_ref
            )

        # 3. ADMINISTRATIVE / SPECIFICATION
        elif doc.doc_type in ['administrative', 'specification']:
            instruction = ADMIN_SPEC_INSTRUCTION.format(
                doc_type=doc.doc_type
            )
            return ADMIN_SPEC_PROMPT.format(
                base_context=base_context,
                content=doc.content[:PROMPT_MAX_CHARS_ADMIN],
                instruction=instruction,
                doc_type=doc.doc_type
            )

        # 4. PRODUCT
        elif doc.doc_type == 'product':
            return PRODUCT_PROMPT.format(
                base_context=base_context,
                content=doc.content[:PROMPT_MAX_CHARS_PRODUCT],
                instruction=PRODUCT_INSTRUCTION,
                example=PRODUCT_EXAMPLE
            )

        # Fallback
        else:
             return FALLBACK_PROMPT.format(
                 base_context=base_context,
                 content=doc.content[:PROMPT_MAX_CHARS_OTHER]
             )


    
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
                    "source_doc": doc.original_filename
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
