# Extraction Container - Build and Deploy Guide

## Issues Fixed
1. ✅ Added `tender_id` lookup from database if not provided in SQS message
2. ✅ Fixed PydanticOutputParser for List type (wrapped in ProductList model)
3. ✅ Added database models copy to Dockerfile
4. ✅ Added validation for empty metadata context
5. ✅ Created `src/__init__.py` for proper package structure
6. ✅ Improved error handling and logging

## Build Instructions

```bash
cd /home/naoufel/projects/AO_scrape/extraction_container

# Build Docker image
docker build -t extraction-container:latest .

# Test locally (with env vars)
docker run --env-file ../.env extraction-container:latest
```

## Environment Variables Required

```
EXTRACTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/...
VECTOR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/...
S3_BUCKET_NAME=my-tender-documents-bucket
AWS_REGION=eu-west-3
DB_URL=postgresql://user:pass@host:5432/dbname
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

## Remaining TODOs
- [ ] Test with real OCR output
- [ ] Tune LLM prompts for better extraction accuracy
- [ ] Add retry logic for DB connection failures
- [ ] Implement status transition rule (in_progress -> awarded based on deadline)
- [ ] Add monitoring/CloudWatch metrics
