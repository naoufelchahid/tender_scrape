# OCR Docker Container

Docker container for OCR processing of tender documents. Converts PDF, DOCX, XLSX, and image files to structured Markdown using OpenRouter API with Llama 4 models.

## Features

- **Multi-format Support**: PDF, DOCX, XLSX, JPEG, PNG
- **Language Detection**: Automatic Arabic detection with routing to Bedrock Nova Lite
- **Table Preservation**: High-quality table conversion to markdown
- **SQS Integration**: Polls OCR_QUEUE for new tenders, sends to EXTRACTION_QUEUE on completion
- **Batch Processing**: Script to process existing S3 tenders
- **S3 Storage**: Downloads from `final_doc_tender/`, uploads to `markdown_tender/`

## Architecture

```
SQS OCR_QUEUE → Container → S3 markdown_tender/ → SQS EXTRACTION_QUEUE
```

## Setup

### 1. Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required variables:

- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `S3_BUCKET_NAME`
- `OCR_QUEUE_URL`, `EXTRACTION_QUEUE_URL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_APP_NAME` (optional)

### 2. Build Docker Image

```bash
docker build -t ocr-service .
```

### 3. Run Container

**Using Docker Compose (recommended for local testing):**

```bash
docker-compose up
```

**Using Docker directly:**

```bash
docker run --env-file .env ocr-service
```

## File Processors

### PDF Processor

- Converts PDF pages to images (300 DPI)
- Detects if PDF has extractable text layer
- If text layer exists: Direct extraction (fast, no API calls)
- If scanned: Routes to OpenRouter with Llama 4 models
- Parallel processing for speed (10 workers)
- Preserves layout and tables
- Optional table enhancement

### DOCX Processor

- Extracts text with python-docx
- Converts tables to markdown
- Preserves headings and structure

### XLSX Processor

- Processes all sheets with pandas
- Converts to markdown tables
- Preserves numeric formatting

### Image Processor

- Detects language from image
- Routes to OpenRouter API
- Extracts all visible text
- Supports Arabic, French, English

## Batch Processing

Process existing tenders in S3:

```bash
# Dry run (no messages sent)
python batch_processor.py --dry-run

# Process first 10 tenders
python batch_processor.py --limit 10

# Process all unprocessed tenders
python batch_processor.py
```

## SQS Message Format

### Input (OCR_QUEUE)

```json
{
  "tender_ref": "REF123",
  "s3_paths": [
    "final_doc_tender/REF123/document1.pdf",
    "final_doc_tender/REF123/document2.xlsx"
  ]
}
```

### Output (EXTRACTION_QUEUE)

```json
{
  "tender_ref": "REF123",
  "markdown_paths": [
    "markdown_tender/REF123/REF123_ocr.md"
  ]
}
```

## Logging

Structured JSON logs for CloudWatch:

```json
{
  "timestamp": "2025-12-31T12:00:00Z",
  "level": "INFO",
  "message": "Processing PDF: document.pdf",
  "tender_ref": "REF123",
  "file_type": "pdf",
  "processing_time": 45.2
}
```

## Error Handling

- **Retry Logic**: Failed messages return to queue via visibility timeout
- **Dead Letter Queue**: Messages failing 3+ times go to OCR_DLQ
- **Graceful Degradation**: Bedrock failures fall back to OpenRouter
- **Partial Success**: Processes all files even if some fail

## Development

### Local Testing

1. Create `.env` with valid credentials
2. Run with docker-compose: `docker-compose up`
3. Send test message to OCR_QUEUE
4. Monitor logs and S3 output

### Testing Individual Processors

```python
from processors.pdf_processor import process_pdf

markdown = process_pdf('/path/to/test.pdf', document_type='CPS')
print(markdown)
```

## Monitoring

- **CloudWatch Logs**: All container output
- **SQS Metrics**: Message count, age, DLQ depth
- **S3 Structure**: Verify markdown files in correct paths

## Production Deployment

1. Build and tag image:

   ```bash
   docker build -t ocr-service:v1.0 .
   ```

2. Push to ECR:

   ```bash
   docker tag ocr-service:v1.0 <account>.dkr.ecr.us-east-1.amazonaws.com/ocr-service:v1.0
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/ocr-service:v1.0
   ```

3. Deploy to ECS/EKS with appropriate IAM role for S3, SQS, Bedrock access

## Troubleshooting

**Issue**: Container can't find credentials

- **Solution**: Ensure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set

**Issue**: Poppler not found error

- **Solution**: Rebuild image (poppler-utils installed in Dockerfile)

**Issue**: Arabic text not detected

- **Solution**: Check Tesseract Arabic language pack installed (tesseract-ocr-ara)

**Issue**: Messages not being deleted

- **Solution**: Check processing is successful and visibility timeout is adequate
