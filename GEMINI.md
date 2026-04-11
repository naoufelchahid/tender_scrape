# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tender Scrape** is a sophisticated multi-stage, event-driven data processing pipeline for scraping, processing, and ingesting Moroccan public procurement tenders into a semantic Knowledge Graph. The pipeline uses AWS SQS for inter-stage queueing and S3 for distributed document storage.

**Purpose**: Automate the extraction of structured tender data from documents, validate quality, and persist to Apache Jena triple store with vector embeddings.

## Architecture at a Glance

### Main Pipeline
```
1_Update (Scraping) → S3 + SQS
  ↓
2_Ocr (OCR/Text Extraction) → Markdown in S3 + SQS
  ↓
3_Classification (Document Classification) → Classified Markdown + SQS
  ↓
4_Extraction (Structured Data Extraction) → JSON Chunks in S3 + SQS
  ↓
5_Ingestion (Knowledge Graph) → Apache Jena + Vector Index
```

### Results Pipeline (Post-Deadline)
```
6_Result_Update (Scrape PVs) → S3 + SQS
  ↓
7_Result_scrape (OCR Results) → Markdown in S3 + SQS
  ↓
8_Result_Ingestion (Result Ingestion) → Apache Jena (Local LLM/Ollama)
```

## Pipeline Stages

1. **1_Update** — Web scraper using Playwright/BeautifulSoup. Navigates marchespublics.gov.ma, extracts tender metadata (reference, buyer, categories, deadlines, lots), and downloads ZIP files. Uploads raw documents and JSON metadata to S3, posts tender references to SQS.

2. **2_Ocr** — SQS consumer polling for new tenders. Uses Docling (PyTorch/Transformers) to perform OCR and convert PDFs/documents into Markdown. Outputs concatenated markdown files to S3.

3. **3_Classification** — SQS consumer implementing 3-step document classification: (Step 1) filename + regex patterns for high-confidence classification, (Step 2) content analysis for unknowns, (Step 3) LLM fallback (OpenRouter). Injects document-type headers into markdown, posts to extraction queue.

4. **4_Extraction** — SQS consumer. Uses LLMs and `DocumentChunker` heuristics to decompose classified documents into smaller, structured JSON chunks suitable for vectorization and semantic mapping. Routes to ingestion queue.

5. **5_Ingestion** — Final SQS consumer for the initial tender data. Orchestrates: tender enrichment from S3 → JSON-to-RDF mapping → SHACL validation → SPARQL insertion to Jena → concurrent embedding generation → vector storage in S3.

6. **6_Result_Update** — Periodic service that identifies tenders past their deadline in Jena, scrapes the procurement portal for result PVs (Procès-Verbaux), uploads them to S3, and triggers the results OCR queue.

7. **7_Result_scrape** — Specialized OCR service for result documents. Converts PV PDFs into structured markdown, detecting winning bidders, excluded bidders, and award amounts.

8. **8_Result_Ingestion** — Local-first ingestion service using Ollama (DeepSeek-R1) for structured extraction from PV markdown. Maps results to RDF, validates against shapes, and enriches the Knowledge Graph with winner and award information.

## Monitoring & Reporting

The pipeline includes a robust monitoring system to track tenders through all stages:
- **monitor.py**: Shared event emitter that writes stage transitions, completions, and failures to a local `pipeline.db` (SQLite).
- **reporter.py**: CLI tool that polls `pipeline.db` to generate batch reports and live progress tracking.
- **monitor_anomalies.py**: Service for detecting unexpected patterns or bottlenecks in the pipeline.

## Key Technologies

- **Language**: Python 3.11+
- **Web Scraping**: Playwright, BeautifulSoup4
- **OCR & ML**: Docling, PyTorch, Transformers (DeepSeek models)
- **LLMs**: OpenRouter API (Remote), Ollama (Local DeepSeek-R1)
- **Cloud**: AWS S3, SQS, ECS, boto3
- **Semantic Web**: Apache Jena Fuseki, RDFLib, SPARQL, OWL, SHACL
- **Data Validation**: Pydantic v2, SHACL shape validation
- **Containerization**: Docker, Docker Compose, Kubernetes (K8s)

