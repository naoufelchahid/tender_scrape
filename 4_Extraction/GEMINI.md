# 4_Extraction: Structured Data Extraction Service

This container handles the **fourth stage** of the pipeline: consuming classified markdown documents, decomposing into structured JSON chunks, and preparing for knowledge graph ingestion.

## Purpose

- **Poll** SQS queue for classified documents (from 3_Classification)
- **Download** markdown with document-type headers from S3
- **Chunk** documents into logical sections using heuristics
- **Extract** structured data (tender info, product details, pricing) using LLMs
- **Validate** extracted data against Pydantic models
- **Upload** JSON chunks to S3
- **Route** to 5_Ingestion queue for RDF conversion and Jena storage

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop. Polls EXTRACTION_QUEUE, orchestrates extraction |
| `src/document_chunker.py` | Core extraction logic. Decomposes markdown → JSON chunks using LLM + heuristics |
| `src/cleaning.py` | Text cleaning utilities (normalize spaces, remove artifacts, etc.) |
| `src/models.py` | Pydantic v2 models for extracted data (TenderAvis, Product, Lot, etc.) |
| `src/openrouter_wrapper.py` | LLM API wrapper (OpenRouter with fallback chain) |
| `src/prompts.py` | LLM extraction prompts |
| `src/database.py` | Database manager for persistence |
| `src/smoke_test_chunker.py` | Component test for chunking logic |
| `tests/test_extraction_quality.py` | Quality validation tests |
| `repro_parsing.py` | Reproduction script for debugging parsing issues |
| `repro_metadata_issue.py` | Reproduction script for metadata issues |
| `Dockerfile` | Container image definition |

## Data Flow

```
SQS Input (EXTRACTION_QUEUE)
  Message: { "tender_ref": "AO_123_2024", "document_type": "avis", ... }
  ↓
4_Extraction service:
  1. Download markdown from S3: markdown_tender/{tender_ref}/concatenated.md
  2. Split by document type (avis, administrative, specification, product, form)
  3. For each document type:
     - Chunk into logical sections (headers, boundaries)
     - Extract structured data using LLM
     - Validate against Pydantic models (TenderAvis, Product, Lot, etc.)
  4. Serialize JSON chunks
  5. Upload to S3: extracted_json/{tender_ref}/
  ↓
SQS Output (DB_FILLER_QUEUE)
  Message routed to 5_Ingestion
```

## Document Types & Extracted Data

| Type | Output Model | Key Fields |
|------|--------------|-----------|
| `avis` | `TenderAvis` | ref, buyer, deadline, lots, budget, activity, regions |
| `administrative` | `AdministrativeDoc` | rules, timelines, conditions |
| `specification` | `Specification` | technical requirements, standards |
| `product` (BDP) | `Product`, `Lot` | quantities, prices, unit costs |
| `form` | `FormDocument` | declarations, engagement acts |

## Local Development

### Setup
```bash
cd 4_Extraction
pip install -r requirements.txt
```

### Environment Variables (`.env`)
```bash
# AWS
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-west-3

# SQS Queue URLs
EXTRACTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../extraction-queue
DB_FILLER_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../db-filler-queue

# S3
S3_BUCKET_NAME=tender-scrape-data

# LLM API
OPENROUTER_API_KEY=sk-or-v1-...

# Database (optional for persistence)
DB_URL=postgresql://user:pass@localhost/tender_db
```

### Running Locally

**Start extraction service:**
```bash
python main.py
# Logs to stdout + extraction.log
# Processes one tender at a time
```

**Run reproduction scripts (debugging):**
```bash
# Test parsing on sample document
python repro_parsing.py

# Test metadata extraction issue
python repro_metadata_issue.py
```

**Test chunker component:**
```bash
python src/smoke_test_chunker.py
```

**Run quality tests:**
```bash
pytest tests/test_extraction_quality.py -v
```

## Code Patterns

### DocumentChunker
- Input: classified markdown with document-type headers
- Process:
  1. Split by document-type headers
  2. Identify chunk boundaries (headers, page breaks, line patterns)
  3. For each chunk, call LLM with extraction prompt
  4. Validate output against Pydantic model
  5. Serialize to JSON
- Output: list of JSON chunks (one per logical document)

### LLM Extraction Prompts
- Located in `src/prompts.py`
- Prompts extract:
  - **Avis**: tender reference, buyer, deadline, lots, budget, activity, regions
  - **Product**: quantities, unit prices, product names
  - **Admin**: rules, procedures, deadlines
- Uses few-shot examples for accuracy

