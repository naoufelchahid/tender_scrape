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
            logger.info(f"Using AWS Bedrock with model: {model_id}")
            self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
        
        # Standard text splitter for fallback/other documents
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE * 4,  # chars approx
            chunk_overlap=STANDARD_CHUNK_OVERLAP * 4,
            separators=["\n\n", "\n", ". ", " "]
        )
    
    def chunk_all_documents(self, docs: List[LogicalDocument], tender_id: int) -> List[Dict[str, Any]]:
        """Process all documents and generate chunks.
        
        Args:
            docs: List of LogicalDocument objects
            tender_id: Database ID of the tender
            
        Returns:
            List of chunk dictionaries with id, content, metadata
        """
        all_chunks = []
        
        for doc in docs:
            doc_type = doc.doc_type
            
            # Skip excluded document types
            if doc_type in SKIP_TYPES or self._is_excluded_document(doc.original_filename):
                logger.info(f"Skipping excluded document: {doc.original_filename}")
                continue
            
            # Choose chunking strategy
            if doc_type in LLM_CHUNK_TYPES:
                logger.info(f"LLM chunking for {doc.original_filename} (type: {doc_type}) using {'OpenRouter' if self.use_openrouter else 'Bedrock'}")
                chunks = self._llm_chunk_document(doc, tender_id)
            else:
                logger.info(f"Standard chunking for {doc.original_filename} (type: {doc_type})")
                chunks = self._standard_chunk_document(doc, tender_id)
            
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
    
    def _llm_chunk_document(self, doc: LogicalDocument, tender_id: int) -> List[Dict[str, Any]]:
        """Use LLM to intelligently chunk the document. Handles large files by segmentation."""
        MAX_SEGMENT_CHARS = 40000  # Conservative limit for 32k context (~10-12k tokens + resp)
        OVERLAP_CHARS = 1000
        
        content = doc.content
        segments = []
        
        # 1. Split content if too large
        if len(content) > MAX_SEGMENT_CHARS:
            start = 0
            while start < len(content):
                end = min(start + MAX_SEGMENT_CHARS, len(content))
                # Attempt to split at a newline near the end
                if end < len(content):
                    last_newline = content.rfind('\n', end - 2000, end)
                    if last_newline != -1:
                        end = last_newline + 1
                
                segments.append(content[start:end])
                
                # Move start forward, ensuring overlap unless we hit end
                if end >= len(content):
                    break
                start = end - OVERLAP_CHARS
        else:
            segments = [content]
            
        all_chunks = []
        
        # 2. Process each segment
        for i, segment in enumerate(segments):
            logger.info(f"LLM Chunking: Processing segment {i+1}/{len(segments)} for {doc.original_filename} ({len(segment)} chars)")
            
            prompt = self._get_prompt_for_type(doc.doc_type, segment)
            
            try:
                if self.use_openrouter:
                    response = self._invoke_openrouter(prompt)
                else:
                    response = self._invoke_nova(prompt)
                
                if not response or len(response) < 10:
                    logger.warning(f"Empty/Tiny response for segment {i+1} of {doc.original_filename}")
                    continue
                    
                seg_chunks = self._parse_chunk_markers(response, doc, tender_id)
                all_chunks.extend(seg_chunks)
                logger.info(f"Segment {i+1}: Parsed {len(seg_chunks)} chunks.")
                
            except Exception as e:
                logger.error(f"LLM chunking failed for segment {i+1} of {doc.original_filename}: {e}")
                # Continue to next segment instead of total failure
        
        # 3. Fallback only if NO chunks were generated at all
        if not all_chunks:
            logger.warning(f"No chunks parsed from any segment for {doc.original_filename}, falling back to standard")
            return self._standard_chunk_document(doc, tender_id)
            
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
            # max_tokens=4000 # Optional
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
<!-- CHUNK:product:item_NUMBER lot="LOT_NUMBER" -->
[complete product row content]
<!-- /CHUNK -->

EXAMPLE:
<!-- CHUNK:product:item_1 lot="1" -->
| 1 | Ordinateur Portable | i7, 16GB RAM | 5 | U |
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_cps_prompt(self, content: str) -> str:
        """Prompt for CPS (Cahier des Prescriptions Spéciales) documents."""
        return f"""You are a document analyzer for Moroccan tender CPS (Cahier des Prescriptions Spéciales) documents.

TASK: Identify logical sections (Articles, Chapters) AND embedded pricing tables (Bordereau des Prix).

CRITICAL RULES FOR TEXT SECTIONS:
1. Each ARTICLE = ONE separate chunk (e.g., Article 1, Article 2...).
2. STRICT PROHIBITION: NEVER merge multiple articles into a single chunk. Even short articles must be separate.
3. Marker format: <!-- CHUNK:article:ARTICLE_NUMBER type="clause" -->
4. Keep the article header exactly as is with its content.
5. If an article has sub-points, keep them logically within that article's chunk.

CRITICAL RULES FOR PRICING TABLES (BDP) - IF PRESENT:
1. If you encounter a list of products/prices, switch to PRODUCT mode.
2. STRICT SEPARATION: One product row = ONE chunk. NEVER merge rows.
3. Marker format: <!-- CHUNK:product:item_NUMBER lot="LOT_NUMBER" -->

OUTPUT FORMATS:

For Articles:
<!-- CHUNK:article:5 type="clause" -->
[article content]
<!-- /CHUNK -->

For Products (if table found):
<!-- CHUNK:product:item_1 lot="4" -->
| 1 | Laptop HP | i5, 8GB | 5 | U |
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_rc_prompt(self, content: str) -> str:
        """Prompt for RC (Règlement de Consultation) documents."""
        return f"""You are a document analyzer for Moroccan tender RC (Règlement de Consultation) documents.

