#!/bin/bash

# Configuration
BUCKET_NAME="my-tender-documents-bucket"
PREFIX="tenders_doc_final"
QUEUE_URL="https://sqs.eu-west-3.amazonaws.com/034791378578/OCR_QUEUE"
REGION="eu-west-3"

echo "Fetching folders from S3..."

# List all folders (simulated by listing objects and extracting prefixes)
# We use a python one-liner to parse the s3 ls output safely if awk is tricky, but awk works for standard output
folders=$(aws s3 ls s3://$BUCKET_NAME/$PREFIX/ | awk '{print $2}' | sed 's/\///g')

count=0
echo "Found folders. Preparing to send messages..."

for folder in $folders; do
    echo "Processing: $folder"
    
    # 1. List files in folder
    # We want only supported files
    files=$(aws s3 ls s3://$BUCKET_NAME/$PREFIX/$folder/ | awk '{print $4}' | grep -E '\.(pdf|docx|doc|xlsx|xls|jpeg|jpg|png)$')
    
    if [ -z "$files" ]; then
        echo "No supported files in $folder"
        continue
    fi
    
    # 2. Build JSON structure
    # This uses jq to build the JSON object properly
    json_payload=$(jq -n \
                  --arg ref "$folder" \
                  --arg pfx "$PREFIX/$folder" \
                  --arg bucket "$BUCKET_NAME" \
                  --argjson files_list "$(echo "$files" | jq -R . | jq -s .)" \
                  '{
                    tender_ref: $ref,
                    s3_paths: ($files_list | map($pfx + "/" + .)),
                    file_types: ($files_list | map(split(".")[-1] | ascii_downcase))
                  }')
                  
    # 3. Send to SQS
    echo "$json_payload" > /tmp/payload.json
    
    aws sqs send-message \
        --queue-url "$QUEUE_URL" \
        --region "$REGION" \
        --message-body "file:///tmp/payload.json" > /dev/null
        
    echo "✅ Queued $folder"
    count=$((count+1))
    
    # Clean up
    rm /tmp/payload.json
done

echo "----------------------------------------"
echo "🎉 Successfully queued $count tenders!"
