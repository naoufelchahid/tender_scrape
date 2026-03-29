import json
import os

def mock_handle_parsing(body_str):
    print(f"Parsing body: {body_str!r}")
    try:
        # Try JSON loading first
        try:
            body = json.loads(body_str)
            print("Successfully parsed as JSON")
        except json.JSONDecodeError:
            print("JSON parsing failed, trying S3 URI fallback")
            # Fallback: check if it's a plain S3 URI string
            if body_str.startswith('s3://'):
                # Extract tender_ref from path: s3://bucket/markdown_tender/REF/file.md
                parts = body_str.replace('s3://', '').split('/')
                if len(parts) >= 4 and parts[1] == 'markdown_tender':
                    tender_ref = parts[2]
                else:
                    tender_ref = os.path.splitext(os.path.basename(body_str))[0]
                
                body = {
                    'markdown_key': body_str.replace('s3://my-tender-documents-bucket/', ''), # Simulating bucket name
                    'tender_ref': tender_ref
                }
                print(f"Fallback extracted: tender_ref={tender_ref}, key={body['markdown_key']}")
            else:
                raise

        tender_ref = body.get('tender_ref')
        markdown_key = body.get('markdown_key')
        
        print(f"Final extracted: tender_ref={tender_ref}, markdown_key={markdown_key}")
        return body
    except Exception as e:
        print(f"Error parsing: {e}")
        return None

# Test 1: Plain S3 URI
print("--- Test 1: Plain S3 URI ---")
mock_handle_parsing("s3://my-tender-documents-bucket/markdown_tender/003_2026_SRMCS_SOCREGMULCASSETSA/003_2026_SRMCS_SOCREGMULCASSETSA.md")

# Test 2: JSON
print("\n--- Test 2: JSON ---")
mock_handle_parsing('{"tender_ref": "REF123", "markdown_key": "path/msg.md"}')

# Test 3: Empty string (what might be happening if SQS body is empty)
print("\n--- Test 3: Empty string ---")
mock_handle_parsing("")
