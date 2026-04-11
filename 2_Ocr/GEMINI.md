# 2_Ocr: OCR & Text Extraction Service

This container handles the **second stage** of the pipeline: consuming tender documents from S3, performing OCR using Docling, converting to Markdown, and uploading back to S3.

## Purpose

- **Poll** SQS queue for new tenders (from 1_Update)
- **Download** raw documents (PDFs, DOCs, images) from S3
- **Extract** text using Docling (PyTorch/Transformers-based OCR)
- **Convert** documents to Markdown format (UTF-8, concatenated)
- **Upload** markdown back to S3
- **Route** to 3_Classification queue for downstream processing
- **Track** progress via the shared `monitor` module.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop. Polls OCR_QUEUE, orchestrates processing |
| `document_processor.py` | Docling integration. Handles PDF/DOC → Markdown conversion |
| `s3_utils.py` | S3 client for downloading source docs, uploading markdown |
| `sqs_utils.py` | SQS client for queue polling and message deletion |
| `monitor.py` | (Symlink) Event emitter for pipeline tracking. |
| `config.py` | Configuration loader (env vars for queue URLs, S3 paths, etc.) |
| `logger.py` | Logging setup with structured output |
| `Dockerfile` | CPU-optimized container (no GPU) |

## Monitoring Integration

This stage emits events to `pipeline.db` using the `monitor` module:
- `enter`: Called when a tender starts OCR processing.
- `complete`: Called when markdown is successfully uploaded.
- `failed`: Called on any processing or S3 error.

## Workflow

```
SQS Input (OCR_QUEUE)
  Message format: { "tender_ref": "AO_123_2024", "batch_id": "..." }
  ↓
OCRService processes:
  - Download raw docs from S3: tender_doc_final/{tender_ref}/*.pdf
  - Process with Docling (extract text, detect tables, images)
  - Concatenate markdown files
  - Upload to S3: markdown_tender/{tender_ref}/concatenated.md
  ↓
SQS Output (CLASSIFICATION_QUEUE)
```

## Local Development

### Setup
```bash
cd 2_Ocr
pip install -r requirements.txt
```

### Commands
```bash
python main.py
```

## Configuration

| Variable | Purpose |
|---|---|
| `OCR_QUEUE_URL` | Input queue URL |
| `CLASSIFICATION_QUEUE_URL` | Output queue URL |
| `S3_BUCKET_NAME` | S3 bucket name |
| `DOCLING_CACHE_DIR` | Directory for model weights |

## Performance Notes

- **Per-document time**: 30-120s depending on PDF complexity.
- **Memory**: ~2-4GB per large PDF processing.
- **Cleanup**: Temp files are removed after each tender is processed.
