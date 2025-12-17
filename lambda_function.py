import boto3
import urllib.parse
import zipfile
import os
import shutil
from typing import List, Dict, Any, Optional

s3_client = boto3.client('s3')

def sanitize_filename(filename: str) -> str:
    """
    Sanitize the filename by replacing special characters with underscores.
    Keeps only alphanumeric, dot, hyphen, and underscore.
    Replaces: non-ASCII, spaces, quotes, parentheses, etc. with '_'.
    """
    # Whitelist: Alphanumeric, dot, hyphen, underscore. Everything else -> underscore
    valid_chars = "-_"
    sanitized = "".join([c if c.isalnum() or c in valid_chars else "_" for c in filename])
    return sanitized

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
        
        # 5. Delete Source File from S3 (Cleanup)
        # Only if everything above succeeded
        print(f"Deleting source file {s3_bucket}/{s3_key}")
        s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
            
        result_string = f"Successfully unzipped to tenders_doc_final/{zip_name_no_ext}/ and deleted source"

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
