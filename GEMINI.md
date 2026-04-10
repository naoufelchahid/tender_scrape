# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tender Scrape** is a sophisticated multi-stage, event-driven data processing pipeline for scraping, processing, and ingesting Moroccan public procurement tenders into a semantic Knowledge Graph. The pipeline uses AWS SQS for inter-stage queueing and S3 for distributed document storage.

**Purpose**: Automate the extraction of structured tender data from documents, validate quality, and persist to Apache Jena triple store with vector embeddings.

## Architecture at a Glance

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

### Pipeline Stages

1. **1_Update** — Web scraper using Playwright/BeautifulSoup. Navigates marchespublics.gov.ma, extracts tender metadata (reference, buyer, categories, deadlines, lots), and downloads ZIP files. Uploads raw documents and JSON metadata to S3, posts tender references to SQS.

2. **2_Ocr** — SQS consumer polling for new tenders. Uses Docling (PyTorch/Transformers) to perform OCR and convert PDFs/documents into Markdown. Outputs concatenated markdown files to S3.

3. **3_Classification** — SQS consumer implementing 3-step document classification: (Step 1) filename + regex patterns for high-confidence classification, (Step 2) content analysis for unknowns, (Step 3) LLM fallback (OpenRouter). Injects document-type headers into markdown, posts to extraction queue.

4. **4_Extraction** — SQS consumer. Uses LLMs and `DocumentChunker` heuristics to decompose classified documents into smaller, structured JSON chunks suitable for vectorization and semantic mapping. Routes to ingestion queue.

5. **5_Ingestion** — Final SQS consumer (microservice). Orchestrates: tender enrichment from S3 → JSON-to-RDF mapping → SHACL validation → SPARQL insertion to Jena → concurrent embedding generation → vector storage in S3.

## Key Technologies

- **Language**: Python 3.11+
- **Web Scraping**: Playwright, BeautifulSoup4
- **OCR & ML**: Docling, PyTorch, Transformers (DeepSeek models)
- **LLMs**: OpenRouter API (fallback model chain)
- **Cloud**: AWS S3, SQS, ECS, boto3
- **Semantic Web**: Apache Jena Fuseki, RDFLib, SPARQL, OWL, SHACL
- **Data Validation**: Pydantic v2, SHACL shape validation
- **Containerization**: Docker, Docker Compose

## Commands

### Local Development

```bash
# Install root-level dependencies
pip install -r requirements.txt

# Install stage-specific dependencies (example: 4_Extraction)
cd 4_Extraction
pip install -r requirements.txt
```

### 4_Extraction (Current Stage)

```bash
# Run the extraction service locally
cd 4_Extraction
python main.py

# Run reproduction scripts for debugging
python repro_parsing.py
python repro_metadata_issue.py

# Test individual components locally
python -c "from src.document_chunker import DocumentChunker; print('Import successful')"
```

### 5_Ingestion (Tests)

```bash
cd 5_Ingestion

# Run all tests
pytest tests/

# Run a specific test file
pytest tests/test_data_tester.py

# Run a specific test function
pytest tests/test_data_tester.py::test_passed_validation

# Run with verbose output
pytest -v tests/

# Run the ingestion service
python main.py

# Debug SHACL validation
python test_pyshacl.py
```

### 2_Ocr (Deployment)

```bash
cd 2_Ocr

# Build Docker image locally
docker build -t tender-scrape-ocr:latest .

# Run with docker-compose (for local Jena testing)
docker-compose up

# Deploy to AWS ECS (requires credentials)
./deploy_to_ecs.sh
```

### 1_Update (Scraper Control)

```bash
cd 1_Update

# Run the tender scraper
python Db_updater.py

# Run reference data updater
python ref_updater.py

# Analyze knowledge graph
python analyze_graph.py

# Update Fuseki visualization
python visualize_graphistry.py
```

### Docker & Deployment

```bash
# Build extraction service image
cd 4_Extraction
docker build -t tender-scrape-extraction:latest .
docker run --env-file .env tender-scrape-extraction:latest

# View ECS deployment script
cat 2_Ocr/deploy_to_ecs.sh
```

## Development Conventions

### Asynchronous I/O
- Stages use `asyncio` for concurrent network operations (Playwright, LLM API calls, S3 uploads)
- Embedding generation in 5_Ingestion uses `asyncio.gather()` for batch concurrency
- Keep async patterns consistent when extending stages

### SQS Polling Loop Structure
All consumer stages (2_Ocr, 3_Classification, 4_Extraction, 5_Ingestion) follow this pattern:
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

