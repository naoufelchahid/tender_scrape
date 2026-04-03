import os
import json
import time
import logging
import boto3
import asyncio
from botocore.exceptions import ClientError
from pydantic import ValidationError


from src.document_chunker import DocumentChunker
from src.cleaning import DocumentCleaners
from src.database import DatabaseManager

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
KB_INGESTION_QUEUE_URL= os.environ.get('KB_INGESTION_QUEUE_URL')
S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
DB_URL = os.environ.get('DB_URL')
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

    chunker = DocumentChunker(AWS_REGION, OPENROUTER_API_KEY)

    logger.info(f"Starting Extraction Service polling {SQS_QUEUE_URL}...")

    while True:
        logger.info(f"Loop start: polling {SQS_QUEUE_URL}...")
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )

            if 'Messages' not in response:
                logger.info("No messages found in this poll.")
                continue

            for msg in response['Messages']:
                handle_message(msg, sqs, s3, chunker)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

def handle_message(msg, sqs, s3, chunker):
    receipt_handle = msg['ReceiptHandle']
    body_str = msg['Body']
    try:
        # Try JSON loading first
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            # Fallback: check if it's a plain S3 URI string
            if body_str.startswith('s3://'):
                # Extract tender_ref from path: s3://bucket/markdown_tender/REF/file.md
                # We assume the standard structure markdown_tender/{tender_ref}/...
                parts = body_str.replace('s3://', '').split('/')
                # parts[0] is bucket, parts[1] is markdown_tender
                if len(parts) >= 4 and parts[1] == 'markdown_tender':
                    tender_ref = parts[2]
                else:
                    # Last ditch effort: use the filename without extension as ref
                    tender_ref = os.path.splitext(os.path.basename(body_str))[0]
                
                body = {
                    'markdown_key': body_str.split(f"{S3_BUCKET}/")[-1] if f"{S3_BUCKET}/" in body_str else body_str,
                    'tender_ref': tender_ref
                }
                # If the key still has s3:// or bucket name, clean it
                if body['markdown_key'].startswith('s3://'):
                    body['markdown_key'] = body['markdown_key'].replace(f"s3://{S3_BUCKET}/", "")
            else:
                raise

        tender_ref = body.get('tender_ref')
        tender_id = body.get('tender_id')
        
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
        
        # Support both formats: markdown_key (string) or markdown_paths (array)
        markdown_key = body.get('markdown_key')
        markdown_paths = body.get('markdown_paths', [])
        
        if not tender_ref or (not markdown_key and not markdown_paths):
            logger.error(f"Missing required fields in message: {body}")
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            return
            
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

        # 2. Split Markdown into logical documents (already classified by classification container)
        docs = DocumentCleaners.split_concatenated_file(full_markdown)
        logger.info(f"Split into {len(docs)} documents: {[d.doc_type for d in docs]}")

        
        # 3. Intelligent chunking (Avis/Product via LLM, others via header splitting)
        # Now returns a dictionary of chunk lists grouped by type
        chunks_by_type = asyncio.run(chunker.chunk_all_documents(
            docs=docs, 
            tender_id=tender_id, 
            tender_ref=tender_ref
        ))
        
        total_chunks = sum(len(c) for c in chunks_by_type.values())
        logger.info(f"Generated {total_chunks} total chunks across types: {list(chunks_by_type.keys())}")
        
        # 4. Upload Chunks to S3 (4 distinct files)
        output_keys = {}
        target_types = ['avis', 'specification', 'administrative', 'product']
        
        for t in target_types:
            type_chunks = chunks_by_type.get(t, [])
            if type_chunks:
                key = f"chunks_tender/{tender_ref}/{t}.json"
                # Wrap chunks in a dictionary with 'chunks' key for KB ingestion compatibility
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=key,
                    Body=json.dumps({"chunks": type_chunks}, ensure_ascii=False)
                )
                output_keys[f"{t}_key"] = key
                logger.info(f"Saved {len(type_chunks)} {t} chunks to {key}")
        
        # 6. Notify DB Filler Queue
        queue_url = KB_INGESTION_QUEUE_URL
        if not queue_url.startswith("https://"):
            try:
                q_response = sqs.get_queue_url(QueueName=KB_INGESTION_QUEUE_URL)
                queue_url = q_response['QueueUrl']
            except ClientError as e:
                logger.error(f"Could not get URL for queue {KB_INGESTION_QUEUE_URL}: {e}")
        
        logger.info(f"Sending completion message to {queue_url}")
        
        # Construct message payload with all keys
        completion_payload = {
            "tender_ref": tender_ref,
            "tender_id": tender_id,
            "status": "extraction_complete"
        }
        completion_payload.update(output_keys)
        # Also include legacy 'chunks_key' pointing to avis or first available for backward compatibility if needed
        if output_keys:
            first_key = output_keys.get('avis_key') or next(iter(output_keys.values()))
            completion_payload["chunks_key"] = first_key

        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(completion_payload)
        )

        # 9. Delete Message
        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
        logger.info(f"Successfully processed {tender_ref}")

    except ValidationError as e:
        logger.error(f"Validation errors processing message: {e.errors()}", exc_info=True)
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        # Don't delete message, let visibility timeout handle retry

if __name__ == "__main__":
    main()
