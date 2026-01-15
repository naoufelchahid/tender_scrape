"""
Configuration management for Results OCR container.
Loads and validates environment variables.

Stage: Extraction Container - OCR Processing
"""
import os
import sys
from typing import Optional


class Config:
    """Configuration class for Results OCR container."""
    
    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    S3_BUCKET_NAME: str = os.getenv('S3_BUCKET_NAME', '')
    
    # SQS Queue Configuration
    RESULTS_QUEUE_URL: str = os.getenv('RESULTS_QUEUE_URL', '')
    RESULTS_FILLER_QUEUE_URL: str = os.getenv('RESULTS_FILLER_QUEUE_URL', '')
    
    # S3 Path Prefixes
    INPUT_PREFIX: str = os.getenv('INPUT_PREFIX', 'results_lambda_ocr/')
    OUTPUT_PREFIX: str = os.getenv('OUTPUT_PREFIX', 'Results_markdown/')
    MARKDOWN_PREFIX: str = os.getenv('MARKDOWN_PREFIX', 'Results_markdown/markdown_files/')
    METADATA_PREFIX: str = os.getenv('METADATA_PREFIX', 'Results_markdown/results_metadata/')
    FAILED_PREFIX: str = os.getenv('FAILED_PREFIX', 'results_failed/')
    
    # Groq API Configuration
    GROQ_API_KEY: str = os.getenv('GROQ_API_KEY', '')
    PRIMARY_MODEL: str = os.getenv('PRIMARY_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
    FALLBACK_MODEL: str = os.getenv('FALLBACK_MODEL', 'meta-llama/llama-4-maverick-17b-128e-instruct')
    
    # OpenRouter API Configuration (optional fallback)
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL: str = os.getenv('OPENROUTER_MODEL', 'nvidia/nemotron-nano-12b-v2-vl:free')
    
    # Processing Configuration
    POLLING_INTERVAL_SECONDS: int = int(os.getenv('POLLING_INTERVAL_SECONDS', '30'))
    MAX_WORKERS: int = int(os.getenv('MAX_WORKERS', '5'))
    PDF_DPI: int = int(os.getenv('PDF_DPI', '300'))
    MAX_RETRIES: int = int(os.getenv('MAX_RETRIES', '3'))
    
    # Text Layer Detection
    TEXT_LAYER_MIN_CHARS: int = int(os.getenv('TEXT_LAYER_MIN_CHARS', '50'))
    TEXT_LAYER_SAMPLE_PAGES: int = int(os.getenv('TEXT_LAYER_SAMPLE_PAGES', '3'))
    TEXT_LAYER_CONFIDENCE_THRESHOLD: float = float(os.getenv('TEXT_LAYER_CONFIDENCE_THRESHOLD', '0.5'))
    
    # Processing Options
    DELETE_SOURCE_FILES: bool = os.getenv('DELETE_SOURCE_FILES', 'true').lower() == 'true'
    MOVE_FAILED_FILES: bool = os.getenv('MOVE_FAILED_FILES', 'false').lower() == 'true'
    
    # Supported file extensions
    SUPPORTED_EXTENSIONS: tuple = ('.pdf', '.docx', '.doc')
    
    @classmethod
    def validate(cls) -> bool:
        """
        Validate that all required configuration values are set.
        
        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        required_vars = {
            'S3_BUCKET_NAME': cls.S3_BUCKET_NAME,
            'RESULTS_QUEUE_URL': cls.RESULTS_QUEUE_URL,
            'GROQ_API_KEY': cls.GROQ_API_KEY,
        }
        
        missing_vars = [var for var, value in required_vars.items() if not value]
        
        if missing_vars:
            print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (hiding sensitive values)."""
        print("=" * 60)
        print("Results OCR Container Configuration")
        print("=" * 60)
        print(f"  AWS_REGION: {cls.AWS_REGION}")
        print(f"  S3_BUCKET_NAME: {cls.S3_BUCKET_NAME}")
        print(f"  RESULTS_QUEUE_URL: {cls.RESULTS_QUEUE_URL[:50]}..." if len(cls.RESULTS_QUEUE_URL) > 50 else f"  RESULTS_QUEUE_URL: {cls.RESULTS_QUEUE_URL}")
        print(f"  RESULTS_FILLER_QUEUE_URL: {cls.RESULTS_FILLER_QUEUE_URL[:50]}..." if len(cls.RESULTS_FILLER_QUEUE_URL) > 50 else f"  RESULTS_FILLER_QUEUE_URL: {cls.RESULTS_FILLER_QUEUE_URL}")
        print(f"  INPUT_PREFIX: {cls.INPUT_PREFIX}")
        print(f"  MARKDOWN_PREFIX: {cls.MARKDOWN_PREFIX}")
        print(f"  METADATA_PREFIX: {cls.METADATA_PREFIX}")
        print(f"  OUTPUT_PREFIX: {cls.OUTPUT_PREFIX}")
        print(f"  GROQ_API_KEY: {'*' * 10 if cls.GROQ_API_KEY else 'NOT SET'}")
        print(f"  PRIMARY_MODEL: {cls.PRIMARY_MODEL}")
        print(f"  FALLBACK_MODEL: {cls.FALLBACK_MODEL}")
        print(f"  POLLING_INTERVAL: {cls.POLLING_INTERVAL_SECONDS}s")
        print(f"  MAX_WORKERS: {cls.MAX_WORKERS}")
        print(f"  PDF_DPI: {cls.PDF_DPI}")
        print(f"  DELETE_SOURCE_FILES: {cls.DELETE_SOURCE_FILES}")
        print("=" * 60)


# Validate configuration on import
if not Config.validate():
    print("Configuration validation failed. Please check your environment variables.")
    if os.getenv('SKIP_CONFIG_VALIDATION') != 'true':
        sys.exit(1)
