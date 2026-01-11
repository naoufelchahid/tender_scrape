"""
LLM-Assisted Intelligent Document Chunking Service.

Uses Amazon Nova Micro via Bedrock to analyze documents and create
semantically meaningful chunks with proper metadata.
"""

import re
import json
import logging
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import boto3
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Optional import for OpenAI/OpenRouter
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from src.cleaning import DocumentCleaners, LogicalDocument
from src.prompts import get_chunking_prompt

logger = logging.getLogger(__name__)


# Document types that use LLM-assisted chunking
LLM_CHUNK_TYPES = {'product', 'specification', 'administrative', 'avis', 'other'}

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
    """LLM-assisted intelligent document chunking using Amazon Bedrock or OpenRouter."""
    
    def __init__(self, region_name: str, model_id: str, openrouter_api_key: Optional[str] = None):
        """Initialize the LLM chunker.
        
        Args:
            region_name: AWS region for Bedrock
            model_id: Model ID (Bedrock or OpenRouter)
            openrouter_api_key: API Key for OpenRouter (if using OpenRouter)
        """
        self.region_name = region_name
        self.model_id = model_id
        
        # Use Groq API for chunking (matching nova_extractor approach)
        if openrouter_api_key:
            logger.info(f"Using Groq API with model: {model_id}")
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=openrouter_api_key)
                self.use_groq = True
                self.use_openrouter = False
            except ImportError:
                logger.error("Groq library not found, falling back to Bedrock")
                self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
                self.use_groq = False
                self.use_openrouter = False
        else:
            logger.info(f"Using AWS Bedrock with model: {model_id}")
            self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
            self.use_groq = False
            self.use_openrouter = False
        
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
        
        for doc in docs:
            doc_type = doc.doc_type
            
            # Skip excluded document types
            if doc_type in SKIP_TYPES or self._is_excluded_document(doc.original_filename):
                logger.info(f"Skipping excluded document: {doc.original_filename}")
                continue
            
            # Choose chunking strategy
            if doc_type in LLM_CHUNK_TYPES:
                logger.info(f"LLM chunking for {doc.original_filename} (type: {doc_type}) using {'OpenRouter' if self.use_openrouter else 'Bedrock'}")
                chunks = self._llm_chunk_document(doc, tender_id, tender_ref, lot_map, default_lot_ref)
            else:
                logger.info(f"Standard chunking for {doc.original_filename} (type: {doc_type})")
                chunks = self._standard_chunk_document(doc, tender_id, default_lot_ref)
            
            all_chunks.extend(chunks)
        
        logger.info(f"Generated {len(all_chunks)} total chunks for tender {tender_id}")
        return all_chunks
    
    def _is_excluded_document(self, filename: str) -> bool:
        """Check if document should be excluded based on filename."""
        fname_lower = filename.lower()
        exclude_patterns = [
            'acte', 'engagement', 'declaration', 'honneur',
            'attestation', 'caution', 'cautionnement'
        ]
        return any(pattern in fname_lower for pattern in exclude_patterns)
    
    def _llm_chunk_document(self, doc: LogicalDocument, tender_id: int, tender_ref: str, lot_map: Dict[str, str], default_lot_ref: str) -> List[Dict[str, Any]]:
        """Use LLM to intelligently chunk the document. Handles large files by segmentation."""
        MAX_SEGMENT_CHARS = 40000 
        OVERLAP_CHARS = 1000
        
        content = doc.content
        segments = []
        
        # 1. Split content if too large
        if len(content) > MAX_SEGMENT_CHARS:
            start = 0
            while start < len(content):
                end = min(start + MAX_SEGMENT_CHARS, len(content))
                if end < len(content):
                    last_newline = content.rfind('\n', end - 2000, end)
                    if last_newline != -1:
                        end = last_newline + 1
                
                segments.append(content[start:end])
                
                if end >= len(content):
                    break
                start = end - OVERLAP_CHARS
        else:
            segments = [content]
            
        all_chunks = []
        type_counters = {} # Key: (lot_ref, type) -> int
        
        # 2. Process each segment
        for i, segment in enumerate(segments):
            logger.info(f"LLM Chunking: Processing segment {i+1}/{len(segments)} for {doc.original_filename} ({len(segment)} chars)")
            
            prompt = get_chunking_prompt(segment)
            
            try:
                if self.use_groq:
                    response = self._invoke_groq(prompt)
                elif self.use_openrouter:
                    response = self._invoke_openrouter(prompt)
                else:
                    response = self._invoke_nova(prompt)
                
                if not response or len(response) < 10:
                    logger.warning(f"Empty/Tiny response for segment {i+1} of {doc.original_filename}")
                    continue
                    
                seg_chunks, type_counters = self._parse_chunk_markers(
                    response, doc, tender_id, lot_map, default_lot_ref, type_counters
                )
                all_chunks.extend(seg_chunks)
                logger.info(f"Segment {i+1}: Parsed {len(seg_chunks)} chunks.")
                
            except Exception as e:
                logger.error(f"LLM chunking failed for segment {i+1} of {doc.original_filename}: {e}")
        
        # 3. Fallback
        if not all_chunks:
            logger.warning(f"No chunks parsed from any segment for {doc.original_filename}, falling back to standard")
            return self._standard_chunk_document(doc, tender_id, default_lot_ref)
            
        return all_chunks

    @retry(
        retry=retry_if_exception_type(Exception), # Catch generic exceptions for simple retry
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True
    )
    def _invoke_openrouter(self, prompt: str) -> str:
        """Invoke OpenRouter API.
        
        Args:
            prompt: The prompt to send to the model
            
        Returns:
            Model response text
        """
        # Limit prompt size if needed (e.g. 128k context is usually enough)
        # Qwen-2.5-32b has 128k context, no aggressive truncation needed usually
        # But let's keep it safe
        max_input_chars = 100000 
        if len(prompt) > max_input_chars:
            prompt = prompt[:max_input_chars] + "\n\n[Document truncated due to length...]"
        
        completion = self.openai_client.chat.completions.create(
            model=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.0,
            extra_body={
                "models": [
                    "meta-llama/llama-3.1-8b-instruct",
                    "mistralai/mistral-small-3.2-24b-instruct"
                ]
            }
        )
        
        return completion.choices[0].message.content
    
    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True
    )
    def _invoke_groq(self, prompt: str) -> str:
        """Invoke Groq API.
        
        Args:
            prompt: The prompt to send to the model
            
        Returns:
            Model response text
        """
        # Limit prompt size
        max_input_chars = 100000
        if len(prompt) > max_input_chars:
            prompt = prompt[:max_input_chars] + "\n\n[Document truncated due to length...]"
        
        completion = self.groq_client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=4000
        )
        
        return completion.choices[0].message.content

    @retry(
        retry=retry_if_exception_type(ClientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True
    )
    def _invoke_nova(self, prompt: str) -> str:
        """Invoke Amazon Nova model.
        
        Args:
            prompt: The prompt to send to the model
            
        Returns:
            Model response text
        """
        # Limit prompt size to stay within context window
        max_input_chars = 24000  # ~6000 tokens, leave room for response
        if len(prompt) > max_input_chars:
            prompt = prompt[:max_input_chars] + "\n\n[Document truncated due to length...]"
        
        # Nova uses the Converse API format
        body = json.dumps({
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ],
            "inferenceConfig": {
                "maxTokens": 4000,
                "temperature": 0.0,
                "topP": 0.9
            }
        })
        
        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType='application/json',
            accept='application/json',
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        
        # Nova response format
        if 'output' in response_body and 'message' in response_body['output']:
            content = response_body['output']['message'].get('content', [])
            if content and 'text' in content[0]:
                return content[0]['text']
        
        logger.error(f"Unexpected Nova response format: {response_body.keys()}")
        return ""
    
    def _parse_chunk_markers(self, response: str, doc: LogicalDocument, tender_id: int, 
                             lot_map: Dict[str, str], default_lot_ref: str, 
                             type_counters: Dict) -> tuple[List[Dict[str, Any]], Dict]:
        """Parse chunk markers and generate IDs: {lot_ref}_{type}_{increment}"""
        chunks = []
        
        # Matches: <!-- CHUNK:type:id attributes --> content <!-- /CHUNK -->
        pattern = r'<!-- CHUNK:(\w+):(\w+)(.*?) -->\s*(.*?)\s*<!-- /CHUNK -->'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        
        for i, (chunk_type, chunk_id, attributes_str, content) in enumerate(matches):
            content = content.strip()
            if not content or len(content) < 10: 
                continue
            
            # Parse attributes
            metadata = {
                "type": chunk_type, # Should be one of the 4 strict types match user req
                "tender_id": tender_id,
                "source_doc": doc.original_filename
            }
            
            # Extract attributes like lot="1", designation="...", etc.
            attr_pattern = r'(\w+)=["\']([^"\']+)["\']'
            attrs = re.findall(attr_pattern, attributes_str)
            for key, val in attrs:
                metadata[key] = val
            
            # Resolve Lot Reference
            # 1. Try metadata['lot'] (from LLM)
            lot_num_raw = metadata.get("lot")
            lot_ref = default_lot_ref # Default if not found
            
            if lot_num_raw:
                # Clean num "1"
                c_num = str(lot_num_raw).lower().replace("lot","").strip()
                if c_num in lot_map:
                    lot_ref = lot_map[c_num]
                else:
                    # Fallback if LLM found a lot number not in extraction map?
                    # Maybe construct it dynamically or fallback to default
                    # We will construct it dynamically using tender_ref of default
                    base_tender_ref = default_lot_ref.rsplit('_', 1)[0]
                    lot_ref = f"{base_tender_ref}_{c_num}"
            
            metadata['lot_reference'] = lot_ref
            
            # Generate ID: lot_ref_type_increment
            # Key for counter: (lot_ref, chunk_type)
            k = (lot_ref, chunk_type)
            if k not in type_counters:
                type_counters[k] = 1
            idx = type_counters[k]
            type_counters[k] += 1
            
            # ID Construction
            generated_id = f"{lot_ref}_{chunk_type}_{idx}"
            
            chunks.append({
                "id": generated_id,
                "content": content,
                "metadata": metadata
            })
        
        return chunks, type_counters
    
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
