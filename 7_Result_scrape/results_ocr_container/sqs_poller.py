"""
SQS polling service for receiving messages from RESULTS_QUEUE.

Stage: Extraction Container - OCR Processing
"""
import boto3
import json
from typing import Optional, Dict, Any
from logger import logger
from config import Config


class SQSPoller:
    """SQS polling service for RESULTS_QUEUE messages."""
    
    def __init__(self):
        """Initialize SQS poller."""
        self.sqs_client = boto3.client('sqs', region_name=Config.AWS_REGION)
        self.queue_url = Config.RESULTS_QUEUE_URL
        
        logger.info(f"Initialized SQS Poller for queue: {self.queue_url}")
    
    def receive_message(self) -> Optional[Dict[str, Any]]:
        """
        Receive a message from the RESULTS_QUEUE.
        Uses long polling (20 seconds) for efficiency.
        
        Returns:
            Dictionary with message details or None if no messages
            Format: {
                'message_id': str,
                'receipt_handle': str,
                'body': dict (parsed JSON)
            }
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,  # Long polling
                AttributeNames=['All'],
                MessageAttributeNames=['All']
            )
            
            if 'Messages' not in response or not response['Messages']:
                return None
            
            message = response['Messages'][0]
            
            # Parse message body (JSON)
            try:
                body = json.loads(message['Body'])
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message body as JSON: {e}")
                logger.error(f"Raw body: {message['Body']}")
                # Delete malformed message
                self.delete_message(message['ReceiptHandle'])
                return None
            
            return {
                'message_id': message['MessageId'],
                'receipt_handle': message['ReceiptHandle'],
                'body': body
            }
            
        except Exception as e:
            logger.error(f"Error receiving SQS message: {e}")
            return None
    
    def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete a message from the queue after successful processing.
        
        Args:
            receipt_handle: Receipt handle from received message
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.info(f"✅ Deleted message from queue")
            return True
        except Exception as e:
            logger.error(f"Error deleting SQS message: {e}")
            return False
    
    def change_message_visibility(self, receipt_handle: str, visibility_timeout: int) -> bool:
        """
        Change the visibility timeout of a message (for retry logic).
        
        Args:
            receipt_handle: Receipt handle from received message
            visibility_timeout: New visibility timeout in seconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.sqs_client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            return True
        except Exception as e:
            logger.error(f"Error changing message visibility: {e}")
            return False
    
    def send_message(self, queue_url: str, message_body: Dict[str, Any]) -> bool:
        """
        Send a message to a specific queue.
        
        Args:
            queue_url: Target queue URL
            message_body: Message payload as dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import json
            
            response = self.sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message_body)
            )
            
            logger.info(f"✅ Sent message to queue")
            logger.debug(f"   Message ID: {response['MessageId']}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending SQS message: {e}")
            return False