TASK: Identify administrative sections, eligibility criteria, and Articles.

CRITICAL RULES:
1. Each ARTICLE or discrete SECTION = ONE separate chunk.
2. STRICT PROHIBITION: NEVER merge multiple articles into a single chunk.
3. Marker format: <!-- CHUNK:admin:SECTION_NAME type="admin_rule" -->
4. Example: <!-- CHUNK:admin:Article_1_Objet type="admin_rule" -->

OUTPUT FORMAT:
<!-- CHUNK:admin:Article_1 type="admin_rule" -->
[content of Article 1]
<!-- /CHUNK -->

NOW PROCESS THIS DOCUMENT:

{content}"""

    def _get_avis_prompt(self, content: str) -> str:
        """Prompt for Avis (Tender Notice) documents."""
        return f"""You are a document analyzer for Moroccan tender Avis (Tender Notice) documents.

TASK: Extract key information and create a single summary chunk.

OUTPUT FORMAT:
<!-- CHUNK:notice:summary type="tender_summary" -->
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

    def _parse_chunk_markers(self, response: str, doc: LogicalDocument, tender_id: int) -> List[Dict[str, Any]]:
        """Parse chunk markers from LLM response.
        
        Args:
            response: LLM response with chunk markers
            doc: Source document
            tender_id: Database ID of the tender
            
        Returns:
            List of parsed chunks
        """
        chunks = []
        
        # Pattern to match chunk markers with optional attributes
        # Matches: <!-- CHUNK:type:id attributes --> content <!-- /CHUNK -->
        pattern = r'<!-- CHUNK:(\w+):(\w+)(.*?) -->\s*(.*?)\s*<!-- /CHUNK -->'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        
        for i, (chunk_type, chunk_id, attributes_str, content) in enumerate(matches):
            content = content.strip()
            if not content or len(content) < 20:  # Skip tiny chunks
                continue
            
            # Parse attributes (e.g., lot="1" type="clause")
            metadata = {
                "type": chunk_type,
                "tender_id": tender_id,
                "source_doc": doc.original_filename,
                "chunk_id": chunk_id,
                "generated_id": f"{chunk_type}_{tender_id}_{chunk_id}_{i}"
            }
            
            # Extract simple key="value" attributes
            attr_pattern = r'(\w+)=["\']([^"\']+)["\']'
            attrs = re.findall(attr_pattern, attributes_str)
            for key, val in attrs:
                metadata[key] = val
            
            # Fallback for lot extraction if not in attributes
            if "lot" not in metadata and "lot_ids" not in metadata:
                 metadata["lot_ids"] = self._extract_lot_from_content(content)
            elif "lot" in metadata:
                 metadata["lot_ids"] = metadata["lot"] # standardized key

            chunks.append({
                "id": metadata["generated_id"],
                "content": content,
                "metadata": metadata
            })
        
        return chunks
    
    def _extract_lot_from_content(self, content: str) -> str:
        """Extract lot identifier from chunk content."""
        lot_match = re.search(r'lot\s*[:\s]*(\d+)', content, re.IGNORECASE)
        if lot_match:
            return lot_match.group(1)
        return "ALL"
    
    def _standard_chunk_document(self, doc: LogicalDocument, tender_id: int) -> List[Dict[str, Any]]:
        """Apply standard text splitting for non-LLM documents.
        
        Args:
            doc: LogicalDocument to chunk
            tender_id: Database ID of the tender
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        text_chunks = self.text_splitter.split_text(doc.content)
        
        for i, chunk_text in enumerate(text_chunks):
            if len(chunk_text.strip()) < 50:  # Skip very small chunks
                continue
                
            chunks.append({
                "id": f"doc_{tender_id}_{doc.doc_type}_{i}",
                "content": chunk_text.strip(),
                "metadata": {
                    "type": doc.doc_type,
                    "tender_id": tender_id,
                    "source_doc": doc.original_filename,
                    "lot_ids": "ALL"
                }
            })
        
        return chunks
