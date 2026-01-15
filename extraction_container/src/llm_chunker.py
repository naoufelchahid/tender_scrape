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
        
        # Check if using OpenRouter
        self.use_openrouter = "qwen" in model_id.lower() or "deepseek" in model_id.lower() or "openrouter" in model_id.lower() or openrouter_api_key
        
        if self.use_openrouter:
            if not OpenAI:
                raise ImportError("OpenAI library required for OpenRouter. Install with `pip install openai`")
            if not openrouter_api_key:
                logger.warning("OpenRouter usage detected but no API key provided. Falling back to Bedrock or likely failure.")
            
            logger.info(f"Using OpenRouter with model: {model_id}")
            self.openai_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"),
                default_headers={
                    "HTTP-Referer": "https://localhost:3000",
                    "X-Title": "Tender Extraction Service"
                }
            )
        else:
            logger.info(f"Using OPEN_ROUTER with model: {model_id}")
            self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
        
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
        """
        Use LLM to intelligently chunk the document. Leverages 1M token context windows.
        
        Strategy:
        - Documents < 3M chars: Single batch (full context)
        - Documents >= 3M chars: Split into 2 batches
        """
        MAX_SINGLE_BATCH_CHARS = 3000000  # ~750K tokens (4:1 char:token ratio)
        
        content = doc.content
        content_length = len(content)
        segments = []
        
        # 1. Determine batching strategy based on document size
        if content_length <= MAX_SINGLE_BATCH_CHARS:
            # Single batch - send full document as context
            segments = [content]
            logger.info(f"LLM Chunking: Processing {doc.original_filename} as single batch ({content_length:,} chars)")
        else:
            # Large document - split into 2 batches with overlap
            logger.info(f"LLM Chunking: Document {doc.original_filename} is large ({content_length:,} chars), splitting into 2 batches")
            
            # Calculate split point at approximately 50% with smart boundary detection
            split_point = content_length // 2
            overlap_chars = 5000  # Larger overlap for continuity
            
            # Find a good split boundary (prefer paragraph/section breaks)
            search_window = 10000
            best_split = split_point
            
            # Look for natural boundaries: double newline, article markers, page breaks
            search_start = max(0, split_point - search_window)
            search_end = min(content_length, split_point + search_window)
            search_region = content[search_start:search_end]
            
            # Priority 1: Look for article/section markers
            article_patterns = [r'\n\s*ARTICLE\s+\d+', r'\n\s*Article\s+\d+', r'\n\s*CHAPITRE\s+\d+']
            for pattern in article_patterns:
                matches = list(re.finditer(pattern, search_region, re.IGNORECASE))
                if matches:
                    # Find match closest to midpoint
                    midpoint_offset = split_point - search_start
                    closest_match = min(matches, key=lambda m: abs(m.start() - midpoint_offset))
                    best_split = search_start + closest_match.start()
                    logger.info(f"Found article boundary for split at position {best_split:,}")
                    break
            else:
                # Priority 2: Look for paragraph breaks (double newlines)
                paragraph_breaks = [m.start() for m in re.finditer(r'\n\s*\n', search_region)]
                if paragraph_breaks:
                    midpoint_offset = split_point - search_start
                    closest_break = min(paragraph_breaks, key=lambda pos: abs(pos - midpoint_offset))
                    best_split = search_start + closest_break
                    logger.info(f"Found paragraph boundary for split at position {best_split:,}")
                else:
                    # Priority 3: Find any newline
                    newline_pos = content.rfind('\n', split_point - search_window, split_point + search_window)
                    if newline_pos != -1:
                        best_split = newline_pos + 1
            
            # Create two batches with overlap
            batch1 = content[:best_split + overlap_chars]
            batch2 = content[max(0, best_split - overlap_chars):]
            
            segments = [batch1, batch2]
            logger.info(f"Batch 1: {len(batch1):,} chars | Batch 2: {len(batch2):,} chars")
            
        all_chunks = []
        type_counters = {}  # Key: (lot_ref, type) -> int
        
        # 2. Process each batch
        for i, segment in enumerate(segments):
            batch_num = i + 1
            total_batches = len(segments)
            
            logger.info(f"LLM Chunking: Processing batch {batch_num}/{total_batches} for {doc.original_filename} ({len(segment):,} chars)")
            
            prompt = self._get_prompt_for_type(doc.doc_type, segment)
            
            try:
                if self.use_openrouter:
                    response = self._invoke_openrouter(prompt)
                else:
                    response = self._invoke_nova(prompt)
                
                if not response or len(response) < 10:
                    logger.warning(f"Empty/Tiny response for batch {batch_num} of {doc.original_filename}")
                    continue
                    
                seg_chunks, type_counters = self._parse_chunk_markers(
                    response, doc, tender_id, lot_map, default_lot_ref, type_counters
                )
                all_chunks.extend(seg_chunks)
                logger.info(f"Batch {batch_num}: Parsed {len(seg_chunks)} chunks.")
                
            except Exception as e:
                logger.error(f"LLM chunking failed for batch {batch_num} of {doc.original_filename}: {e}", exc_info=True)
        
        # 3. Fallback
        if not all_chunks:
            logger.warning(f"No chunks parsed from any batch for {doc.original_filename}, falling back to standard chunking")
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
        # With 1M token context window, we can handle ~3M chars (conservative 3:1 ratio)
        # The actual model context is larger, but we leave room for response
        max_input_chars = 3000000
        
        if len(prompt) > max_input_chars:
            logger.warning(f"Prompt length {len(prompt):,} exceeds max {max_input_chars:,}, truncating")
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
    
    def _get_prompt_for_type(self, doc_type: str, content: str) -> str:
        """Get the specialized prompt for a document type.
        
        Args:
            doc_type: Type of document (product, specification, administrative, avis)
            content: Document content to analyze
            
        Returns:
            Complete prompt string
        """
        prompts = {
            'product': self._get_bdp_prompt(content),
            'specification': self._get_cps_prompt(content),
            'administrative': self._get_rc_prompt(content),
            'avis': self._get_avis_prompt(content)
        }
        
        return prompts.get(doc_type, self._get_generic_prompt(content))
    
    def _get_bdp_prompt(self, content: str) -> str:
        """Prompt for BDP (Bill of Quantities / Bordereau des Prix) documents."""
        return f"""You are a document analyzer for Moroccan tender BDP (Bill of Quantities / Bordereau des Prix) documents.

TASK: Identify each INDIVIDUAL product/item row in the pricing table and mark chunk boundaries.

CRITICAL RULES:
1. STRICT separation: One chunk = ONE product item. NEVER merge multiple unrelated items into a single chunk.
2. If the table lists Item 1, Item 2, Item 3 -> You must create 3 separate chunks.
3. Preserve multi-line descriptions: If a single item's description spans multiple lines, keep it all in that item's chunk.
4. Include: item number, designation, quantity, unit, and all technical specifications.
5. Skip header rows, page totals, and subtotals.
6. MANDATORY: Identify the Lot Number this item belongs to. If implicit, look at previous pages or headers.

OUTPUT FORMAT - Insert these markers around each product. Add 'lot' attribute if known:
<!-- CHUNK:products:item_NUMBER lot="LOT_NUMBER" designation="..." quantity="..." unit="..." -->
[complete product row content]
<!-- /CHUNK -->

EXAMPLE:
<!-- CHUNK:products:item_1 lot="1" designation="Ordinateur Portable" quantity="5" unit="U" -->
| 1 | Ordinateur Portable | i7, 16GB RAM | 5 | U |
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_cps_prompt(self, content: str) -> str:
        """Prompt for CPS (Cahier des Prescriptions Spéciales) documents."""
        return f"""You are a document analyzer for Moroccan tender CPS (Cahier des Prescriptions Spéciales) documents.

