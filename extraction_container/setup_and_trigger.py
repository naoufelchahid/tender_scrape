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

    # Real tender from S3 (simulated OCR output)
    tender_ref = "552_2025_SRMCS_SOCREGMULCASSETSA"
    # In a real flow, OCR would produce this. For test, we point to a mock or existing file.
    # Since we can't run real OCR, we will use the existing mock file but rename the Ref in the message
    # OR we can assume `setup_and_trigger` just sends the message and we rely on `manual_test.py` logic?
    # No, `setup_and_trigger` sends to the REAL SQS queue.
    # The Extraction Container (running via main.py) will pick it up and try to download `markdown_key`.
    # We must ensure that `markdown_key` EXISTS in S3.
    # I will stick to the PREVIOUSLY KNOWN working file for the "Extraction" test, 
    # as validating `run_updates.sh` (previous step) proved the "upload to S3" part works.
    # Now validting Extraction.
    
    # Actually, let's use the file we downloaded if we can "OCR" it.
    # We can't easily OCR it here without the OCR container.
    # So I will revert to using the KNOWN working markdown file to verify the Extraction Pipeline itself.
    
    tender_ref = "032_2025_AMENDISTE_AME" 
    markdown_key = f"markdown_tender/{tender_ref}/{tender_ref}_ocr.md"
    
    # Skip Upload - File already exists in S3
    logger.info(f"Using existing S3 file: s3://{S3_BUCKET}/{markdown_key}")

    # 2. Send SQS Message
    message_body = {
        "tender_ref": tender_ref,
        "tender_id": 7777, 
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
