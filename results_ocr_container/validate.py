#!/usr/bin/env python3
"""
Quick validation script to check container setup.
Tests imports and basic functionality.
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from config import Config
        print("✅ config.py imported")
        
        from logger import logger
        print("✅ logger.py imported")
        
        from text_layer_detector import has_text_layer
        print("✅ text_layer_detector.py imported")
        
        from prompts import TENDER_RESULTS_PROMPT
        print("✅ prompts.py imported")
        
        from s3_poller import S3Poller
        print("✅ s3_poller.py imported")
        
        from ocr_service import OCRService
        print("✅ ocr_service.py imported")
        
        from document_processor import DocumentProcessor
        print("✅ document_processor.py imported")
        
        from utils.pdf_utils import extract_text_with_pdfplumber
        print("✅ utils.pdf_utils imported")
        
        from utils.docx_utils import extract_text_from_docx
        print("✅ utils.docx_utils imported")
        
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")
    
    # Skip validation for this test
    os.environ['SKIP_CONFIG_VALIDATION'] = 'true'
    
    try:
        from config import Config
        
        print(f"  S3_BUCKET_NAME: {Config.S3_BUCKET_NAME or 'NOT SET'}")
        print(f"  INPUT_PREFIX: {Config.INPUT_PREFIX}")
        print(f"  OUTPUT_PREFIX: {Config.OUTPUT_PREFIX}")
        print(f"  PRIMARY_MODEL: {Config.PRIMARY_MODEL}")
        print(f"  FALLBACK_MODEL: {Config.FALLBACK_MODEL}")
        print(f"  MAX_WORKERS: {Config.MAX_WORKERS}")
        print(f"  POLLING_INTERVAL: {Config.POLLING_INTERVAL_SECONDS}s")
        
        print("✅ Configuration loaded")
        return True
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("Results OCR Container - Validation")
    print("=" * 60)
    
    results = []
    
    # Test imports
    results.append(test_imports())
    
    # Test config
    results.append(test_config())
    
    # Summary
    print("\n" + "=" * 60)
    if all(results):
        print("✅ All validation tests passed!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some validation tests failed")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
