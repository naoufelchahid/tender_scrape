import boto3
import urllib.parse
import os
import re
import psycopg2
from typing import List, Dict, Any, Optional

s3_client = boto3.client('s3')

def get_db_connection():
    """Establish and return a database connection."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', '').strip(),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            port=os.environ.get('DB_PORT', '5432')
        )
        return conn
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        return None

def update_tender_db(reference: str, s3_folder_key: str, s3_bucket: str):
    """
    Update the tender record in the database.
    Sets is_documents=True (as requested), s3_path, and s3_uri.
    """
    conn = get_db_connection()
    if not conn:
        print(f"Skipping DB update for {reference} due to connection failure.")
        return False

    try:
        s3_uri = f"s3://{s3_bucket}/{s3_folder_key}"
        cur = conn.cursor()
        
        sql = """
            UPDATE tenders 
            SET is_results = TRUE,
                s3_path = %s,
                s3_uri = %s,
                updated_at = NOW()
            WHERE reference = %s
            OR REPLACE(REPLACE(reference, '/', '_'), ' ', '_') = %s
        """
        
        cur.execute(sql, (s3_folder_key, s3_uri, reference, reference))
        conn.commit()
        
        row_count = cur.rowcount
        cur.close()
        
        if row_count > 0:
            print(f"SUCCESS: Updated DB for tender {reference}")
            return True
        else:
            print(f"WARNING: No DB record found for tender {reference}")
            return False
            
    except Exception as e:
        print(f"ERROR: Failed to update DB: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def extract_references(filename_no_ext: str) -> List[str]:
    """
    Extract potential references from filename.
    Format: result_{REF}.pdf or result_{REF}_{IDX}.pdf
    Returns list of candidate references to try.
    """
    # Remove 'result_' prefix if present
    clean = filename_no_ext
    if clean.startswith('result_'):
        clean = clean[7:]
    
    candidates = []
    
    # 1. Full remaining string matches REF (e.g. 12_2025)
    candidates.append(clean)
    
    # 2. Check for tailing index (e.g. _1, _2)
    # If clean is "12_2025_AO_1", candidate 2 is "12_2025_AO"
    match = re.search(r'^(.*)_\d+$', clean)
    if match:
        candidates.append(match.group(1))
        
    return candidates

def process_file_logic(s3_bucket: str, s3_key: str) -> Dict[str, str]:
    """
    Process single file: Copy to tenders_doc_final/{REF}/ and update DB.
    """
    result_code = 'Succeeded'
    result_string = ''

    try:
        filename = os.path.basename(s3_key)
        filename_no_ext, ext = os.path.splitext(filename)
        
        # skip validation of folder since we trigger on prefix
        
        # 1. Identify Reference
        candidates = extract_references(filename_no_ext)
        print(f"Processing {filename}. Candidates: {candidates}")
        
        ref_found = None
        
        # We need to know which candidate is correct to form the dest path.
        # But dest path depends on the correct REF folder?
        # Typically folders in tenders_doc_final are named exactly as the REF (or sanitized REF).
        # We can try to update DB first to see which one "hits"?
        # OR we just pick the longest one?
        # Safest is to try DB update. If it hits, we use that Ref for the folder.
        
        for cand in candidates:
             # We can't easily check DB without updating or selecting.
             # Let's assume we do a SELECT to check existence?
             # For performance, maybe just try update. But update changes state.
             # Actually, if we update, we commit.
             
             # Let's try to verify REF against DB first?
             conn = get_db_connection()
             if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT reference FROM tenders WHERE reference = %s OR REPLACE(REPLACE(reference, '/', '_'), ' ', '_') = %s", (cand, cand))
                    res = cur.fetchone()
                    cur.close()
                    conn.close()
                    if res:
                        ref_found = res[0] # Use the real ref from DB
                        print(f"Matched reference in DB: {ref_found} (from candidate {cand})")
                        break
                except Exception as e:
                    print(f"DB Check failed: {e}")
                    if conn: conn.close()
        
        if not ref_found:
             # Fallback: use the first candidate (full string without result_) as best guess
             # and blindly copy there. It might be a new tender or mismatch.
             ref_found = candidates[0]
             print(f"No DB match found. using candidate: {ref_found}")

        # 2. Copy to tenders_doc_final
        # Dest: tenders_doc_final/{REF_FOUND}/{filename}
        # Note: REF_FOUND might contain slashes. S3 keys handle slashes as folders.
        # But typically we want a clean folder name? 
        # `Lambda_unziptendersbatch.py` uses `zip_name_no_ext` as folder.
        # If zip name was "12_2025.zip", folder is "12_2025".
        # So we should probably use the sanitized candidate or the ref_found itself.
        # We'll use ref_found as the folder name.
        
        # Sanitize folder name just in case?
        # DB usually has "12/2025", we probably want "12_2025" as folder?
        # Lambda_unziptendersbatch uses `zip_name_no_ext`, which comes from the file.
        # If I downloaded "12_2025.zip", folder is "12_2025".
        # So I will sanitize the ref for the folder name.
        folder_name = ref_found.replace('/', '_').replace(' ', '_')
        
        dest_key = f"tenders_doc_final/{folder_name}/{filename}"
        
        print(f"Copying {s3_key} -> {dest_key}")
        s3_client.copy_object(
            Bucket=s3_bucket,
            CopySource={'Bucket': s3_bucket, 'Key': s3_key},
            Key=dest_key
        )
        
        # 3. Update DB
        # We already might have found the ref, but we need to run the update logic 
        # to set is_documents=True (and ensure path is set).
        s3_folder_key = f"tenders_doc_final/{folder_name}/"
        update_tender_db(ref_found, s3_folder_key, s3_bucket)
        
        # 4. Clean up: Delete the ORIGINAL file from tender_results/
        print(f"Deleting original file: {s3_key}")
        s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
        
        result_string = f"Copied to {dest_key}, updated DB, and deleted original"

    except Exception as e:
        print(f"Error processing {s3_key}: {str(e)}")
        result_code = 'TemporaryFailure'
        result_string = str(e)
        
    return {
        'resultCode': result_code,
        'resultString': result_string
    }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for S3 Event Notifications.
    """
    print("Received event:", event)

    if 'Records' in event:
        for record in event['Records']:
            if 's3' in record:
                s3_bucket = record['s3']['bucket']['name']
                s3_key = urllib.parse.unquote_plus(record['s3']['object']['key'])
                
                # Filter: Ensure it is in tender_results/
                if not s3_key.startswith('tender_results/'):
                    print(f"Skipping {s3_key} (not in tender_results/)")
                    continue
                
                # Filter: Ensure it is a file (not a folder object if any)
                if s3_key.endswith('/'):
                    continue
                    
                process_file_logic(s3_bucket, s3_key)
        
        return {'statusCode': 200, 'body': 'Event processed'}
    
    else:
        print("Unknown event structure")
        return {'statusCode': 400, 'body': 'Unknown event structure'}
