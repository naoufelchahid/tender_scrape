"""
Document Chunking Service with specialized logic per type.
"""

import re
import json
import json_repair
import logging
import asyncio
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.cleaning import LogicalDocument
from src.openrouter_wrapper import OpenRouterClientWrapper
from src.models import (
    ChunkingOutput, ChunkItem, AvisMetadata, 
    SpecificationMetadata, AdministrativeMetadata, 
    ProductItemMetadata, ProductChunkMetadata
)
from src.prompts import (
    BASE_CONTEXT, AVIS_INSTRUCTION, AVIS_PROMPT,
    PRODUCT_INSTRUCTION, PRODUCT_EXAMPLE, PRODUCT_PROMPT
)

logger = logging.getLogger(__name__)

try:
    from decompose import decompose_text
    _DECOMPOSE_AVAILABLE = True
except ImportError:
    _DECOMPOSE_AVAILABLE = False
    logger.warning("decompose not installed. Document cleaning and semantic segmentation disabled.")

# Standard chunking settings for fallback
STANDARD_CHUNK_SIZE = 4000  # chars
STANDARD_CHUNK_OVERLAP = 200

@dataclass
class DocumentChunker:
    """Specialized chunking logic for tender documents."""
    
    def __init__(self, region_name: str = "us-east-1", openrouter_api_key: Optional[str] = None, client: Optional[OpenRouterClientWrapper] = None, decomposer_func: Optional[Any] = None):
        self.region_name = region_name
        self.llm = client or OpenRouterClientWrapper(api_key=openrouter_api_key)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE,
            chunk_overlap=STANDARD_CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " "]
        )
        self._decomposer_func = decomposer_func if decomposer_func is not None else (decompose_text if _DECOMPOSE_AVAILABLE else None)

    async def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int, tender_ref: str) -> Dict[str, List[Dict[str, Any]]]:
        """Process all documents and return a dictionary of chunks grouped by type."""
        all_chunks_by_type = defaultdict(list)
        
        avis_docs = [d for d in docs if 'avis' in d.doc_type.lower()]
        other_docs = [d for d in docs if 'avis' not in d.doc_type.lower()]
        
        # 1. Process Avis
        if avis_docs:
            # Prioritize French Avis if available
            french_avis = [d for d in avis_docs if d.doc_type == 'avis_fr' or (d.doc_type == 'avis' and self._is_french(d.content))]
            target_avis = french_avis if french_avis else avis_docs
            
            if target_avis:
                best_avis = max(target_avis, key=lambda d: len(d.content))
                logger.info(f"Selected Avis for LLM: {best_avis.original_filename} ({best_avis.doc_type})")
                chunks = await self._process_with_llm(best_avis, tender_ref, tender_id)
                all_chunks_by_type['avis'].extend(chunks)

        # 2. Process others in parallel
        semaphore = asyncio.Semaphore(5)

        async def process_doc(doc):
            async with semaphore:
                logger.info(f"Processing {doc.doc_type}: {doc.original_filename}")
                
                if doc.doc_type == 'product':
                    return 'product', await self._process_with_llm(doc, tender_ref, tender_id)
                
                elif doc.doc_type == 'administrative':
                    if self._decomposer_func:
                        return 'administrative', await self._segment_with_decompose(doc, tender_ref, tender_id)
                    return 'administrative', self._split_by_headers(doc, tender_ref, tender_id)
                
                elif doc.doc_type == 'specification':
                    if self._decomposer_func:
                        return 'specification', await self._segment_with_decompose(doc, tender_ref, tender_id)
                    return 'specification', self._split_by_headers(doc, tender_ref, tender_id)
                
                else:
                    target_type = doc.doc_type if doc.doc_type != "unknown" else "specification"
                    logger.warning(f"Defaulting {doc.doc_type} to {target_type}")
                    
                    # Clean noise before splitting for unknown/misc types
                    doc.content = self._clean_with_decompose(doc.content, target_type)
                    
                    # Use header split for structure if probable, else simple
                    if '##' in doc.content:
                        return target_type, self._split_by_headers(doc, tender_ref, tender_id, forced_type=target_type)
                    return target_type, self._simple_split(doc, tender_ref, tender_id, forced_type=target_type)

        tasks = [process_doc(doc) for doc in other_docs]
        results = await asyncio.gather(*tasks)
        
        for doc_type, chunks in results:
            all_chunks_by_type[doc_type].extend(chunks)
            
        return dict(all_chunks_by_type)

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
        
        # Clean content before LLM processing
        cleaned_content = self._clean_with_decompose(doc.content, doc.doc_type)
        
        if 'avis' in doc.doc_type.lower():
            prompt = AVIS_PROMPT.format(base_context=base_context, content=cleaned_content[:100000], instruction=AVIS_INSTRUCTION)
        else: # product
            prompt = PRODUCT_PROMPT.format(base_context=base_context, content=cleaned_content[:100000], instruction=PRODUCT_INSTRUCTION, example=PRODUCT_EXAMPLE)

        response = await self.llm.chat_completion_async(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True
        )
        
        try:
            data = json_repair.loads(response)
            if isinstance(data, list): data = {"chunks": data}
            
            # Robust filtering: ensure 'chunks' is a list and contains valid dicts with 'content'
            if isinstance(data, dict) and "chunks" in data and isinstance(data["chunks"], list):
                filtered_chunks = []
                for item in data["chunks"]:
                    if not isinstance(item, dict):
                        logger.warning(f"Skipping non-dictionary item in LLM chunks: {item}")
                        continue
                    if "content" not in item:
                        # Attempt to recover if it's a metadata-only dict
                        logger.warning(f"Skipping chunk missing 'content' field: {item}")
                        continue
                    filtered_chunks.append(item)
                data["chunks"] = filtered_chunks

            parsed = ChunkingOutput(**data)
            return self._finalize_chunks(parsed.chunks, tender_ref, tender_id, doc.doc_type)
        except Exception as e:
            logger.error(f"LLM parsing failed for {doc.doc_type}: {e}")
            return self._simple_split(doc, tender_ref, tender_id)

    def _split_by_headers(self, doc: LogicalDocument, tender_ref: str, tender_id: int, forced_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Split Specification/Administrative documents by H3, keeping H2 context."""
        content = doc.content
        lines = content.split('\n')
        
        chunks = []
        current_h2 = ""
        current_h3 = ""
        current_buffer = []
        doc_type = forced_type or doc.doc_type
        
        for line in lines:
            if line.startswith('## '):
                if current_buffer:
                    chunks.append(self._create_header_chunk(current_buffer, doc_type, current_h2, current_h3))
                    current_buffer = []
                current_h2 = line.lstrip('# ').strip()
                current_h3 = ""
            elif line.startswith('### '):
                if current_buffer:
                    chunks.append(self._create_header_chunk(current_buffer, doc_type, current_h2, current_h3))
                    current_buffer = []
                current_h3 = line.lstrip('# ').strip()
            else:
                current_buffer.append(line)
                
        if current_buffer:
            chunks.append(self._create_header_chunk(current_buffer, doc_type, current_h2, current_h3))
            
        return self._finalize_chunks([c for c in chunks if c.content.strip()], tender_ref, tender_id, doc_type)

    def _create_header_chunk(self, buffer: List[str], doc_type: str, h2: str, h3: str) -> ChunkItem:
        content = "\n".join(buffer).strip()
        return ChunkItem(
            content=content,
            metadata={
                "type": doc_type,
                "title": h3 if h3 else h2,
                "chapter": h2
            }
        )

    def _simple_split(self, doc: LogicalDocument, tender_ref: str, tender_id: int, forced_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Simplified chunking for other document types."""
        text_chunks = self.text_splitter.split_text(doc.content)
        chunk_items = []
        doc_type = forced_type or doc.doc_type
        
        for chunk_text in text_chunks:
            chunk_items.append(ChunkItem(
                content=chunk_text, 
                metadata={"type": doc_type}
            ))
            
        return self._finalize_chunks(chunk_items, tender_ref, tender_id, doc_type)

    def _clean_with_decompose(self, content: str, doc_type: str) -> str:
        """Strip noise (OCR artifacts, headers, footers) using decompose."""
        if not self._decomposer_func:
            return content
            
        try:
            result = self._decomposer_func(content, compact=True)
            units = result.get('units', [])
            cleaned = "\n".join([u['text'] for u in units if 'text' in u]).strip()
            
            # Minimum safety ratio: if cleaned < 20% of original, it might be too aggressive
            if not cleaned or len(cleaned) < len(content) * 0.20:
                logger.warning(f"Decompose cleaning too aggressive or failed for {doc_type}. Using raw content.")
                return content
            return cleaned
        except Exception as e:
            logger.warning(f"Decompose cleaning failed for {doc_type}: {e}. Using raw content.")
            return content

    async def _segment_with_decompose(self, doc: LogicalDocument, tender_ref: str, tender_id: int) -> List[Dict[str, Any]]:
        """Semantic segmentation using decompose for Specification/Administrative docs."""
        if not self._decomposer_func:
            return self._split_by_headers(doc, tender_ref, tender_id)
            
        try:
            # First clean the noise if not already done, or just use decompose with compact=False for segmentation
            result = self._decomposer_func(doc.content, compact=False)
            units = result.get('units', [])
            
            chunk_items = []
            current_h2 = ""
            current_h3 = ""
            
            for entry in units:
                # Map Decompose units to our ChunkItem
                text = entry.get('text', '').strip()
                if not text:
                    continue
                
                # Extract hierarchical headers from text if present
                # decompose usually splits at headers, but the header remains in the text
                lines = text.split('\n')
                for line in lines[:5]:  # Usually headers are at the top of the segment
                    stripped = line.strip()
                    if stripped.startswith('### '):
                        current_h3 = stripped.lstrip('# ').strip()
                    elif stripped.startswith('## '):
                        current_h2 = stripped.lstrip('# ').strip()
                        current_h3 = ""  # Reset H3 when entering a new H2
                    
                chunk_items.append(ChunkItem(
                    content=text,
                    metadata={
                        "type": doc.doc_type,
                        "title": current_h3 if current_h3 else (current_h2 if current_h2 else doc.doc_type),
                        "chapter": current_h2 if current_h2 else "General"
                    }
                ))
            
            if not chunk_items:
                return self._split_by_headers(doc, tender_ref, tender_id)
                
            return self._finalize_chunks(chunk_items, tender_ref, tender_id, doc.doc_type)
        except Exception as e:
            logger.error(f"Decompose segmentation failed for {doc.doc_type}: {e}. Falling back to header split.")
            return self._split_by_headers(doc, tender_ref, tender_id)

    def _finalize_chunks(self, items: List[ChunkItem], tender_ref: str, tender_id: int, doc_type: str) -> List[Dict[str, Any]]:
        """Add IDs and ensure metadata matches internal models."""
        final_chunks = []
        for i, item in enumerate(items):
            if not item.content.strip(): continue
            
            # Extract lot_number for ID generation (default to 00)
            lot_num = "00"
            raw_meta = item.metadata if isinstance(item.metadata, dict) else item.metadata.model_dump(by_alias=True)
            
            if 'lot_number' in raw_meta:
                try:
                    lot_num = f"{int(raw_meta['lot_number']):02d}"
                except:
                    pass
            
            chunk_id = f"{tender_ref}_{lot_num}_{doc_type}_{i+1}"
            
            # Clean metadata to keep only relevant fields per section
            cleaned_meta = self._clean_metadata_for_type(raw_meta, doc_type)

            content = item.content.strip()
            # Issue 2: Remove Arabic content from avis if present
            if doc_type == 'avis':
                content = re.sub(r'[\u0600-\u06FF]', '', content).strip()
                # Remove extra spaces/newlines that might remain after removal
                content = re.sub(r'\s+', ' ', content)

            final_chunks.append({
                "id": chunk_id,
                "content": content,
                "metadata": cleaned_meta
            })
        return final_chunks

    def _clean_metadata_for_type(self, meta: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
        """Ensures metadata only contains fields relevant to the section."""
        if doc_type == 'avis':
            allowed = {
                'type', 'objet', 'mode de soumission', 'mode de passation', 
                'qualifications', 'budget', 'location', 'deadline', 
                'caution', 'contact', 'phone', 'lot_number'
            }
            return {k: v for k, v in meta.items() if k in allowed}
        
        elif doc_type in ['specification', 'administrative']:
            allowed = {'type', 'title', 'chapter'}
            return {k: v for k, v in meta.items() if k in allowed}
            
        elif doc_type == 'product':
            # Allow standard fields + dynamic product_n keys
            return {k: v for k, v in meta.items() if k in {
                'type', 'product header', 'designation', 'quantity', 'unit'
            } or k.startswith('product_')}
            
        return meta
