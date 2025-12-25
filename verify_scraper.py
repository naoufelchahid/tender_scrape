import os
import shutil
import zipfile
import logging
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock environment variables before importing if needed, 
# but we will mock the calls.
import results_scraper
from results_scraper import ResultsScraper, Tender

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_dummy_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'w') as zf:
        # 1. Valid PDF
        zf.writestr('valid1.pdf', b'PDF_CONTENT_1')
        
        # 2. Valid DOCX
        zf.writestr('valid2.docx', b'DOCX_CONTENT_2')
        
        # 3. Ignored TXT
        zf.writestr('ignore.txt', b'TXT_CONTENT')
        
        # 4. Duplicate Content PDF (should be skipped)
        zf.writestr('duplicate.pdf', b'PDF_CONTENT_1')
        
        # 5. Nested PDF (should be flattened)
        zf.writestr('subfolder/nested.pdf', b'PDF_CONTENT_3')

def test_unzip_and_upload():
    print(">>> Starting Verification Test")
    
    # Setup directories
    test_dir = Path("test_downloads")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()
    
    # Mock Tender
    tender = MagicMock(spec=Tender)
    tender.reference = "TEST_REF_2025"
    
    # Mock ResultsScraper
    # We purposefully bypass __init__ to avoid DB/S3 connections
    scraper = ResultsScraper.__new__(ResultsScraper)
    scraper.downloads_dir = test_dir
    scraper.s3_bucket = "mock-bucket"
    scraper.s3_client = MagicMock()
    scraper.upload_file_to_s3 = MagicMock()
    
    # Manually bind sanitize_filename since we bypassed init
    # But it is a method on the class, so instance has it.
    
    # Create Test Zip
    zip_path = test_dir / "test_data.zip"
    create_dummy_zip(zip_path)
    
    print(f"Created zip at {zip_path}")
    
    # Run Method
    print("Running unzip_and_upload...")
    scraper.unzip_and_upload(str(zip_path), tender)
    
    # Verification
    print("\n>>> Verification Results:")
    
    # 1. Check Files in Directory
    files = list(test_dir.glob("*"))
    # filter out the zip if it wasn't removed (logic says it should be removed)
    files = [f for f in files if f.name != 'test_data.zip']
    
    print(f"Files in download dir: {[f.name for f in files]}")
    
    # Expected: 
    # - result_TEST_REF_2025_1.pdf (PDF_CONTENT_1)
    # - result_TEST_REF_2025_2.docx (DOCX_CONTENT_2)
    # - result_TEST_REF_2025_3.pdf (PDF_CONTENT_3)
    # Duplicate (PDF_CONTENT_1) should be ignored.
    # TXT should be ignored.
    
    expected_count = 3
    if len(files) == expected_count:
        print("[PASS] File count matches expected (3).")
    else:
        print(f"[FAIL] Expected {expected_count} files, found {len(files)}.")
        
    # Check flattening
    is_flat = all(not f.is_dir() for f in files)
    if is_flat:
        print("[PASS] All outputs are files (no folders).")
    else:
        print("[FAIL] Found directories!")
        
    # Check S3 Calls
    print(f"S3 Upload Calls: {scraper.upload_file_to_s3.call_count}")
    for call in scraper.upload_file_to_s3.call_args_list:
        path_arg, key_arg = call[0]
        print(f"  - Uploaded Local: {path_arg.name}, Key: {key_arg}")
        if "/" in key_arg:
             print(f"    [WARNING] Key '{key_arg}' contains folders (slashes). Check if this is intended.")
        else:
             print(f"    [PASS] Key '{key_arg}' is flat.")

    # Cleanup
    # shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_unzip_and_upload()
