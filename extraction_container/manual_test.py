import os
import json
import logging
import boto3
from dotenv import load_dotenv

# Load env variables if .env exists
try:
    load_dotenv()
except:
    pass

from src.extraction import ExtractionService
from src.llm_chunker import LLMChunker
from main import handle_message

# Mocking SQS to avoid disrupting real queues
class MockSQS:
    def delete_message(self, QueueUrl, ReceiptHandle):
        print(f"[MOCK SQS] Deleting message from {QueueUrl}, handle: {ReceiptHandle}")
    
    def send_message(self, QueueUrl, MessageBody):
        print(f"[MOCK SQS] Sending message to {QueueUrl}:")
        print(f"Body: {MessageBody}")
    
    def get_queue_url(self, QueueName):
        return {"QueueUrl": f"https://sqs.mock.amazonaws.com/{QueueName}"}

def run_test():
    logging.basicConfig(level=logging.INFO)
    
    # Config
    AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
    BEDROCK_MODEL = "qwen/qwen-2.5-72b-instruct" # Known working model
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
    
    # Clients
    s3 = boto3.client('s3', region_name=AWS_REGION)
    sqs = MockSQS()
    
    extractor = ExtractionService(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    chunker = LLMChunker(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    
    # Test Data
    tender_ref = "0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL"
    markdown_key = "markdown_tender/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL_ocr.md"
    
    msg = {
        'ReceiptHandle': 'mock_handle_123',
        'Body': json.dumps({
            "tender_ref": tender_ref,
            "tender_id": 9999,
            "markdown_key": markdown_key
        })
    }
    
    print(f"--- STARTING TEST FOR {tender_ref} ---")
    handle_message(msg, sqs, s3, extractor, chunker)
    print("--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()
