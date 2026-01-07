from main import NovaExtractionService
from logger import logger
import time

def process_one():
    service = NovaExtractionService()
    logger.info("Polling SQS for one message...")
    
    # Try polling a few times
    for _ in range(5):
        message = service.sqs_client.receive_message()
        if message:
            logger.info(f"Received message: {message['message_id']}")
            body = message['body']
            tender_ref = body.get('tender_ref')
            tender_id = body.get('tender_id', tender_ref)
            
            if service._process_tender(tender_ref, tender_id):
                service.sqs_client.delete_message(message['receipt_handle'])
                logger.info("Message processed and deleted.")
                return
            else:
                logger.error("Processing failed.")
                return
        else:
            logger.info("No message found, retrying in 2s...")
            time.sleep(2)
            
    logger.info("Timeout: No message received.")

if __name__ == "__main__":
    process_one()
