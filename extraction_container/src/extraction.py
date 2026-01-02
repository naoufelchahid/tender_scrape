import os
import json
import logging
from typing import List, Dict, Any, Optional
import boto3
from langchain_aws import ChatBedrock
# Optional import for OpenAI/OpenRouter
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    try:
        from langchain_community.chat_models import ChatOpenAI
    except ImportError:
        ChatOpenAI = None

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from botocore.exceptions import ClientError

from src.models import ExtractionOutput, TenderMetadata, LotMetadata, ProductItem, ProductList
from src.cleaning import DocumentCleaners
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self, region_name: str, model_id: str, openrouter_api_key: str = None):
        self.use_openrouter = "qwen" in model_id.lower() or "deepseek" in model_id.lower() or "openrouter" in model_id.lower() or openrouter_api_key
        
        if self.use_openrouter:
            if not ChatOpenAI:
                raise ImportError("langchain-openai required for OpenRouter")
            
            logger.info(f"Using OpenRouter (ChatOpenAI) with model: {model_id}")
            self.llm = ChatOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"),
                model=model_id,
                temperature=0.0
            )
        else:
            logger.info(f"Using AWS Bedrock with model: {model_id}")
            self.llm = ChatBedrock(
                client=boto3.client("bedrock-runtime", region_name=region_name),
                model_id=model_id,
                model_kwargs={"temperature": 0.0}
            )
        
        # Parsers
        self.meta_parser = PydanticOutputParser(pydantic_object=ExtractionOutput)
        self.product_parser = PydanticOutputParser(pydantic_object=ProductList)

    def process_tender(self, tender_id: int, tender_ref: str, full_markdown: str) -> ExtractionOutput:
        """Main orchestration method. Returns extraction result instead of DB write."""
        
        # 1. Split & Classify
        cleaner = DocumentCleaners()
        docs = cleaner.split_concatenated_file(full_markdown)
        
        # 2. Identify Metadata Sources (Avis, RC, Engagement)
        meta_context = ""
        for d in docs:
            if d.doc_type in ['avis', 'administrative', 'engagement']:
                # Limit context size per doc to avoid token overflow
                meta_context += f"\n--- Document: {d.original_filename} ---\n{d.content[:50000]}"
        
        # 3. Extract Metadata (Tender + Lots)
        extraction_result = None
        if not meta_context.strip():
            logger.warning(f"No metadata context found for {tender_ref}. Proceeding with clean object.")
            extraction_result = ExtractionOutput(
                tender_info=TenderMetadata(),
                lots=[],
                products=[]
            )
        else:
            logger.info(f"Extracting metadata for Tender {tender_ref}")
            try:
                extraction_result = self._extract_metadata_llm(meta_context)
            except Exception as e:
                logger.error(f"Metadata extraction failed after retries: {e}. Proceeding with clean object.")
                extraction_result = ExtractionOutput(
                    tender_info=TenderMetadata(),
                    lots=[],
                    products=[]
                )
        
        if extraction_result is None:
             extraction_result = ExtractionOutput(
                tender_info=TenderMetadata(),
                lots=[],
                products=[]
            )

        if extraction_result:
            info = extraction_result.tender_info
            # Format Tender Reference: Ref_Initials
            if info.tender_reference and info.buyer_initials:
                 # Sanitize inputs
                ref_clean = info.tender_reference.strip().replace(" ", "")
                initials_clean = info.buyer_initials.strip().upper().replace(" ", "")
                info.tender_reference = f"{ref_clean}_{initials_clean}"
            
            # Fallback: if no extracted reference, use the filename ref (passed as arg)
            if not info.tender_reference:
                 info.tender_reference = tender_ref

        # 4. Extract Products (BDP sources)
        all_products = []
        for d in docs:
            if d.doc_type == 'product':
                logger.info(f"Extracting products from {d.original_filename}")
                products = self._extract_products_llm(d.content)
                if products:
                    all_products.extend(products)
        
        extraction_result.products = all_products
        
        # Post-process: Ensure lot_reference is populated
        if extraction_result and extraction_result.lots:
            for lot in extraction_result.lots:
                if not lot.lot_reference:
                    # Fallback: Create simplified reference
                    lot.lot_reference = f"{tender_ref}-{lot.lot_number}"
        
        return extraction_result
                    
    @retry(
        retry=retry_if_exception_type(ClientError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=True
    )
    def _extract_metadata_llm(self, text: str) -> ExtractionOutput:
        """Extracts Tender Info and Lots definition with retry logic."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert in Moroccan Tender Documents analysis. Extract structured data."),
            ("user", "Analyze the following tender documents and extract:\n"
                     "1. Global Tender Info:\n"
                     "   - Tender Reference (if mentioned)\n"
                     "   - Buyer Name (MANDATORY)\n"
                     "   - Buyer Initials (e.g. OCP, ANP - if mentioned or inferable)\n"
                     "   - Buyer Details (Address, Phone, Email, Contact Person - if mentioned)\n"
                     "   - Publication Date\n"
                     "   - Submission Deadline\n"
                     "   - Passation Mode (e.g. AO Ouvert)\n"
                     "   - Type/Domain (formerly Category)\n"
                     "   - Global Budget & Agrements\n"
                     "2. List of Lots (Number, Title, Budget, etc.).\n"
                     "   - For each lot, construct 'lot_reference' by combining Tender Ref + Lot Number (e.g. '12/2025-1').\n"
                     "Ignore product tables for now, focus on metadata and Lots.\n\n"
                     "{format_instructions}\n\n"
                     "Context:\n{context}")
        ])
        
        chain = prompt | self.llm | self.meta_parser
        try:
            return chain.invoke({
                "context": text,
                "format_instructions": self.meta_parser.get_format_instructions()
            })
        except Exception as e:
            logger.error(f"Metadata extraction failed: {e}")
            raise e

    @retry(
        retry=retry_if_exception_type(ClientError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=True
    )
    def _extract_products_llm(self, text: str) -> List[ProductItem]:
        """Extracts Bill of Quantities (Bordereau des Prix) items with retry logic."""
        if not text.strip():
            return []
            
        # Using a specialized prompt for Tables
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a data extraction engine targeted at extracting 'Bordereau des Prix' tables."),
            ("user", "Extract all line items from the pricing table in the text.\n"
                     "- STRICT RULE: Create ONE JSON object for EACH row in the table.\n"
                     "- Capture fields: 'designation', 'unit', 'quantity', 'estimated_price'.\n"
                     "- Ensure 'lot_number' is inferred.\n"
                     "- Ignore headers and subtotals.\n"
                     "Return a JSON object with a 'products' array containing the items.\n"
                     "{format_instructions}\n\n"
                     "Text:\n{context}")
        ])
        
        chain = prompt | self.llm | self.product_parser
        try:
            result = chain.invoke({
                "context": text[:50000], # Limit check
                "format_instructions": self.product_parser.get_format_instructions()
            })
            return result.products if result else []
        except Exception as e:
            logger.error(f"Product extraction failed: {e}")
            return []
