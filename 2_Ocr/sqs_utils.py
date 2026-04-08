"""
SQS utility functions for queue operations.
Handles message receiving, deletion, and sending.
"""
import json
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from config import Config
from logger import logger


class SQSClient:
    """SQS client wrapper with error handling."""
    
    def __init__(self):
        """Initialize SQS client."""
        self.client = boto3.client('sqs', region_name=Config.AWS_REGION)
        self.ocr_queue_url = Config.OCR_QUEUE_URL
        self.classification_queue_url = Config.CLASSIFICATION_QUEUE_URL
    
    def receive_message(self, queue_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Receive message from SQS queue with long polling.
        
        Args:
            queue_url: Queue URL (default: OCR_QUEUE_URL)
            
        Returns:
            Message dict or None if no messages
        """
        if queue_url is None:
            queue_url = self.ocr_queue_url
        
        try:
            logger.debug(f"Polling queue: {queue_url[:50]}...")
            
            response = self.client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=Config.POLL_WAIT_TIME,
                VisibilityTimeout=Config.VISIBILITY_TIMEOUT,
                AttributeNames=['All'],
                MessageAttributeNames=['All']
            )
            
            if 'Messages' not in response or len(response['Messages']) == 0:
                logger.debug("No messages available")
                return None
            
            message = response['Messages'][0]
            logger.info(f"Received message: {message['MessageId']}")
            
            return {
                'message_id': message['MessageId'],
                'receipt_handle': message['ReceiptHandle'],
                'body': json.loads(message['Body']),
                'attributes': message.get('Attributes', {}),
                'message_attributes': message.get('MessageAttributes', {})
            }
        except ClientError as e:
            logger.error(f"Error receiving message: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing message body: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error receiving message: {e}")
            return None
    
    def delete_message(self, receipt_handle: str, queue_url: Optional[str] = None) -> bool:
        """
        Delete message from queue after successful processing.
        
        Args:
            receipt_handle: Receipt handle from received message
            queue_url: Queue URL (default: OCR_QUEUE_URL)
            
        Returns:
            True if successful, False otherwise
        """
        if queue_url is None:
            queue_url = self.ocr_queue_url
        
        try:
            logger.info(f"Deleting message from queue")
            
            self.client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle
            )
            
            logger.info("Message deleted successfully")
            return True
        except ClientError as e:
            logger.error(f"Error deleting message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting message: {e}")
            return False
    
    def send_message(self, message_body: Dict[str, Any], 
                     queue_url: Optional[str] = None) -> bool:
        """
        Send message to queue.
        
        Args:
            message_body: Message body dict
            queue_url: Queue URL (default: CLASSIFICATION_QUEUE_URL)
            
        Returns:
            True if successful, False otherwise
        """
        if queue_url is None:
            queue_url = self.classification_queue_url
        
        try:
            logger.info(f"Sending message to queue: {queue_url[:50]}...")
            
            response = self.client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message_body)
            )
            
            logger.info(f"Message sent successfully: {response['MessageId']}")
            return True
        except ClientError as e:
            logger.error(f"Error sending message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return False
    
    def change_message_visibility(self, receipt_handle: str, 
                                  visibility_timeout: int,
                                  queue_url: Optional[str] = None) -> bool:
        """
        Change message visibility timeout.
        Useful for extending processing time or immediate retry.
        
        Args:
            receipt_handle: Receipt handle from received message
            visibility_timeout: New visibility timeout in seconds
            queue_url: Queue URL (default: OCR_QUEUE_URL)
            
        Returns:
            True if successful, False otherwise
        """
        if queue_url is None:
            queue_url = self.ocr_queue_url
        
        try:
            logger.info(f"Changing message visibility to {visibility_timeout}s")
            
            self.client.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            
            logger.info("Message visibility changed successfully")
            return True
        except ClientError as e:
            logger.error(f"Error changing message visibility: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error changing message visibility: {e}")
            return False
