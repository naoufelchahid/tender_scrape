"""
Document Chunking Service with specialized logic per type.
Replaces llm_chunker.py.
"""

import re
import json
import json_repair
import logging
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.cleaning import LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.models import ChunkingOutput, ChunkItem
from src.prompts import (
    BASE_CONTEXT, AVIS_INSTRUCTION, AVIS_PROMPT,
    PRODUCT_INSTRUCTION, PRODUCT_EXAMPLE, PRODUCT_PROMPT
)

logger = logging.getLogger(__name__)

# Standard chunking settings for fallback
STANDARD_CHUNK_SIZE = 4000  # chars
STANDARD_CHUNK_OVERLAP = 200

@dataclass
class DocumentChunker:
    """Specialized chunking logic for tender documents."""
    
    def __init__(self, region_name: str, openrouter_api_key: Optional[str] = None):
        self.region_name = region_name
        self.llm = OpenRouterClientWrapper(api_key=openrouter_api_key)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE,
            chunk_overlap=STANDARD_CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " "]
        )

    async def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int, tender_ref: str) -> List[Dict[str, Any]]:
        """Process all documents according to their specific rules."""
        all_chunks = []
        
        # Group Avis by language to follow the rule: send French if exists, else Arabic
        avis_docs = [d for d in docs if d.doc_type == 'avis']
        non_avis_docs = [d for d in docs if d.doc_type != 'avis']
        
        # 1. Process Avis
        if avis_docs:
            french_avis = [d for d in avis_docs if self._is_french(d.content)]
            arabic_avis = [d for d in avis_docs if not self._is_french(d.content)]
            
            target_avis = french_avis if french_avis else arabic_avis
            for doc in target_avis:
                logger.info(f"Processing Avis (LLM): {doc.original_filename}")
                chunks = await self._process_with_llm(doc, tender_ref, tender_id)
                all_chunks.extend(chunks)

        # 2. Process others
        semaphore = asyncio.Semaphore(5)

        async def process_doc(doc):
            async with semaphore:
                logger.info(f"Processing {doc.doc_type}: {doc.original_filename}")
                
                if doc.doc_type == 'product':
                    return await self._process_with_llm(doc, tender_ref, tender_id)
                
                elif doc.doc_type in ['specification', 'administrative']:
                    return self._split_by_headers(doc, tender_ref, tender_id)
                
                elif doc.doc_type in ['engagement', 'declaration', 'annexe']:
                    return self._simple_split(doc, tender_ref, tender_id)
                
                else:
                    logger.warning(f"Unknown doc type {doc.doc_type}, using simple split")
                    return self._simple_split(doc, tender_ref, tender_id)

        tasks = [process_doc(doc) for doc in non_avis_docs]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            all_chunks.extend(res)
            
        return all_chunks

    def _is_french(self, text: str) -> bool:
        """Check if content is predominantly French/Latin."""
        sample = text[:1000]
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', sample))
        total_chars = len(sample.strip())
        if total_chars == 0: return True
        return (arabic_chars / total_chars) < 0.4

    async def _process_with_llm(self, doc: LogicalDocument, tender_ref: str, tender_id: int) -> List[Dict[str, Any]]:
        """LLM metadata extraction for Avis and Product."""
        base_context = BASE_CONTEXT.format(
            tender_ref=tender_ref,
            doc_type=doc.doc_type.upper(),
            filename=doc.original_filename
        )
        
        if doc.doc_type == 'avis':
            prompt = AVIS_PROMPT.format(base_context=base_context, content=doc.content[:100000], instruction=AVIS_INSTRUCTION)
        else: # product
            prompt = PRODUCT_PROMPT.format(base_context=base_context, content=doc.content[:100000], instruction=PRODUCT_INSTRUCTION, example=PRODUCT_EXAMPLE)

        response = await self.llm.chat_completion_async(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True
        )
        
        try:
            data = json_repair.loads(response)
            if isinstance(data, list): data = {"chunks": data}
            parsed = ChunkingOutput(**data)
            return self._finalize_chunks(parsed.chunks, tender_ref, tender_id, doc.doc_type)
        except Exception as e:
            logger.error(f"LLM parsing failed for {doc.doc_type}: {e}")
            return self._simple_split(doc, tender_ref, tender_id)

    def _split_by_headers(self, doc: LogicalDocument, tender_ref: str, tender_id: int) -> List[Dict[str, Any]]:
        """Split Specification/Administrative documents by H3, keeping H2 and H3 context."""
        content = doc.content
        lines = content.split('\n')
        
        chunks = []
        current_h2 = ""
        current_h3 = ""
        current_buffer = []
        
        for line in lines:
            if line.startswith('## '):
                # Save previous chunk if header changes
                if current_buffer:
                    chunks.append(self._create_header_chunk(current_buffer, doc.doc_type, current_h2, current_h3))
                    current_buffer = []
                current_h2 = line.strip()
                current_h3 = "" # Reset H3 when new H2 starts
            elif line.startswith('### '):
                if current_buffer:
                    chunks.append(self._create_header_chunk(current_buffer, doc.doc_type, current_h2, current_h3))
                    current_buffer = []
                current_h3 = line.strip()
            else:
                current_buffer.append(line)
                
        if current_buffer:
            chunks.append(self._create_header_chunk(current_buffer, doc.doc_type, current_h2, current_h3))
            
        return self._finalize_chunks(chunks, tender_ref, tender_id, doc.doc_type)

    def _create_header_chunk(self, buffer: List[str], doc_type: str, h2: str, h3: str) -> ChunkItem:
        content = "\n".join(buffer).strip()
        return ChunkItem(
            content=content,
            metadata={
                "type": doc_type,
                "H2": h2,
                "H3": h3
            }
        )

    def _simple_split(self, doc: LogicalDocument, tender_ref: str, tender_id: int) -> List[Dict[str, Any]]:
        """Simplified chunking for engagement, declaration, annexe."""
        text_chunks = self.text_splitter.split_text(doc.content)
        chunk_items = []
        
        # For annexe, we might want to capture a title from the first lines
        doc_header = ""
        if doc.doc_type == 'annexe' and text_chunks:
            # Try to grab the first # or ## as doc_header
            header_match = re.search(r'^#+\s+(.*)$', doc.content, re.MULTILINE)
            if header_match:
                doc_header = header_match.group(1).strip()

        for chunk_text in text_chunks:
            meta = {"type": doc.doc_type}
            if doc_header:
                meta["doc_header"] = doc_header
            
            chunk_items.append(ChunkItem(content=chunk_text, metadata=meta))
            
        return self._finalize_chunks(chunk_items, tender_ref, tender_id, doc.doc_type)

    def _finalize_chunks(self, items: List[ChunkItem], tender_ref: str, tender_id: int, doc_type: str) -> List[Dict[str, Any]]:
        """Add IDs and format as dictionaries."""
        final_chunks = []
        for i, item in enumerate(items):
            if not item.content.strip(): continue
            
            lot_num = "00" # Default
            # Attempt to extract lot_number if present in metadata (for Avis)
            if item.metadata and item.metadata.get('lot_number'):
                try:
                    lot_val = int(item.metadata['lot_number'])
                    lot_num = f"{lot_val:02d}"
                except:
                    pass
            
            chunk_id = f"{tender_ref}_{lot_num}_{item.metadata.get('type', doc_type)}_{i+1}"
            
            final_chunks.append({
                "id": chunk_id,
                "content": item.content.strip(),
                "metadata": item.metadata if isinstance(item.metadata, dict) else item.metadata.model_dump()
            })
        return final_chunks