## Commands

### Local Development

```bash
# Install root-level dependencies
pip install -r requirements.txt

# Run monitoring dashboard
python reporter.py --watch
```

### Initial Pipeline Execution
See individual stage directories for specific commands. Generally:
```bash
cd [Stage_Directory]
python main.py
```

### Result Tracking Pipeline
```bash
cd 6_Result_Update
python result_updater.py

cd 8_Result_Ingestion
python result_ingestor.py
```

### Testing & Validation (Stage 5)

```bash
cd 5_Ingestion
pytest tests/
```

### Deployment

```bash
# Kubernetes deployment
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/
```

## Development Conventions

### Asynchronous I/O
- Stages use `asyncio` for concurrent network operations (Playwright, LLM API calls, S3 uploads)
- Embedding generation in 5_Ingestion uses `asyncio.gather()` for batch concurrency

### SQS Polling Loop Structure
All consumer stages follow this pattern:
```python
while True:
    try:
        response = sqs.receive_message(QueueUrl=..., MaxNumberOfMessages=1, WaitTimeSeconds=20)
        if 'Messages' not in response: continue
        for msg in response['Messages']:
            handle_message(msg, sqs, ...)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        time.sleep(5)
```

### Monitoring Integration
Every `handle_message` implementation should use the `monitor` module:
```python
from monitor import enter, complete, failed

def handle_message(msg, ...):
    tender_ref = msg['tender_ref']
    enter(batch_id, tender_ref, STAGE_NAME)
    try:
        # process ...
        complete(batch_id, tender_ref, STAGE_NAME)
    except Exception as e:
        failed(batch_id, tender_ref, STAGE_NAME, detail=str(e))
```

## Directory Structure

```
tender_scrape/
├── GEMINI.md                          # Root documentation (this file)
├── monitor.py                         # Shared event emitter
├── reporter.py                        # Batch reporting tool
├── pipeline.db                        # SQLite database for monitoring
├── k8s/                               # Kubernetes manifests
│
├── 1_Update/                         # Web Scraper (Initial Tender)
├── 2_Ocr/                           # OCR & Text Extraction
├── 3_Classification/                # Document Classification
├── 4_Extraction/                    # Structured Data Extraction
├── 5_Ingestion/                     # Knowledge Graph Ingestion
│
├── 6_Result_Update/                 # Result PV Scraper (Post-Deadline)
├── 7_Result_scrape/                 # Results OCR Service
└── 8_Result_Ingestion/              # Results KG Ingestor (Local LLM)
```

## Configuration & Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `AWS_REGION` | AWS region for S3/SQS | `eu-west-3` |
| `S3_BUCKET_NAME` | S3 bucket for documents | `tender-scrape-data` |
| `OPENROUTER_API_KEY` | LLM/embedding API key | `sk-or-v1-...` |
| `OLLAMA_BASE_URL` | Local LLM endpoint | `http://ollama:11434` |
| `JENA_ENDPOINT` | Jena Fuseki base URL | `http://fuseki:3030` |
| `JENA_DATASET` | Jena dataset name | `tenders` |
| `RESULTS_OCR_QUEUE_URL` | SQS queue for results OCR | — |
| `RESULTS_INGESTION_QUEUE_URL`| SQS queue for results ingestion| — |

## Integration Notes

- **Tender References**: Use normalized format (e.g., `AO_123_2024`) consistently.
- **Monitoring**: Ensure `batch_id` is propagated through all SQS messages.
- **Local LLMs**: Stage 8 uses Ollama locally to reduce costs for result extraction.

## Additional Resources

- **5_Ingestion/GEMINI.md** — Detailed guidance for initial RDF ingestion.
- **8_Result_Ingestion/GEMINI.md** — Detailed guidance for result ingestion.
- **Ontology Files** — `5_Ingestion/ontology/` and `8_Result_Ingestion/ontology/`.
