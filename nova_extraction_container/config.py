"""
Configuration module for Nova Extraction Container.
Loads environment variables and provides configuration settings.
"""
import os
from typing import Optional

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Config:
    """Configuration class with all settings."""
    
    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'eu-west-3')
    S3_BUCKET_NAME: str = os.getenv('S3_BUCKET_NAME', 'my-tender-documents-bucket')
    S3_SOURCE_PREFIX: str = os.getenv('S3_SOURCE_PREFIX', 'tenders_doc_final/')
    
    # SQS Configuration
    OCR_QUEUE_URL: str = os.getenv('OCR_QUEUE_URL', '')
    OCR_DLQ_URL: str = os.getenv('OCR_DLQ_URL', 'https://sqs.eu-west-3.amazonaws.com/034791378578/OCR_DLQ')
    DB_FILLER_QUEUE_URL: str = os.getenv('DB_FILLER_QUEUE_URL', '')
    VECTOR_QUEUE_URL: str = os.getenv('VECTOR_QUEUE_URL', '')
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_BASE_URL: str = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    
    # Model Configuration
    PRIMARY_MODEL: str = os.getenv('PRIMARY_MODEL', 'amazon/nova-lite')
    FALLBACK_MODEL_1: str = os.getenv('FALLBACK_MODEL_1', 'mistralai/mistral-small-3.2-24b-instruct')
    FALLBACK_MODEL_2: str = os.getenv('FALLBACK_MODEL_2', 'amazon/nova-2-lite')
    
    # Processing Configuration
    MAX_WORKERS: int = int(os.getenv('MAX_WORKERS', '3'))
    MAX_RETRIES_PER_MODEL: int = int(os.getenv('MAX_RETRIES_PER_MODEL', '3'))
    CHUNK_SIZE_PAGES: int = int(os.getenv('CHUNK_SIZE_PAGES', '10'))
    
    # Database Configuration (optional)
    DB_URL: Optional[str] = os.getenv('DB_URL')
    
    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        required = {
            'OCR_QUEUE_URL': cls.OCR_QUEUE_URL,
            'DB_FILLER_QUEUE_URL': cls.DB_FILLER_QUEUE_URL,
            'VECTOR_QUEUE_URL': cls.VECTOR_QUEUE_URL,
            'OPENROUTER_API_KEY': cls.OPENROUTER_API_KEY,
            'S3_BUCKET_NAME': cls.S3_BUCKET_NAME,
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (hiding sensitive data)."""
        print("=" * 50)
        print("Nova Extraction Container Configuration")
        print("=" * 50)
        print(f"AWS Region: {cls.AWS_REGION}")
        print(f"S3 Bucket: {cls.S3_BUCKET_NAME}")
        print(f"S3 Prefix: {cls.S3_SOURCE_PREFIX}")
        print(f"OCR Queue: {cls.OCR_QUEUE_URL[:50]}...")
        print(f"OCR DLQ: {cls.OCR_DLQ_URL[:50]}...")
        print(f"DB Filler Queue: {cls.DB_FILLER_QUEUE_URL[:50]}...")
        print(f"Vector Queue: {cls.VECTOR_QUEUE_URL[:50]}...")
        print(f"Primary Model: {cls.PRIMARY_MODEL}")
        print(f"Fallback 1: {cls.FALLBACK_MODEL_1}")
        print(f"Fallback 2: {cls.FALLBACK_MODEL_2}")
        print(f"Max Workers: {cls.MAX_WORKERS}")
        print(f"Chunk Size: {cls.CHUNK_SIZE_PAGES} pages")
        print(f"OpenRouter Key: {'*' * 20 if cls.OPENROUTER_API_KEY else 'NOT SET'}")
        print("=" * 50)
