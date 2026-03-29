# OCR Docker Container

Container for high-fidelity OCR processing of tender documents using [Docling](https://github.com/DS4SD/docling).
Converts PDF, DOCX, XLSX, and image files to **GraphRAG-optimized Markdown** with strict hierarchy and table preservation.

## Features

- **Unified Pipeline**: Single `DocumentProcessor` handles all supported formats.
- **Docling Integration**: State-of-the-art document layout analysis and OCR.
- **GraphRAG Optimized**: Output enforces `# Title`, `## Section` hierarchy and strips headers/footers/page numbers.
- **Metadata Enrichment**: Every output file includes YAML frontmatter.
- **Table Extraction**: High-fidelity table conversion to Markdown pipes.
- **SQS Integration**: Polls `OCR_QUEUE` for new tenders, sends completion to `EXTRACTION_QUEUE`.

## Architecture

```
SQS OCR_QUEUE → Container [Docling Engine] → S3 markdown_tender/ → SQS EXTRACTION_QUEUE
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

### 2. Build Docker Image

```bash
docker-compose build
```

### 3. Run Container

**Using Docker Compose:**

```bash
docker-compose up -d
```

## Supported Formats

| Format | Backend | Features |
| :--- | :--- | :--- |
| **PDF** | Docling (PyPdfium2 + OCR) | Text layer extraction, OCR for scans, Table structure analysis |
| **DOCX** | Docling | Text, Tables, Hierarchy preservation |
| **XLSX** | Docling | Sheet-to-Table conversion |
| **Image**| Docling | OCR (Tesseract/EasyOCR via Docling) |

## SQS Message Format

### Input (OCR_QUEUE)

```json
{
  "tender_ref": "REF123",
  "s3_paths": [
    "final_doc_tender/REF123/document1.pdf",
    "final_doc_tender/REF123/specs.docx"
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

## Output Format

All generated Markdown files start with YAML frontmatter:

```markdown
---
filename: document1.pdf
file_type: pdf
processed_at: 2024-01-01T12:00:00
---

# Title of Document

## Section 1
Content...

| Table | Header |
|-------|--------|
| Row   | Data   |
```

## Development

### Local Testing

1. Create `.env` with valid credentials.
2. Run with docker-compose: `docker-compose up`.
3. Send test message to `OCR_QUEUE`.
4. Monitor logs and S3 output.

### Testing Locally (Python)

```python
from document_processor import DocumentProcessor

processor = DocumentProcessor()
markdown = processor.process("/path/to/local/file.pdf")
print(markdown)
```
