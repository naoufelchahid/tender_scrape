"""
SQS client utilities for queue polling and messaging.
"""
import json
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError

from config import Config
from logger import logger


class SQSClient:
    """SQS client for queue operations."""
    
    def __init__(self):
        """Initialize SQS client."""
        self.sqs = boto3.client('sqs', region_name=Config.AWS_REGION)
        self.queue_url = Config.OCR_QUEUE_URL
        self.db_filler_queue_url = Config.DB_FILLER_QUEUE_URL
    
    def receive_message(self, wait_time: int = 20) -> Optional[Dict[str, Any]]:
        """
        Receive message from queue with long polling.
        
        Args:
            wait_time: Wait time in seconds for long polling
            
        Returns:
            Message dict with keys: message_id, receipt_handle, body
            Returns None if no messages
        """
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=wait_time,
                MessageAttributeNames=['All']
            )
            
            if 'Messages' not in response:
                return None
            
            msg = response['Messages'][0]
            body = json.loads(msg['Body'])
            
            return {
                'message_id': msg['MessageId'],
                'receipt_handle': msg['ReceiptHandle'],
                'body': body
            }
            
        except ClientError as e:
            logger.error(f"Error receiving message: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding message body: {e}")
            return None
    
    def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete message from queue.
        
        Args:
            receipt_handle: Receipt handle from received message
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.debug("Message deleted successfully")
            return True
        except ClientError as e:
            logger.error(f"Error deleting message: {e}")
            return False
    
    def send_message(self, body: Dict[str, Any], 
                     queue_url: Optional[str] = None) -> bool:
        """
        Send message to queue.
        
        Args:
            body: Message body dictionary
            queue_url: Optional queue URL (defaults to DB_FILLER_QUEUE)
            
        Returns:
            True if successful, False otherwise
        """
        target_queue = queue_url or self.db_filler_queue_url
        
        try:
            response = self.sqs.send_message(
                QueueUrl=target_queue,
                MessageBody=json.dumps(body, ensure_ascii=False)
            )
            logger.info(f"Message sent to queue: {response['MessageId']}")
            return True
        except ClientError as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    def get_queue_url(self, queue_name: str) -> Optional[str]:
        """
        Get queue URL from queue name.
        
        Args:
            queue_name: Queue name
            
        Returns:
            Queue URL or None if not found
        """
        try:
            response = self.sqs.get_queue_url(QueueName=queue_name)
            return response['QueueUrl']
        except ClientError as e:
            logger.error(f"Error getting queue URL for {queue_name}: {e}")
            return None
