# Results OCR Container

Intelligent OCR processing container for tender result documents. Monitors S3 for new PDFs and DOCX files, processes them with text layer detection, and outputs structured markdown.

## Features

- **Intelligent PDF Processing**: Automatically detects PDF text layers and chooses the optimal extraction method
  - Direct text extraction for text-layer PDFs (fast!)
  - OCR with Groq API for scanned PDFs
- **Multi-Format Support**: PDF, DOCX, DOC
- **Multi-Model Fallback**: Primary (Llama 4 Scout) → Fallback (Llama 4 Maverick) → OpenRouter
- **Parallel Processing**: Concurrent OCR for multi-page PDFs
- **Table Preservation**: Maintains table structure in markdown output
- **Message-Based Processing**: Polls RESULTS_QUEUE for event-driven processing
- **Structured Data Extraction**: Extracts bidder information, amounts, and rejection reasons
- **Dual Output**: Generates both markdown and JSON files
  - Markdown: Human-readable results
  - JSON: Structured data for database population
- **Auto-Cleanup**: Deletes processed source files

## Architecture

**Pipeline Stage**: Extraction Container - OCR Processing

**Data Flow**:

1. Receive message from RESULTS_QUEUE (SQS)
2. Download files listed in message
3. Process with appropriate method (direct extraction or OCR)
4. Extract structured data using Groq API
5. Upload markdown to `s3://bucket/Results_markdown/{tender_ref}.md`
6. Upload JSON to `s3://bucket/Results_markdown/Results_{tender_ref}.json`
7. Delete source files (optional)

## Configuration

All configuration is done via environment variables. Copy `.env.example` to `.env` and configure:

```bash
# Required
S3_BUCKET_NAME=your-bucket-name
GROQ_API_KEY=your-groq-api-key
RESULTS_QUEUE_URL=https://sqs.REGION.amazonaws.com/ACCOUNT_ID/RESULTS_QUEUE

# Optional
PRIMARY_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
FALLBACK_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct
MAX_WORKERS=5
DELETE_SOURCE_FILES=true
```

## Usage

### Using Docker Compose (Recommended)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 2. Build and run
docker-compose up --build

# View logs
docker-compose logs -f results_ocr
```

### Using Docker

```bash
# Build
docker build -t results-ocr-container .

# Run
docker run -d \
  --name results-ocr \
  --env-file .env \
  results-ocr-container
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

## Processing Methods

### PDF with Text Layer

- **Detection**: Uses pdfplumber to sample pages and detect extractable text
- **Processing**: Direct text extraction with table preservation
- **Speed**: ~2-5 seconds per document
- **Cost**: Free (no API calls)

### Scanned PDF

- **Detection**: No text layer or low confidence score
- **Processing**: Converts to images → Groq API OCR
- **Speed**: ~10-20 seconds per page (concurrent processing)
- **Cost**: Groq API usage

### DOCX/DOC

- **Processing**: Direct text and table extraction
- **Speed**: ~1-2 seconds per document
- **Cost**: Free

## Output Format

Markdown files are saved to `Results_markdown/` with the following structure:

```markdown
## Page 1

[Extracted content...]

### Table 1

| Company Name | Proposed Amount | Status | Notes |
|--------------|----------------|--------|-------|
| Company A    | 1,000,000 MAD  | Winner | -     |
| Company B    | 1,200,000 MAD  | Excluded | ... |

---

## Page 2

[...]
```

## Logging

Logs include:

- File detection and processing status
- Text layer detection results
- OCR progress for each page
- S3 operations (download/upload/delete)
- Processing time and method used
- Errors and warnings

Example log output:

```
2026-01-12 10:30:00 - results_ocr - INFO - ================================================================================
2026-01-12 10:30:00 - results_ocr - INFO - Processing: results_lambda_ocr/result_123_2025.pdf
2026-01-12 10:30:00 - results_ocr - INFO - ================================================================================
2026-01-12 10:30:01 - results_ocr - INFO - ☁️  S3 DOWNLOAD: results_lambda_ocr/result_123_2025.pdf
2026-01-12 10:30:01 - results_ocr - INFO - 📄 Processing PDF: result_123_2025.pdf
2026-01-12 10:30:01 - results_ocr - INFO - Checking for text layer...
2026-01-12 10:30:02 - results_ocr - INFO - ✅ Text layer detected (confidence: 1.00) - /tmp/results_ocr/result_123_2025.pdf
2026-01-12 10:30:02 - results_ocr - INFO - ✅ Text layer detected (confidence: 1.00)
2026-01-12 10:30:02 - results_ocr - INFO - Using direct text extraction (no OCR needed)
2026-01-12 10:30:04 - results_ocr - INFO - ✅ Completed PDF: result_123_2025.pdf (3 pages, 2.1s, method: direct_extraction)
2026-01-12 10:30:04 - results_ocr - INFO - ☁️  S3 UPLOAD: Results_markdown/result_123_2025.md
2026-01-12 10:30:05 - results_ocr - INFO - ☁️  S3 DELETE: results_lambda_ocr/result_123_2025.pdf
2026-01-12 10:30:05 - results_ocr - INFO - ✅ Successfully processed: results_lambda_ocr/result_123_2025.pdf
```

## Monitoring

Check container health:

```bash
# Docker Compose
docker-compose ps
docker-compose logs -f results_ocr

# Docker
docker ps | grep results-ocr
docker logs -f results-ocr
```

## Troubleshooting

### No files being processed

- Check S3 bucket permissions
- Verify `INPUT_PREFIX` configuration
- Check AWS credentials

### OCR failing

- Verify Groq API key is valid
- Check API rate limits
- Review model availability

### High memory usage

- Reduce `MAX_WORKERS` for parallel processing
- Lower `PDF_DPI` (default: 300)

## Project Structure

```
results_ocr_container/
├── main.py                    # Main service orchestration
├── config.py                  # Configuration management
├── logger.py                  # Logging utilities
├── s3_poller.py              # S3 monitoring service
├── document_processor.py      # Document processing orchestrator
├── ocr_service.py            # Groq API OCR service
├── text_layer_detector.py    # PDF text layer detection
├── prompts.py                # Tender-specific prompts
├── utils/
│   ├── pdf_utils.py          # PDF utilities
│   └── docx_utils.py         # DOCX utilities
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Development

### Adding New Models

Edit `config.py`:

```python
PRIMARY_MODEL = 'new-model-name'
FALLBACK_MODEL = 'fallback-model-name'
```

### Customizing Prompts

Edit `prompts.py` to modify extraction instructions.

### Testing

```bash
# Upload a test file
aws s3 cp test_document.pdf s3://{bucket}/results_lambda_ocr/

# Monitor logs
docker-compose logs -f

# Verify output
aws s3 ls s3://{bucket}/Results_markdown/
aws s3 cp s3://{bucket}/Results_markdown/test_document.md -
```

## License

Part of the AO_scrape project.
