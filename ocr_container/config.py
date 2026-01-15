"""
Configuration management for OCR container.
Loads and validates environment variables.
"""
import os
import sys
from typing import Optional


class Config:
    """Configuration class for OCR container."""
    
    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    S3_BUCKET_NAME: str = os.getenv('S3_BUCKET_NAME', '')
    
    # SQS Queue URLs
    OCR_QUEUE_URL: str = os.getenv('OCR_QUEUE_URL', '')
    EXTRACTION_QUEUE_URL: str = os.getenv('EXTRACTION_QUEUE_URL', '')
    
    # OpenRouter API Configuration
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_APP_NAME: str = os.getenv('OPENROUTER_APP_NAME', 'OCR-Service')
    PRIMARY_MODEL: str = os.getenv('PRIMARY_MODEL', 'meta-llama/llama-4-maverick')
    FALLBACK_MODEL_1: str = os.getenv('FALLBACK_MODEL_1', 'meta-llama/llama-guard-4-12b')
    FALLBACK_MODEL_2: str = os.getenv('FALLBACK_MODEL_2', 'meta-llama/llama-4-scout')
    ENABLE_TABLE_ENHANCEMENT: bool = os.getenv('ENABLE_TABLE_ENHANCEMENT', 'true').lower() == 'true'
    
    # Processing Configuration
    MAX_RETRIES: int = int(os.getenv('MAX_RETRIES', '3'))
    VISIBILITY_TIMEOUT: int = int(os.getenv('VISIBILITY_TIMEOUT', '900'))
    BATCH_SIZE: int = int(os.getenv('BATCH_SIZE', '10'))
    MAX_WORKERS: int = int(os.getenv('MAX_WORKERS', '10'))  # Concurrency for OCR
    POLL_WAIT_TIME: int = 20  # Long polling wait time in seconds
    
    # S3 Path Prefixes
    FINAL_DOC_PREFIX: str = 'tenders_doc_final'
    MARKDOWN_PREFIX: str = 'markdown_tender'
    
    # Supported file extensions
    SUPPORTED_EXTENSIONS: tuple = ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.jpeg', '.jpg', '.png')
    
    @classmethod
    def validate(cls) -> bool:
        """
        Validate that all required configuration values are set.
        
        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        required_vars = {
            'S3_BUCKET_NAME': cls.S3_BUCKET_NAME,
            'OCR_QUEUE_URL': cls.OCR_QUEUE_URL,
            'EXTRACTION_QUEUE_URL': cls.EXTRACTION_QUEUE_URL,
            'OPENROUTER_API_KEY': cls.OPENROUTER_API_KEY,
        }
        
        missing_vars = [var for var, value in required_vars.items() if not value]
        
        if missing_vars:
            print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (hiding sensitive values)."""
        print("OCR Container Configuration:")
        print(f"  AWS_REGION: {cls.AWS_REGION}")
        print(f"  S3_BUCKET_NAME: {cls.S3_BUCKET_NAME}")
        print(f"  OCR_QUEUE_URL: {cls.OCR_QUEUE_URL[:50]}...")
        print(f"  EXTRACTION_QUEUE_URL: {cls.EXTRACTION_QUEUE_URL[:50]}...")
        print(f"  OPENROUTER_API_KEY: {'*' * 10 if cls.OPENROUTER_API_KEY else 'NOT SET'}")
        print(f"  OPENROUTER_APP_NAME: {cls.OPENROUTER_APP_NAME}")
        print(f"  PRIMARY_MODEL: {cls.PRIMARY_MODEL}")
        print(f"  FALLBACK_MODEL_1: {cls.FALLBACK_MODEL_1}")
        print(f"  FALLBACK_MODEL_2: {cls.FALLBACK_MODEL_2}")
        print(f"  ENABLE_TABLE_ENHANCEMENT: {cls.ENABLE_TABLE_ENHANCEMENT}")
        print(f"  MAX_RETRIES: {cls.MAX_RETRIES}")
        print(f"  VISIBILITY_TIMEOUT: {cls.VISIBILITY_TIMEOUT}s")
        print(f"  BATCH_SIZE: {cls.BATCH_SIZE}")


# Validate configuration on import
if not Config.validate():
    print("Configuration validation failed. Please check your environment variables.")
    if os.getenv('SKIP_CONFIG_VALIDATION') != 'true':
        sys.exit(1)