### Error Handling
- Messages return to queue on processing failure (visibility timeout)
- Dead Letter Queues (DLQs) capture poison messages after max retries
- All errors logged with context (tender_ref, queue name, exception details)

### Logging
- Standard Python `logging` module across all stages
- Format: `%(asctime)s - %(levelname)s - %(message)s`
- Per-stage log files in `/logs` or stdout (ECS/container logs)
- Key metrics: processing times, queue depth, API errors

### Data Flow & Representations
- **Stage Output Formats:**
  - 1_Update → Raw PDFs/DOCs in S3 + JSON metadata
  - 2_Ocr → Markdown in S3 (concatenated, UTF-8)
  - 3_Classification → Markdown with YAML frontmatter + injected document-type headers
  - 4_Extraction → JSON chunks in S3 (one chunk per logical section)
  - 5_Ingestion → N-Triples in `/tmp/nt_output` + RDF triples in Jena

### Testing & Validation
- 5_Ingestion uses **Test-Driven Data (TDD)**: SHACL shape validation before Jena insertion
- SHACL shapes defined in `ontology/` directory; validated against local rdflib graph
- Post-insertion verification queries Jena directly
- Pydantic models in `src/models.py` validate input data (French number formatting, currency)

## Directory Structure

```
tender_scrape/
├── CLAUDE.md                          # This file
├── GEMINI.md                          # Project context for Gemini
├── requirements.txt                   # Root-level Python dependencies
├── Dockerfile                         # Base image for extraction
├── .env                              # Environment variables (local dev)
│
├── 1_Update/                         # Web Scraper
│   ├── Db_updater.py                # Main scraper entry point
│   ├── ref_updater.py               # Reference data updater
│   ├── kg_builder.py                # Knowledge graph builder
│   ├── requirements.txt
│   └── browser_config/              # Playwright config
│
├── 2_Ocr/                           # OCR & Text Extraction Microservice
│   ├── main.py                      # SQS consumer entry point
│   ├── document_processor.py        # Docling integration
│   ├── config.py                    # Configuration (queue URLs, S3 paths)
│   ├── logger.py                    # Logging setup
│   ├── s3_utils.py                  # S3 upload/download helpers
│   ├── sqs_utils.py                 # SQS queue operations
│   ├── requirements.txt
│   ├── Dockerfile                   # CPU-optimized image
│   ├── docker-compose.yml           # Local dev orchestration
│   ├── deploy_to_ecs.sh             # AWS ECS deployment script
│   └── container-definitions*.json  # ECS task definitions
│
├── 3_Classification/                # Document Classification Microservice
│   ├── main.py                      # SQS consumer entry point
│   ├── src/classifier.py            # 3-step classification logic
│   ├── README.md                    # Detailed classification documentation
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env                         # Configuration (API keys, queue URLs)
│
├── 4_Extraction/                    # Structured Data Extraction Microservice
│   ├── main.py                      # SQS consumer entry point
│   ├── src/
│   │   ├── document_chunker.py      # Chunking & LLM extraction logic
│   │   ├── cleaning.py              # Text cleaning utilities
│   │   ├── database.py              # Database manager
│   │   ├── models.py                # Pydantic models for extracted data
│   │   ├── openrouter_wrapper.py    # LLM API wrapper
│   │   ├── prompts.py               # LLM prompts
│   │   └── smoke_test_chunker.py    # Component test
│   ├── tests/                       # Unit tests
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── deploy.sh                    # ECS deployment script
│   └── run_local.sh                 # Local execution script
│
├── 5_Ingestion/                     # Knowledge Graph Ingestion Microservice
│   ├── CLAUDE.md                    # Stage-specific guidance
│   ├── main.py                      # SQS consumer + KBIngestor orchestrator
│   ├── src/
│   │   ├── json_to_rdf.py           # JSON → RDF mapping logic
│   │   ├── data_tester.py           # SHACL validation (DataTester)
│   │   ├── jena_client.py           # Jena Fuseki API client
│   │   ├── uri_builder.py           # RDF namespace & URI helpers
│   │   ├── embedding_client.py      # OpenRouter embedding API
│   │   ├── vector_storage.py        # S3 vector storage
│   │   ├── models.py                # Pydantic schemas (TenderAvis, Product, etc.)
│   │   ├── config.py                # Configuration & env vars
│   │   └── __init__.py
│   ├── tests/
│   │   ├── test_data_tester.py      # SHACL validation tests
│   │   ├── test_json_to_rdf.py      # Mapping tests
│   │   ├── test_jena_client.py      # Jena API tests
│   │   └── conftest.py              # Pytest fixtures
│   ├── ontology/
│   │   ├── tender_structure.owl     # OWL ontology definition
│   │   └── shapes.ttl               # SHACL shapes (not committed)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── docker-compose.fuseki.yml    # Local Jena Fuseki setup
│   └── test_pyshacl.py              # Standalone SHACL debug tool
│
└── .agents/                         # (ignore) Agent/skill configuration
```

