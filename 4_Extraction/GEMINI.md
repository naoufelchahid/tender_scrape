# 4_Extraction: Structured Data Extraction Service

This container handles the **fourth stage** of the pipeline: consuming classified markdown documents, decomposing into structured JSON chunks, and preparing for knowledge graph ingestion.

## Purpose

- **Poll** SQS queue for classified documents (from 3_Classification)
- **Download** markdown with document-type headers from S3
- **Chunk** documents into logical sections using heuristics
- **Extract** structured data (tender info, product details, pricing) using LLMs
- **Validate** extracted data against Pydantic models
- **Upload** JSON chunks to S3
- **Route** to 5_Ingestion queue for RDF conversion
- **Track** status via the shared `monitor` module.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop and stage orchestration. |
| `src/document_chunker.py` | Core extraction logic using LLM + heuristics. |
| `monitor.py` | (Symlink) Event emitter for pipeline tracking. |
| `src/models.py` | Pydantic v2 models for data validation. |
| `src/prompts.py` | Few-shot prompts for structured extraction. |
| `src/openrouter_wrapper.py` | API client for LLM calls (DeepSeek). |

## Monitoring Integration

This stage emits events to `pipeline.db` using the `monitor` module:
- `enter`: Called when chunking/extraction starts.
- `complete`: Called when JSON chunks are uploaded to S3.
- `failed`: Called on LLM failures or validation errors.

## Data Flow

```
SQS Input (EXTRACTION_QUEUE)
  ↓
Download markdown (markdown_tender/{tender_ref}.md)
  ↓
Split into chunks based on headers and line patterns
  ↓
LLM Extraction (Structured JSON)
  ↓
Pydantic Validation (TenderAvis, Product, Lot)
  ↓
Upload to S3 (extracted_json/{tender_ref}/)
  ↓
SQS Output (DB_FILLER_QUEUE)
```

## Local Development

### Setup
```bash
cd 4_Extraction
pip install -r requirements.txt
```

### Commands
```bash
python main.py
```

## Configuration

| Variable | Purpose |
|---|---|
| `EXTRACTION_QUEUE_URL` | Input queue URL |
| `DB_FILLER_QUEUE_URL` | Output queue URL |
| `OPENROUTER_API_KEY` | Key for LLM extraction |
| `S3_BUCKET_NAME` | S3 bucket name |
