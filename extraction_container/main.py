import os
import json
import time
import logging
import boto3
from botocore.exceptions import ClientError

from src.extraction import ExtractionService
from src.llm_chunker import LLMChunker
from src.cleaning import DocumentCleaners
from src.database import DatabaseManager
from src.integrity import IntegrityChecker, IntegrityCheckError
from src.metadata_aggregator import MetadataAggregator

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load env vars for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Config
SQS_QUEUE_URL = os.environ.get('EXTRACTION_QUEUE_URL')
# New Queue for DB Filler
DB_FILLER_QUEUE_URL = os.environ.get('DB_FILLER_QUEUE_URL', 'db_filler') # Fallback name if env not set
# Keep vector queue if needed, but user request emphasized db_filler. 
# Assuming this replaces the old NEXT_QUEUE_URL or adds to it. 
# The request said "when finishe the container shoul put message to a new queue name it db_filler"
NEXT_QUEUE_URL = os.environ.get('VECTOR_QUEUE_URL') 

S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
DB_URL = os.environ.get('DB_URL')
BEDROCK_MODEL = os.environ.get('BEDROCK_MODEL_ID', 'qwen/qwen3-235b-a22b-2507')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

def main():
    if not all([SQS_QUEUE_URL, S3_BUCKET]):
        missing = []
        if not SQS_QUEUE_URL: missing.append("EXTRACTION_QUEUE_URL")
        if not S3_BUCKET: missing.append("S3_BUCKET_NAME")
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        return

    sqs = boto3.client('sqs', region_name=AWS_REGION)
    s3 = boto3.client('s3', region_name=AWS_REGION)

    chunker = LLMChunker(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    aggregator = MetadataAggregator(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)

    logger.info(f"Starting Extraction Service polling {SQS_QUEUE_URL}...")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )

            if 'Messages' not in response:
                continue

            for msg in response['Messages']:
                handle_message(msg, sqs, s3, chunker, aggregator)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

def handle_message(msg, sqs, s3, chunker, aggregator):
    receipt_handle = msg['ReceiptHandle']
    try:
        body = json.loads(msg['Body'])
        tender_ref = body.get('tender_ref')
        tender_id = body.get('tender_id')
        
        # Support both formats: markdown_key (string) or markdown_paths (array)
        markdown_key = body.get('markdown_key')
        markdown_paths = body.get('markdown_paths', [])
        
        if not tender_ref or (not markdown_key and not markdown_paths):
            logger.error(f"Missing required fields in message: {body}")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return
        
        # Lookup tender_id if not provided (READ ONLY)
        if not tender_id and DB_URL:
            try:
                db_manager = DatabaseManager(DB_URL)
                tender_id = db_manager.get_tender_id_by_reference(tender_ref)
            except Exception as e:
                logger.warning(f"Could not look up tender_id from DB: {e}")
                tender_id = 0 # Default if DB not accessible
        
        if not tender_id:
            tender_id = 0 
            
        logger.info(f"Processing {tender_ref} (ID: {tender_id})...")

        # 1. Download Markdown - support single key or multiple paths
        if markdown_key:
            # Single file format
            obj = s3.get_object(Bucket=S3_BUCKET, Key=markdown_key)
            full_markdown = obj['Body'].read().decode('utf-8')
        else:
            # Multiple files format - download and concatenate
            markdown_parts = []
            for md_path in markdown_paths:
                logger.info(f"Downloading markdown: {md_path}")
                obj = s3.get_object(Bucket=S3_BUCKET, Key=md_path)
                content = obj['Body'].read().decode('utf-8')
                markdown_parts.append(content)
            full_markdown = "\n\n---\n\n".join(markdown_parts)

        logger.info(f"Downloaded markdown: {len(full_markdown):,} characters")

        # 2. Split Markdown into logical documents
        cleaner = DocumentCleaners()
        docs = cleaner.split_concatenated_file(full_markdown)
        logger.info(f"Split into {len(docs)} documents: {[d.doc_type for d in docs]}")
        
        # 3. LLM-assisted chunking (FIRST - with enriched metadata)
        # Pass empty lots=[] since we don't have metadata yet - will be inferred from chunks
        chunks = chunker.chunk_all_documents(
            docs=docs, 
            tender_id=tender_id, 
            tender_ref=tender_ref,
            lots=[]  # No lots available yet - will be inferred from content
        )
        logger.info(f"Generated {len(chunks)} chunks from documents")
        
        # 4. Upload Chunks to S3 (BEFORE metadata)
        chunk_key = f"chunks_tender/{tender_ref}/chunks.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=chunk_key,
            Body=json.dumps(chunks, ensure_ascii=False)
        )
        logger.info(f"Saved chunks to {chunk_key}")
        
        # 5. Aggregate Metadata from Chunks (NEW - chunk-first approach)
        extraction_output = aggregator.aggregate_metadata(chunks, tender_ref, tender_id)
        logger.info(f"Aggregated metadata: {len(extraction_output.lots)} lots, {len(extraction_output.products)} products")
        
        # 6. Save Metadata to S3 (AFTER chunks)
        # Sanitize tender_ref to avoid creating nested folders from "/" characters
        sanitized_ref = tender_ref.replace("/", "_")
        metadata_key = f"tender_metadata/{sanitized_ref}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=extraction_output.model_dump_json()
        )
        logger.info(f"Saved metadata to {metadata_key}")

        # 7. Integrity Check
        logger.info("Performing output integrity checks...")
        meta_valid = IntegrityChecker.check_metadata(extraction_output)
        chunks_valid = IntegrityChecker.check_chunks(chunks)
        
        if not meta_valid or not chunks_valid:
            logger.error(f"Integrity Check FAILED (Meta: {meta_valid}, Chunks: {chunks_valid}). rolling back S3 uploads.")
            # Rollback: Delete the uploaded artifacts to prevent bad data
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=metadata_key)
                s3.delete_object(Bucket=S3_BUCKET, Key=chunk_key)
                logger.info("Rollback successful: Deleted invalid S3 artifacts.")
            except Exception as cleanup_error:
                logger.error(f"Rollback failed: {cleanup_error}")
            
            # Raise exception to trigger SQS retry (visibility timeout will put it back in queue)
            # We specifically use a custom error to distinguish in logs
            raise IntegrityCheckError(f"Validation failed for {tender_ref}. Metadata: {meta_valid}, Chunks: {chunks_valid}")
            
        logger.info("Integrity Check PASSED.")

        # 8. Notify DB Filler Queue
        # We need to construct the URL for db_filler if it's just a name
        queue_url = DB_FILLER_QUEUE_URL
        if not queue_url.startswith("https://"):
            # Assume it's a queue name, try to get URL
            try:
                q_response = sqs.get_queue_url(QueueName=DB_FILLER_QUEUE_URL)
                queue_url = q_response['QueueUrl']
            except ClientError as e:
                logger.error(f"Could not get URL for queue {DB_FILLER_QUEUE_URL}: {e}")
                # Fallback: maybe it IS a URL or we can't send
                pass
        
        logger.info(f"Sending completion message to {queue_url}")
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "tender_ref": tender_ref,
                "tender_id": tender_id,
                "metadata_key": metadata_key,
                "chunks_key": chunk_key,
                "status": "extraction_complete"
            })
        )

        # 9. Delete Message
        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
        logger.info(f"Successfully processed {tender_ref}")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        # Don't delete message, let visibility timeout handle retry

if __name__ == "__main__":
    main()
