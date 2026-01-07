import boto3
import json
import os
from config import Config

def send_test_message(tender_ref):
    sqs = boto3.client('sqs', region_name=Config.AWS_REGION)
    queue_url = Config.OCR_QUEUE_URL
    
    message = {
        'tender_ref': tender_ref,
        'tender_id': 12345
    }
    
    print(f"Sending message to {queue_url}: {json.dumps(message)}")
    
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message)
    )
    
    print(f"Message sent! ID: {response['MessageId']}")

if __name__ == "__main__":
    # Test tender from user request
    tender_ref = "10_2025_COMRURS_SLIMOUALK" 
    send_test_message(tender_ref)
