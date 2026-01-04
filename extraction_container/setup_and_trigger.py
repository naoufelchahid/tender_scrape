import boto3
import json
import os
import logging
from dotenv import load_dotenv

# Load env variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_and_trigger():
    # Config
    S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
    SQS_QUEUE_URL = os.environ.get('EXTRACTION_QUEUE_URL')
    AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
    
    if not S3_BUCKET or not SQS_QUEUE_URL:
        logger.error("Missing S3_BUCKET_NAME or EXTRACTION_QUEUE_URL in .env")
        return

    s3 = boto3.client('s3', region_name=AWS_REGION)
    sqs = boto3.client('sqs', region_name=AWS_REGION)

    # Real tender from S3 list (Size: 577KB)
    tender_ref = "032_2025_AMENDISTE_AME"
    markdown_key = f"markdown_tender/{tender_ref}/{tender_ref}_ocr.md"
    
    # Skip Upload - File already exists in S3 (verified via ls)
    logger.info(f"Using existing S3 file: s3://{S3_BUCKET}/{markdown_key}")

    # 2. Send SQS Message
    message_body = {
        "tender_ref": tender_ref,
        "tender_id": 8888, # Use different ID to distinguish
        "markdown_key": markdown_key
    }
    
    logger.info(f"Sending message to {SQS_QUEUE_URL}...")
    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps(message_body)
    )
    logger.info("Message sent successfully.")

if __name__ == "__main__":
    setup_and_trigger()
