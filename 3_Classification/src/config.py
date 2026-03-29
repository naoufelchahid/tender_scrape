"""
Pipeline Stage: Classification Container
Configuration management
"""

import os
from typing import Optional


class Config:
    """Configuration for classification container."""
    
    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'eu-west-3')
    S3_BUCKET_NAME: str = os.getenv('S3_BUCKET_NAME', '')
    
    # SQS Queues
    CLASSIFICATION_QUEUE_URL: str = os.getenv('CLASSIFICATION_QUEUE_URL', '')
    EXTRACTION_QUEUE_URL: str = os.getenv('EXTRACTION_QUEUE_URL', '')
    
    # S3 Paths
    MARKDOWN_PREFIX: str = os.getenv('MARKDOWN_PREFIX', 'markdown_tender/')
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    MODEL_PRIMARY: str = os.getenv('MODEL_PRIMARY', 'google/gemma-3n-e2b-it:free')
    MODEL_SECONDARY: str = os.getenv('MODEL_SECONDARY', 'qwen/qwen3-next-80b-a3b-instruct:free')
    MODEL_TERTIARY: str = os.getenv('MODEL_TERTIARY', 'nvidia/nemotron-nano-9b-v2:free')
    
    @classmethod
    def validate(cls) -> bool:
        """
        Validate required configuration.
        
        Returns:
            True if all required config is present
        """
        missing = []
        
        if not cls.S3_BUCKET_NAME:
            missing.append('S3_BUCKET_NAME')
        if not cls.CLASSIFICATION_QUEUE_URL:
            missing.append('CLASSIFICATION_QUEUE_URL')
        if not cls.EXTRACTION_QUEUE_URL:
            missing.append('EXTRACTION_QUEUE_URL')
        if not cls.OPENROUTER_API_KEY:
            missing.append('OPENROUTER_API_KEY')
        
        if missing:
            print(f"❌ Missing required configuration: {', '.join(missing)}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (safe for logging)."""
        print("=" * 50)
        print("Classification Container Configuration")
        print("=" * 50)
        print(f"  AWS_REGION: {cls.AWS_REGION}")
        print(f"  S3_BUCKET_NAME: {cls.S3_BUCKET_NAME}")
        print(f"  CLASSIFICATION_QUEUE_URL: {cls.CLASSIFICATION_QUEUE_URL[:50]}...")
        print(f"  EXTRACTION_QUEUE_URL: {cls.EXTRACTION_QUEUE_URL[:50]}...")
        print(f"  MARKDOWN_PREFIX: {cls.MARKDOWN_PREFIX}")
        print(f"  OPENROUTER_API_KEY: {'*' * 20 if cls.OPENROUTER_API_KEY else 'NOT SET'}")
        print(f"  MODEL_PRIMARY: {cls.MODEL_PRIMARY}")
        print(f"  MODEL_SECONDARY: {cls.MODEL_SECONDARY}")
        print(f"  MODEL_TERTIARY: {cls.MODEL_TERTIARY}")
        print("=" * 50)