### Pydantic Models
- `TenderAvis`: main tender announcement
- `Product`: bill of quantities item
- `Lot`: tender lot (may contain multiple products)
- `AdministrativeDoc`: regulatory document
- Custom validators for French number formatting (e.g., "1 234,56 DH" → float)

### Error Handling
- On LLM extraction failure, logs error and skips chunk
- Validation errors caught and logged (chunk may be partial)
- Message returned to SQS queue on critical failure (visibility timeout)

## Testing & Validation

### Component Tests
```bash
# Test document chunking
python -c "from src.document_chunker import DocumentChunker; c = DocumentChunker('eu-west-3', 'key'); print('OK')"

# Test Pydantic models
python -c "from src.models import TenderAvis; avis = TenderAvis(ref='AO_123_2024', buyer='Test', ...); print(avis.dict())"

# Test text cleaning
python -c "from src.cleaning import DocumentCleaners; dc = DocumentCleaners; text = 'Test  spaces'; print(dc.normalize_whitespace(text))"
```

### Quality Tests
```bash
# Run extraction quality suite
pytest tests/test_extraction_quality.py -v

# Run specific test
pytest tests/test_extraction_quality.py::test_avis_extraction -v
```

## Debugging

### LLM Extraction Failures
1. Check `OPENROUTER_API_KEY` in `.env`
2. Run `repro_parsing.py` with sample markdown to test extraction
3. Enable debug logging: edit `main.py`, set `logging.DEBUG`
4. Check LLM prompt in `src/prompts.py` — may need example adjustment

### Pydantic Validation Errors
1. Check French number formatting: "1 234,56 DH" should become float
2. Review custom validators in `src/models.py`
3. Test with direct model instantiation:
   ```python
   from src.models import TenderAvis
   avis = TenderAvis(ref='...', buyer='...', ...)
   ```

### S3 Upload Errors
- Verify bucket exists and credentials work
- Check S3 path: `extracted_json/{tender_ref}/`
- Confirm file permissions and ACLs

### Queue Message Processing
- On error, message returns to queue after visibility timeout (default 30s)
- Check DLQ for poison messages
- Verify queue URLs in `.env`

## Integration Points

- **Input SQS**: EXTRACTION_QUEUE (from 3_Classification)
- **Input S3**: Classified markdown at `markdown_tender/{tender_ref}/`
- **Output S3**: JSON chunks at `extracted_json/{tender_ref}/`
- **Output SQS**: DB_FILLER_QUEUE (to 5_Ingestion)
- **LLM API**: OpenRouter (with fallback model chain)
- **Database**: PostgreSQL (optional, for tracking processed tenders)

## Performance Notes

- **Per-document time**: 10-30s depending on size and LLM response time
- **LLM calls**: One per chunk (variable cost)
- **Concurrency**: Sequential SQS polling; no internal parallelism
- **Optimization**: Chunk boundaries designed to fit LLM context window (~4k tokens)

## Deployment

### Docker
```bash
cd 4_Extraction
docker build -t tender-scrape-extraction:latest .
docker run --env-file .env tender-scrape-extraction:latest python main.py
```

### AWS ECS
- Similar to 2_Ocr deployment
- Update task definition with environment variables
- Push image to ECR
- Deploy via AWS console or CLI

## Common Tasks

### Adjusting Chunk Boundaries
1. Edit `src/document_chunker.py`, find chunk splitting logic
2. Modify regex or heuristics for header detection
3. Test with `repro_parsing.py` on sample documents
4. Validate output JSON structure

### Adding New Extraction Fields
1. Add field to Pydantic model in `src/models.py`
2. Add custom validator if special formatting needed (French numbers, dates, etc.)
3. Update LLM prompt in `src/prompts.py` with example
4. Test with reproduction script
5. Run `pytest tests/test_extraction_quality.py`

### Debugging French Number Parsing
- French format: "1 234,56 DH" (space thousands separator, comma decimal)
- Check `src/models.py` for `@field_validator` on numeric fields
- Test: `float("1234.56".replace(" ", "").replace(",", "."))`

### Monitoring Extraction Quality
```bash
# Check recent extractions in S3
aws s3 ls s3://tender-scrape-data/extracted_json/ --recursive | tail -20

# Check queue depth
aws sqs get-queue-attributes \
  --queue-url $EXTRACTION_QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages
```

## Related Documentation

- **Root CLAUDE.md**: Pipeline architecture, message contracts
- **3_Classification/CLAUDE.md**: Upstream classification stage
- **5_Ingestion/CLAUDE.md**: Downstream RDF ingestion
- **Memory**: `pipeline_operations.md`
