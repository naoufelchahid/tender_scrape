# 3_Classification: Document Classification Service

This container handles the **third stage** of the pipeline: classifying markdown documents by type, injecting document-type headers, detecting missing documents, and routing for extraction.

## Purpose

- **Poll** SQS queue for markdown documents (from 2_Ocr)
- **Classify** documents using 3-step methodology (patterns → content → AI)
- **Detect Missing Documents** by searching entire markdown for types not yet found
- **Inject** document-type headers into markdown for downstream processing
- **Route** classified documents to 4_Extraction queue
- **Track** events via the shared `monitor` module.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop and stage orchestration. |
| `src/classifier.py` | Core classification logic (3-step process). |
| `monitor.py` | (Symlink) Event emitter for pipeline tracking. |
| `README.md` | Detailed classification methodology. |
| `Dockerfile` | Container image definition. |

## Monitoring Integration

This stage emits events to `pipeline.db` using the `monitor` module:
- `enter`: Called when classification starts for a tender.
- `complete`: Called when markdown headers are injected and uploaded.
- `failed`: Called on classification errors or API failures.

## Classification Methodology

1. **Step 1: High-Confidence Patterns**: Filename regex + content validation.
2. **Step 2: Content Analysis**: Keyword density analysis for documents that failed Step 1.
3. **Step 3: AI Fallback**: LLM-based classification using OpenRouter (DeepSeek).
4. **Step 4: Missing Doc Detection**: Post-scan of entire markdown for expected blocks (e.g., declarations).

## Local Development

### Setup
```bash
cd 3_Classification
pip install -r requirements.txt
```

### Commands
```bash
python main.py
```

## Configuration

| Variable | Purpose |
|---|---|
| `CLASSIFICATION_QUEUE_URL` | Input queue URL |
| `EXTRACTION_QUEUE_URL` | Output queue URL |
| `OPENROUTER_API_KEY` | Key for Step 3 AI classification |
| `S3_BUCKET_NAME` | S3 bucket name |
