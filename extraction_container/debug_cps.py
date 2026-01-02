import os
import logging
import boto3
from dotenv import load_dotenv
from src.cleaning import DocumentCleaners
from src.llm_chunker import LLMChunker

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
load_dotenv()
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
BEDROCK_MODEL = "qwen/qwen-2.5-72b-instruct"
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

def run_debug():
    # 1. Download Markdown
    s3 = boto3.client('s3', region_name=AWS_REGION)
    bucket = "my-tender-documents-bucket"
    key = "markdown_tender/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL_ocr.md"
    
    logger.info(f"Downloading {key}...")
    obj = s3.get_object(Bucket=bucket, Key=key)
    full_markdown = obj['Body'].read().decode('utf-8')
    
    # 2. Split Documents
    logger.info("Splitting documents...")
    docs = DocumentCleaners.split_concatenated_file(full_markdown)
    
    # 3. Find CPS
    cps_doc = None
    for doc in docs:
        if 'cps' in doc.original_filename.lower() or doc.doc_type == 'specification':
            cps_doc = doc
            break
            
    if not cps_doc:
        logger.error("CPS document not found in split!")
        return

    logger.info(f"Found CPS: {cps_doc.original_filename} (Length: {len(cps_doc.content)} chars)")
    
    # 4. Invoke LLM Chunker
    chunker = LLMChunker(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    
    # Invoke
    logger.info(f"Invoking LLM Chunker for CPS (Segmented)...")
    try:
        chunks = chunker._llm_chunk_document(cps_doc, 9999)
        logger.info(f"Total Chunks Parsed: {len(chunks)}")
        # Print sample chunk
        if chunks:
            logger.info(f"Sample Chunk 0 ID: {chunks[0]['id']}")
            logger.info(f"Sample Chunk 0 Metadata: {chunks[0]['metadata']}")
    except Exception as e:
        logger.error(f"Error during chunking: {e}")

if __name__ == "__main__":
    run_debug()
