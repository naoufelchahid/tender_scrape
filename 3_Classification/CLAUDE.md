# 3_Classification: Document Classification Service

This container handles the **third stage** of the pipeline: classifying markdown documents by type, injecting document-type headers, detecting missing documents, and routing for extraction.

## Purpose

- **Poll** SQS queue for markdown documents (from 2_Ocr)
- **Classify** documents using 3-step methodology (patterns → content → AI)
- **Detect Missing Documents** by searching entire markdown for types not yet found
- **Inject** document-type headers into markdown for downstream processing
- **Route** classified documents to 4_Extraction queue

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer loop. Polls CLASSIFICATION_QUEUE, orchestrates classification |
| `src/classifier.py` | Core classification logic (3-step process + missing document detection) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image definition |
| `.env` | Configuration (queue URLs, API keys, S3 paths) |

## Document Types & Classification

| Type | Definition | Example Filename |
|------|-----------|------------------|
| `avis` | Tender notice/announcement (Avis d'appel d'offres) | avis.pdf, AO_2024.pdf |
| `administrative` | Regulatory document (Règlement de consultation) | RC.pdf, reglement.docx |
| `specification` | Technical specifications | CPS.pdf, CCTP.docx |
| `product` | Bill of quantities (Bordereau des Prix) | BDP.xlsx, bordereau.pdf |
| `form` | Forms, declarations, engagement acts | declaration.pdf, acte_engagement.pdf |
| `other` | Miscellaneous documents | misc.pdf |
| `unknown` | Classification failed at all steps | — |

## Classification Methodology

### Step 1: High-Confidence Filename + Content Patterns
Combines filename signals with content validation:

- **Avis**: Filename contains "avis" + content matches pattern `il\s+sera\s+procédé`
- **Specification**: Filename contains "CPS", "CCTP" + content matches 1-3+ technical patterns
- **Administrative**: Filename contains "RC", "Reglement" + content matches 1-3+ admin patterns
- **Product (BDP)**: Filename contains "bordereau", "BDP" + content matches 1-3+ pricing patterns

Confidence levels:
- **High**: 3+ content pattern matches
- **Medium**: 2 content pattern matches
- **Low**: 1 content pattern match

### Step 2: Content-Based Classification for Unknowns
For documents not classified in Step 1:

**Short documents (<3000 chars):**
- Check for Avis patterns
- Check for Form patterns (declarations, engagement acts)
- Check for BDP patterns

**Long documents (>3000 chars):**
- Analyze first 5000 characters
- Check for Specification patterns
- Check for Administrative patterns

### Step 3: AI-Based Classification
For remaining unknowns:
- Uses OpenRouter API with model fallback chain
- Sends first 5000 characters to LLM with classification prompt
- Returns document type or "unknown" if all fail

### Step 4: Missing Document Detection
After initial classification, searches entire markdown for missing document types:

**Detected Types:**
- `avis_fr`: French tender notices
- `avis_ar`: Arabic tender notices
- `declaration`: Declaration sur l'honneur
- `acte_engagement`: Acte d'engagement
- `product`: Bill of quantities

**Process:**
1. Scan entire markdown for patterns
2. Tag detected blocks with temporary markers
3. Extract tagged content into new document objects
4. Merge original + extracted documents
5. Regenerate markdown with all documents

## Data Flow

```
SQS Input (CLASSIFICATION_QUEUE)
  Message: { "tender_ref": "AO_123_2024", "markdown_paths": [...] }
  ↓
Download markdown from S3: markdown_tender/{tender_ref}/
  ↓
3_Classification Service:
  1. Split markdown by file sections
  2. For each section:
     - Step 1: Pattern matching (high-confidence)
     - Step 2: Content analysis (for unknowns)
     - Step 3: AI classification (fallback)
  3. Search entire markdown for missing documents
  4. Inject document-type headers
  5. Regenerate markdown with all classifications
  ↓
Upload to S3: markdown_tender/{tender_ref}/ (with headers)
  ↓
SQS Output (EXTRACTION_QUEUE)
  Message routed to 4_Extraction
```

## Local Development

### Setup
```bash
cd 3_Classification
pip install -r requirements.txt
```

### Environment Variables (`.env`)
```bash
# AWS
AWS_REGION=eu-west-3
S3_BUCKET_NAME=tender-scrape-data

# SQS Queue URLs
CLASSIFICATION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../classification-queue
EXTRACTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../extraction-queue

# S3 Paths
MARKDOWN_PREFIX=markdown_tender/

# LLM API (for Step 3)
OPENROUTER_API_KEY=sk-or-v1-...
```

### Running Locally

**Start classification service:**
```bash
python main.py
# Logs SQS polling and classification results to stdout
```

**Test Step 1 (pattern matching):**
```bash
python -c "
from src.classifier import DocumentClassifier

classifier = DocumentClassifier()
result = classifier.step1_classify('Avis_AO_123.pdf', 'Il sera procédé à...')
print(f'Result: {result}')
"
```

**Test Step 2 (content analysis):**
```bash
python -c "
from src.classifier import DocumentClassifier

classifier = DocumentClassifier()
short_text = 'avis d\\'appel d\\'offres...' * 50
result = classifier.step2_classify('unknown', short_text)
print(f'Result: {result}')
"
```

## Input/Output Format

