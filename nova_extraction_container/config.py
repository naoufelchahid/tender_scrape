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
    
    # Groq Configuration
    GROQ_API_KEY: str = os.getenv('GROQ_API_KEY', '')
    
    # Model Configuration (Groq Vision Models)
    # Groq only has 2 vision models, so we use Scout twice for 3-tier fallback
    PRIMARY_MODEL: str = os.getenv('PRIMARY_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
    FALLBACK_MODEL_1: str = os.getenv('FALLBACK_MODEL_1', 'meta-llama/llama-4-maverick-17b-128e-instruct')
    FALLBACK_MODEL_2: str = os.getenv('FALLBACK_MODEL_2', 'meta-llama/llama-4-scout-17b-16e-instruct')
    
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
            'GROQ_API_KEY': cls.GROQ_API_KEY,
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
        print(f"Groq API Key: {'*' * 20 if cls.GROQ_API_KEY else 'NOT SET'}")
        print("=" * 50)