TASK: Identify logical sections (Articles, Chapters) AND embedded pricing tables (Bordereau des Prix).

CLASSIFICATION TYPES:
- 'specification': Technical specifications specific to materials/products.
- 'products': If a pricing table (BDP) is found embedded here.

CRITICAL RULES FOR TEXT SECTIONS:
1. Each ARTICLE = ONE separate chunk (e.g., Article 1, Article 2...).
2. STRICT PROHIBITION: NEVER merge multiple articles into a single chunk. Even short articles must be separate.
3. Marker format: <!-- CHUNK:specification:ARTICLE_NUMBER type="specification" -->
4. Keep the article header exactly as is with its content.
5. If an article has sub-points, keep them logically within that article's chunk.

CRITICAL RULES FOR PRICING TABLES (BDP) - IF PRESENT:
1. If you encounter a list of products/prices, switch to PRODUCT mode via 'products' type.
2. STRICT SEPARATION: One product row = ONE chunk. NEVER merge rows.
3. Marker format: <!-- CHUNK:products:item_NUMBER lot="LOT_NUMBER" -->

OUTPUT FORMATS:

For Articles:
<!-- CHUNK:specification:Art_5 type="specification" -->
[article content]
<!-- /CHUNK -->

For Products (if table found):
<!-- CHUNK:products:item_1 lot="4" -->
| 1 | Laptop HP | i5, 8GB | 5 | U |
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_rc_prompt(self, content: str) -> str:
        """Prompt for RC (Règlement de Consultation) documents."""
        return f"""You are a document analyzer for Moroccan tender RC (Règlement de Consultation) documents.

TASK: Identify administrative sections, eligibility criteria, and Articles.

CLASSIFICATION TYPE: 'administrative'

CRITICAL RULES:
1. Each ARTICLE or discrete SECTION = ONE separate chunk.
2. STRICT PROHIBITION: NEVER merge multiple articles into a single chunk.
3. Marker format: <!-- CHUNK:administrative:SECTION_NAME type="administrative" -->
4. Example: <!-- CHUNK:administrative:Article_1_Objet type="administrative" -->

OUTPUT FORMAT:
<!-- CHUNK:administrative:Article_1 type="administrative" -->
[content of Article 1]
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_avis_prompt(self, content: str) -> str:
        """Prompt for Avis (Tender Notice) documents."""
        return f"""You are a document analyzer for Moroccan tender Avis (Tender Notice) documents.

TASK: Extract key information and create a single summary chunk.

OUTPUT FORMAT:
<!-- CHUNK:avis:summary type="avis" -->
[complete tender notice summary]
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_generic_prompt(self, content: str) -> str:
        """Generic prompt for unknown document types."""
        return f"""Analyze this document and identify distinct logical sections.

CRITICAL:
1. Split distinct chapters or sections into separate chunks.
2. Marker format: <!-- CHUNK:section:SECTION_ID type="general" -->

OUTPUT FORMAT:
<!-- CHUNK:section:Introduction type="general" -->
[section content]
<!-- /CHUNK -->

DOCUMENT:

{content}"""

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
