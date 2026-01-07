import boto3
import urllib.parse
import zipfile
import os
import shutil
import json
from typing import List, Dict, Any, Optional
import psycopg2

s3_client = boto3.client('s3')
sqs_client = boto3.client('sqs')

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

def send_to_ocr_queue(tender_ref: str, s3_folder_key: str, s3_bucket: str):
    """
    Send a message to OCR_QUEUE to trigger OCR processing for the unzipped folder.
    """
    ocr_queue_url = os.environ.get('OCR_QUEUE_URL')
    if not ocr_queue_url:
        print("WARNING: OCR_QUEUE_URL not set, skipping SQS message")
        return
    
    try:
        # Send just the S3 key (not full URI) since OCR container constructs the full path
        message_body = {
            "tender_ref": tender_ref,
            "s3_paths": [s3_folder_key]  # Changed from full URI to just the key
        }
        
        response = sqs_client.send_message(
            QueueUrl=ocr_queue_url,
            MessageBody=json.dumps(message_body)
        )
        
        print(f"SUCCESS: Sent message to OCR_QUEUE for {tender_ref}. MessageId: {response['MessageId']}")
        
    except Exception as e:
        print(f"ERROR: Failed to send message to OCR_QUEUE: {e}")

def update_tender_db(reference: str, s3_folder_key: str, s3_bucket: str):
    """
    Update the tender record in the database.
    Sets is_documents=True, s3_path, and s3_uri.
    """
    conn = get_db_connection()
    if not conn:
        print(f"Skipping DB update for {reference} due to connection failure.")
        return

    try:
        # Construct S3 URI
        s3_uri = f"s3://{s3_bucket}/{s3_folder_key}"
        
        cur = conn.cursor()
        
        sql = """
            UPDATE tenders 
            SET is_documents = TRUE,
                s3_path = %s,
                s3_uri = %s,
                updated_at = NOW()
            WHERE reference = %s
            OR REPLACE(REPLACE(REPLACE(reference, '/', '_'), ' ', '_'), '.', '_') = %s
        """
        
        # Both s3_path and s3_uri now contain the full S3 URI
        cur.execute(sql, (s3_uri, s3_uri, reference, reference))
        conn.commit()
        
        if cur.rowcount > 0:
            print(f"SUCCESS: Updated DB for tender {reference}")
        else:
            print(f"WARNING: No DB record found for tender {reference}")
            
        cur.close()
        
    except Exception as e:
        print(f"ERROR: Failed to update DB: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def sanitize_filename(filename: str) -> str:
    """
    Sanitize the filename by replacing special characters with underscores.
    Preserves file extension to maintain file type detection.
    Keeps only alphanumeric, dot, hyphen, and underscore.
    Replaces: non-ASCII, spaces, quotes, parentheses, etc. with '_'.
    """
    # Split filename into name and extension to preserve extension
    if '.' in filename:
        parts = filename.rsplit('.', 1)
        name = parts[0]
        ext = parts[1] if len(parts) > 1 else ''
    else:
        name = filename
        ext = ''
    
    # Sanitize name only
    valid_chars = "-_"
    sanitized_name = "".join([c if c.isalnum() or c in valid_chars else "_" for c in name])
    
    # Sanitize extension (keep alphanumeric only)
    sanitized_ext = "".join([c if c.isalnum() else "" for c in ext]) if ext else ""
    
    # Combine with dot if extension exists
    if sanitized_ext:
        return f"{sanitized_name}.{sanitized_ext}"
    else:
        return sanitized_name

def process_zip_file_logic(s3_bucket: str, s3_key: str, task_id: Optional[str] = None) -> Dict[str, str]:
    """
    Core logic to download, unzip, upload extracted files, and cleanup.
    Returns a dict with 'resultCode' ('Succeeded', 'TemporaryFailure', 'PermanentFailure')
    and 'resultString'.
    """
    # Use a default task_id if none provided (for S3 Events)
    if not task_id:
        task_id = "event_trigger"

    result_code = 'Succeeded'
    result_string = ''
    
    download_path = ""

    try:
        # 1. Validation: Ensure it's a zip file
        if not s3_key.lower().endswith('.zip'):
             # Treat as success but skip to avoid erroring
            return {'resultCode': 'Succeeded', 'resultString': 'Skipped: Not a zip file'}

        # 2. Setup paths
        base_name = os.path.basename(s3_key)
        zip_name_no_ext = os.path.splitext(base_name)[0]
        
        # We still need to download the main zip file to disk (Stream unzipping from S3 is possible but complex due to seek)
        download_path = f"/tmp/{base_name}"
        
        # 3. Download Zip
        print(f"Downloading {s3_bucket}/{s3_key} to {download_path}")
        s3_client.download_file(s3_bucket, s3_key, download_path)
        
        # 4. Unzip and Stream to S3
        with zipfile.ZipFile(download_path, 'r') as zip_ref:
            # Iterate through files instead of extractall to handle issues one by one
            for file_info in zip_ref.infolist():
                try:
                    # Skip directories
                    if file_info.is_dir():
                        continue
                    
                    original_filename = file_info.filename
                    
                    # Sanitize filename (Fixes ASCII and encoding issues)
                    sanitized_name = sanitize_filename(original_filename)
                    
                    # Construct Destination Key
                    # target: tenders_doc_final/<zip_name_no_ext>/<sanitized_path>
                    dest_key = f"tenders_doc_final/{zip_name_no_ext}/{sanitized_name}"
                    
                    # Stream directly to S3 (Fixes "No Space Left" and "Filename too long" on local disk)
                    # print(f"Streaming {original_filename} -> {dest_key}")
                    with zip_ref.open(file_info) as file_stream:
                        s3_client.upload_fileobj(file_stream, s3_bucket, dest_key)
                        
                except Exception as inner_e:
                    print(f"Warning: Failed to process file {file_info.filename} inside {s3_key}: {str(inner_e)}")
                    continue # Continue to next file in zip
        
        # 5. Update Database
        # Calculate the final S3 folder key
        s3_folder_final_key = f"tenders_doc_final/{zip_name_no_ext}/"
        print(f"Updating DB for {zip_name_no_ext}...")
        update_tender_db(zip_name_no_ext, s3_folder_final_key, s3_bucket)
        
        # 6. Send to OCR Queue
        print(f"Sending {zip_name_no_ext} to OCR_QUEUE...")
        send_to_ocr_queue(zip_name_no_ext, s3_folder_final_key, s3_bucket)
        
        # 7. Delete Source File from S3 (Cleanup)
        # Only if everything above succeeded
        print(f"Deleting source file {s3_bucket}/{s3_key}")
        s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
            
        result_string = f"Successfully unzipped to {s3_folder_final_key} and deleted source"

    except zipfile.BadZipFile:
        print(f"Error: Bad Zip File {s3_key}")
        result_code = 'PermanentFailure' # Do not retry corrupt files
        result_string = "Bad Zip File"
        
    except Exception as e:
        print(f"Error processing {s3_key}: {str(e)}")
        # Check for specific "Disk full" errors just in case, though streaming should fix it.
        if "No space left" in str(e):
             result_code = 'TemporaryFailure' 
        else:
             result_code = 'TemporaryFailure'
             
        result_string = str(e)
        
    finally:
        # 6. Cleanup Local Zip
        if download_path and os.path.exists(download_path):
            os.remove(download_path)

    return {
        'resultCode': result_code,
        'resultString': result_string
    }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for S3 Batch Operations AND S3 Event Notifications.
    """
    print("Received event:", event)

    # CASE A: S3 Batch Operations
    if 'tasks' in event:
        tasks = event.get('tasks', [])
        results: List[Dict[str, Any]] = []

        for task in tasks:
            task_id = task['taskId']
            s3_key = urllib.parse.unquote_plus(task['s3Key'])
            s3_bucket_arn = task['s3BucketArn']
            s3_bucket = s3_bucket_arn.split(':::')[-1]
            
            # Call core logic
            process_result = process_zip_file_logic(s3_bucket, s3_key, task_id)
            
            results.append({
                'taskId': task_id,
                'resultCode': process_result['resultCode'],
                'resultString': process_result['resultString']
            })

        return {
            'invocationSchemaVersion': event['invocationSchemaVersion'],
            'treatMissingKeysAs': 'PermanentFailure',
            'invocationId': event['invocationId'],
            'results': results
        }

    # CASE B: S3 Event Notifications
    elif 'Records' in event:
        for record in event['Records']:
            # Ensure it's an S3 event
            if 's3' in record:
                s3_bucket = record['s3']['bucket']['name']
                s3_key = urllib.parse.unquote_plus(record['s3']['object']['key'])
                
                # Call core logic (Ignore return value for events, just log it)
                result = process_zip_file_logic(s3_bucket, s3_key, task_id="event")
                print(f"Processing result for {s3_key}: {result}")
        
        return {'statusCode': 200, 'body': 'Event processed'}
    
    else:
        print("Unknown event structure")
        return {'statusCode': 400, 'body': 'Unknown event structure'}