## Configuration & Environment Variables

Key variables per stage (set in `.env` or container env):

| Variable | Purpose | Example |
|---|---|---|
| `AWS_REGION` | AWS region for S3/SQS | `eu-west-3` |
| `AWS_ACCESS_KEY_ID` | AWS credentials | — |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials | — |
| `S3_BUCKET_NAME` | S3 bucket for documents | `tender-scrape-data` |
| `EXTRACTION_QUEUE_URL` | SQS queue URL (4_Extraction input) | `https://sqs.../extraction-queue` |
| `DB_FILLER_QUEUE_URL` | SQS queue URL (post-extraction) | `https://sqs.../db-filler` |
| `KB_INGESTION_QUEUE_URL` | SQS queue URL (5_Ingestion input) | `https://sqs.../ingestion-queue` |
| `OPENROUTER_API_KEY` | LLM/embedding API key | `sk-or-v1-...` |
| `JENA_ENDPOINT` | Jena Fuseki base URL | `http://fuseki:3030` |
| `JENA_DATASET` | Jena dataset name | `tenders` |
| `OPENAI_API_KEY` | OpenAI API key (fallback LLM) | — |
| `DB_URL` | PostgreSQL connection string | `postgresql://...` |
| `MARKDOWN_PREFIX` | S3 path prefix for markdown | `markdown_tender/` |

See individual stage READMEs (e.g., `5_Ingestion/CLAUDE.md`) for stage-specific variables.

## Common Development Tasks

### Adding a New LLM Call
- Add prompt template to `src/prompts.py` or inline
- Use `openrouter_wrapper.py` (if available) or instantiate `openai.AsyncOpenAI(api_key=...)`
- Wrap in try-except with tenacity retry logic (`@retry(...)`)
- Log input/output for debugging

### Testing a Stage Locally Without AWS
- Set `EXTRACTION_QUEUE_URL` to a mock string or skip queue polling
- Hardcode S3 paths or create local test fixtures
- Mock `boto3.client('s3')` and `boto3.client('sqs')` if needed
- Run reproduction scripts (e.g., `repro_parsing.py`) for quick validation

### Debugging SHACL Validation Issues (5_Ingestion)
- Run `python test_pyshacl.py` to test shapes in isolation
- Check `ontology/shapes.ttl` for constraint definitions
- Verify Pydantic models in `src/models.py` match shape requirements
- Enable detailed logging: `logger.setLevel(logging.DEBUG)`

### Deploying a Stage to ECS
- Update `container-definitions.json` with new environment variables
- Build and push Docker image to ECR: `docker build -t ... && docker push ...`
- Update ECS task definition and service
- Reference deployment scripts: `2_Ocr/deploy_to_ecs.sh` for pattern

## Integration Notes

- **Message Format**: SQS messages are JSON with at least `tender_ref` and stage-specific keys
- **S3 Paths**: Follow convention `{prefix}/{tender_ref}/{filename}` for consistency
- **Tender References**: Use normalized format (e.g., `AO_123_2024`) consistently across stages
- **Error Recovery**: Messages silently return to queue on error; implement idempotence for safety
- **Intermediate Markdown**: Treated as source of truth between OCR and Extraction; preserve YAML frontmatter

## Useful Patterns

### Async SQS Consumer Loop
See `2_Ocr/main.py`, `4_Extraction/main.py` for reference implementations.

### Dependency Injection for Testing
5_Ingestion's `JenaClient` accepts callable functions for SPARQL operations, enabling mock injection without subclassing. Pattern: `jena_client = JenaClient(sparql_fn=mock_sparql)`.

### Pydantic Model Validation
5_Ingestion's `src/models.py` demonstrates custom validators for French number formatting (e.g., "1 234,56 DH" → float). Extend similar validators for new data types.

### RDF Namespace Management
5_Ingestion's `src/uri_builder.py` is the single source of truth for all namespaces (`TS`, `REGIONS`, `ACTIVITY`). Use consistent URIs: `ts.Tender(tender_ref)`, `regions.Region("fr_region_name")`, etc.

## Additional Resources

- **GEMINI.md** — High-level project context and technology stack
- **5_Ingestion/CLAUDE.md** — Detailed guidance for knowledge graph ingestion stage
- **3_Classification/README.md** — Comprehensive classification methodology and troubleshooting
- **Ontology Files** — `5_Ingestion/ontology/` contains OWL and SHACL definitions