### Input SQS Message (from 2_Ocr)
```json
{
  "tender_ref": "AO_123_2024",
  "markdown_paths": [
    "markdown_tender/AO_123_2024/AO_123_2024_ocr.md"
  ]
}
```

### Markdown File (with injected headers)
Input markdown is transformed with document-type headers:

```markdown
# File: avis.pdf

> Document Type: avis

Content of the tender notice...

---

# File: CPS.docx

> Document Type: specification

Content of technical specifications...
```

**File Naming**:
- Input: `markdown_tender/{tender_ref}/{tender_ref}_ocr.md`
- Output: `markdown_tender/{tender_ref}/{tender_ref}.md` (suffix removed)

### Output SQS Message (to 4_Extraction)
```json
{
  "tender_ref": "AO_123_2024",
  "markdown_paths": [
    "markdown_tender/AO_123_2024/AO_123_2024.md"
  ],
  "classification_complete": true
}
```

## Testing & Validation

### Smoke Tests
```bash
# Test classifier import
python -c "from src.classifier import DocumentClassifier; print('OK')"

# Test pattern matching
python -c "
from src.classifier import DocumentClassifier
c = DocumentClassifier()
print(c.step1_classify('test.pdf', 'Il sera procédé à'))
"
```

### Monitor Classification Results
Look for logs like:
```
INFO - Processing tender: AO_123_2024
INFO - Split into 5 documents
INFO -   'avis.pdf' → avis (step 1, confidence: high)
INFO -   'RC.docx' → administrative (step 1, confidence: medium)
INFO -   'CPS.pdf' → specification (step 2, confidence: high)
INFO -   'BDP.xlsx' → product (step 1, confidence: high)
INFO -   'unknown.pdf' → other (step 3, confidence: ai)
INFO - ✓ Successfully processed AO_123_2024
```

## Debugging

### Documents Always Classified as "unknown"
1. Check regex patterns in `src/classifier.py`
2. Verify content encoding (UTF-8)
3. Check OpenRouter API key validity
4. Test Step 1 patterns manually with sample text

### OpenRouter Step 3 Failures
1. Verify `OPENROUTER_API_KEY` is set in `.env`
2. Check network connectivity to openrouter.ai
3. Monitor API rate limits and costs
4. Test API connectivity: 
   ```bash
   curl -H "Authorization: Bearer $OPENROUTER_API_KEY" https://openrouter.ai/api/v1/models
   ```

### SQS Queue Issues
1. Verify `CLASSIFICATION_QUEUE_URL` and `EXTRACTION_QUEUE_URL` are correct
2. Check IAM permissions (SQS receive, delete, send)
3. Monitor queue depth and visibility timeout
4. Check DLQ for poison messages

### Markdown S3 Upload Failures
1. Verify S3 bucket exists and is accessible
2. Check AWS credentials in `.env`
3. Confirm S3 path structure matches `MARKDOWN_PREFIX` config

## Performance Notes

- **Step 1**: ~10ms per document (regex matching)
- **Step 2**: ~20ms per document (content analysis)
- **Step 3**: ~500-2000ms per document (AI inference via OpenRouter)
- **Typical distribution**: 70-80% classified in Step 1 (minimizes API costs)
- **Optimal case**: Entire tender classified in under 1 second if Step 1 catches all docs

## Deployment

### Docker
```bash
cd 3_Classification
docker build -t tender-scrape-classification:latest .
docker run --env-file .env tender-scrape-classification:latest
```

### AWS ECS
- Similar to 2_Ocr deployment
- Update task definition with environment variables
- Push image to ECR
- Deploy via AWS console or CLI

## Monitoring

### Key Metrics
- Number of documents processed
- Classification step distribution (Step 1 vs Step 2 vs Step 3)
- Confidence level distribution
- Unknown document rate
- Processing time per tender
- SQS queue depth
- OpenRouter API errors and costs

### Queue Monitoring
```bash
# Check queue depth
aws sqs get-queue-attributes \
  --queue-url $CLASSIFICATION_QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages

# Check messages in DLQ
aws sqs get-queue-attributes \
  --queue-url $CLASSIFICATION_DLQ_URL \
  --attribute-names ApproximateNumberOfMessages
```

## Common Tasks

### Adjusting Classification Patterns
1. Edit pattern regexes in `src/classifier.py` (Step 1/2)
2. Test with known documents:
   ```bash
   python -c "from src.classifier import DocumentClassifier; c = DocumentClassifier(); print(c.step1_classify('filename.pdf', 'content'))"
   ```
3. Redeploy container

### Tuning Step 3 LLM Prompt
1. Edit classification prompt in `src/classifier.py` (Step 3)
2. Adjust model fallback chain if needed
3. Test with `main.py` local run
4. Monitor accuracy and API costs

### Handling Missing Documents
1. Patterns are defined in Step 4 logic (in `src/classifier.py`)
2. Add new detection patterns for additional document types
3. Test with full tender markdown locally
4. Verify regenerated markdown structure

## Related Documentation

- **Root CLAUDE.md**: Pipeline architecture, message contracts
- **2_Ocr/CLAUDE.md**: Upstream OCR stage
- **4_Extraction/CLAUDE.md**: Downstream extraction stage
- **3_Classification/README.md**: Original detailed documentation (legacy)
- **Memory**: `pipeline_operations.md`
