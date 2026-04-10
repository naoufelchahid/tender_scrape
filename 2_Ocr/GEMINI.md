# 2_Ocr: OCR & Text Extraction Service

This container handles the **second stage** of the pipeline: consuming tender documents from S3, performing OCR using Docling, converting to Markdown, and uploading back to S3.

## Purpose

- **Poll** SQS queue for new tenders (from 1_Update)
- **Download** raw documents (PDFs, DOCs, images) from S3
- **Extract** text using Docling (PyTorch/Transformers-based OCR)
- **Convert** documents to Markdown format (UTF-8, concatenated)
- **Upload** markdown back to S3
- **Route** to 3_Classification queue for downstream processing

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop. Polls OCR_QUEUE, orchestrates processing |
| `document_processor.py` | Docling integration. Handles PDF/DOC → Markdown conversion |
| `s3_utils.py` | S3 client for downloading source docs, uploading markdown |
| `sqs_utils.py` | SQS client for queue polling and message deletion |
| `config.py` | Configuration loader (env vars for queue URLs, S3 paths, etc.) |
| `logger.py` | Logging setup with structured output |
| `Dockerfile` | CPU-optimized container (no GPU) |
| `docker-compose.yml` | Local development orchestration (includes Jena for testing) |

## Queue Structure

```
SQS Input (OCR_QUEUE)
  Message format: { "tender_ref": "AO_123_2024", ... }
  ↓
OCRService processes:
  - Download raw docs from S3: tender_doc_final/{tender_ref}/*.pdf
  - Process with Docling (extract text, detect tables, images)
  - Concatenate markdown files
  - Upload to S3: markdown_tender/{tender_ref}/concatenated.md
  ↓
SQS Output (CLASSIFICATION_QUEUE)
  Message routed to 3_Classification
```

## Local Development

### Setup
```bash
cd 2_Ocr
pip install -r requirements.txt
```

### Environment Variables (`.env`)
```bash
# AWS credentials
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-west-3

# SQS Queue URLs
OCR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../ocr-queue
CLASSIFICATION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../classification-queue

# S3
S3_BUCKET_NAME=tender-scrape-data
MARKDOWN_PREFIX=markdown_tender/

# Docling
DOCLING_CACHE_DIR=/tmp/docling_cache
```

### Running Locally

**Start OCR service (polls SQS):**
```bash
python main.py
# Logs to stdout + ocr_service.log
# Processes one message at a time, cleans up temp files after each tender
```

**Docker Compose (local testing with Jena):**
```bash
docker-compose up
# Starts OCR service + Jena Fuseki for integration testing
# Logs available via: docker-compose logs -f ocr
```

**Docker Build Only:**
```bash
docker build -t tender-scrape-ocr:latest .
docker run --env-file .env tender-scrape-ocr:latest
```

## Testing & Validation

### Smoke Tests
```bash
# Test Docling import and initialization
python -c "from document_processor import DocumentProcessor; p = DocumentProcessor(); print('OK')"

# Test S3 connectivity
python -c "from s3_utils import S3Client; s3 = S3Client(); buckets = s3.list_buckets(); print(f'Buckets: {len(buckets)}')"

# Test SQS connectivity
python -c "from sqs_utils import SQSClient; sqs = SQSClient(); print(sqs.get_queue_attributes())"
```

### Testing with Local Documents
```bash
# Create a test PDF in temp directory
# Edit main.py to hardcode a tender_ref instead of polling SQS
# Set test_mode=true in config or skip SQS polling
# Run: python main.py
```

## Code Patterns

### SQS Consumer Loop (main.py)
```python
while True:
    try:
        response = sqs.receive_message(QueueUrl=OCR_QUEUE_URL, MaxNumberOfMessages=1, WaitTimeSeconds=20)
        if 'Messages' not in response:
            continue
        for message in response['Messages']:
            process_message(message)
            sqs.delete_message(QueueUrl=OCR_QUEUE_URL, ReceiptHandle=message['ReceiptHandle'])
    except Exception as e:
        logger.error(f"Error: {e}")
        time.sleep(5)
```

### Docling Processing (document_processor.py)
- Initializes `DocumentConverter` from Docling
- Converts each document to markdown using table + image detection
- Handles large PDFs with streaming
- Returns UTF-8 encoded markdown

### S3 Upload
- Downloads source documents from `tender_doc_final/{tender_ref}/`
- Processes all files (concatenates markdown)
- Uploads result to `markdown_tender/{tender_ref}/concatenated.md`
- Handles missing files gracefully (skips, logs)

## Debugging

### OCR Hangs or Timeouts
- Docling can be slow on large PDFs (GPU would help, but disabled for cost)
- Check `DocumentProcessor` initialization in `document_processor.py`
- Monitor system memory: `free -h`
- Increase timeout in `config.py` if needed

### Markdown Extraction Quality Issues
- Verify Docling version in `requirements.txt`
- Test on a sample document locally
- Check for encoding issues: `file -i {output}.md` should show UTF-8
- Review Docling logs: enable `logging.DEBUG` in `logger.py`

### S3 Upload Errors
- Check AWS credentials and region match bucket location
- Verify S3 path permissions
- Confirm bucket exists: `aws s3 ls s3://tender-scrape-data/markdown_tender/`

### Queue Message Processing Failures
- On error, message returns to queue (visibility timeout)
- Check SQS DLQ for poison messages (max retry exceeded)
- Verify queue URL in `.env` is correct
- Monitor queue depth: `aws sqs get-queue-attributes --queue-url ... --attribute-names ApproximateNumberOfMessages`

## Integration Points

- **Input SQS**: OCR_QUEUE (from 1_Update)
- **Input S3**: Raw documents at `tender_doc_final/{tender_ref}/`
- **Output S3**: Markdown at `markdown_tender/{tender_ref}/concatenated.md`
- **Output SQS**: CLASSIFICATION_QUEUE (to 3_Classification)
- **Dependencies**: Docling (PyTorch/Transformers), boto3, SQS polling

## Performance Notes

- **Per-document time**: 30-120s depending on PDF complexity (CPU-bound, no GPU)
- **Memory**: ~2-4GB per large PDF processing
- **Optimization**: Documents are processed sequentially; no concurrent processing (single SQS consumer)
- **Temp cleanup**: Automatic after each tender (see `_cleanup_temp_files`)

## Deployment

### AWS ECS
```bash
cd 2_Ocr
./deploy_to_ecs.sh
# Builds image, pushes to ECR, updates ECS task definition
# Task runs indefinitely, polling SQS queue
```

### Container Specs (from ECS)
- **CPU**: 2 vCPU (CPU-only, no GPU)
- **Memory**: 8 GB
- **Image**: AWS ECR (via deploy script)

## Common Tasks

### Increasing Document Processing Timeout
1. Edit `config.py`, increase `DOCLING_TIMEOUT` (seconds)
2. Also update SQS visibility timeout in `sqs_utils.py`
3. Rebuild and redeploy

### Changing Output Markdown Format
1. Edit `document_processor.py`, modify markdown generation logic
2. Test with a sample document
3. Ensure UTF-8 encoding is preserved

### Monitoring Queue Depth
```bash
# Check approximate messages waiting
aws sqs get-queue-attributes \
  --queue-url $OCR_QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages
```

## Related Documentation

- **Root CLAUDE.md**: Pipeline architecture, SQS message contracts
- **3_Classification/CLAUDE.md**: Downstream classification stage
- **Memory**: `pipeline_operations.md`, `pipeline_fixes_2026-03-31.md`
