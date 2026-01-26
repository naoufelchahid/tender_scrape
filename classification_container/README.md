# Classification Container

## Overview

The **Classification Container** is a critical component in the tender processing pipeline, positioned between the OCR container and the extraction container. It implements a sophisticated 3-step document classification system to accurately identify and tag tender documents before they are processed for data extraction.

**Pipeline Position:**

```
OCR_QUEUE → ocr_container → CLASSIFICATION_QUEUE → classification_container → EXTRACTION_QUEUE → extraction_container
```

## Purpose

- **Classify** tender documents using a 3-step process (filename patterns → content analysis → AI classification)
- **Inject** document type headers into markdown files for downstream processing
- **Route** classified documents to the extraction container

## Architecture

### Pipeline Stage

This container belongs to the **Classification** stage in the System Architecture:

1. scraping_tenders
2. unziping lambda
3. OCR container
4. **→ Classification container ←** (this container)
5. Extraction container
6. Lambda database Filler
7. Vectorisation
8. Synchronize database and graph knowledge base

### 3-Step Classification Methodology

#### Step 1: High-Confidence Filename + Content Patterns

Combines filename signals with content validation for high-accuracy classification:

- **Avis**: Filename contains "avis" + content contains `il\s+sera\s+procédé`
- **Specification**: Filename contains "CPS", "CCTP", or variants + content matches 1-3+ technical spec patterns
- **Administrative**: Filename contains "RC", "Reglement consultation" + content matches 1-3+ admin patterns
- **Product (BDP)**: Filename contains "bordereau", "BDP", "detail estimatif" + content matches 1-3+ pricing patterns

Confidence levels:

- **High**: 3+ content pattern matches
- **Medium**: 2 content pattern matches
- **Low**: 1 content pattern match

#### Step 2: Content-Based Classification for Unknowns

For documents not classified in Step 1:

**Short documents (<3000 chars):**

- Check for Avis patterns (tender announcements)
- Check for Form patterns (declarations, engagement acts)
- Check for BDP patterns (pricing tables)

**Long documents (>3000 chars):**

- Analyze first 5000 characters
- Check for Specification patterns (technical specs)
- Check for Administrative patterns (regulations)

#### Step 3: AI-Based Classification

For documents that remain unknown after Step 2:

- Uses **OpenRouter** with `xiaomi/mimo-v2-flash:free` model
- Sends first 5000 characters with classification prompt
- Returns document type or "unknown" if AI fails

### Document Types

- `avis`: Tender notice/announcement (Avis d'appel d'offres)
- `administrative`: Administrative regulation (Règlement de consultation)
- `specification`: Technical specifications (CPS/CCTP)
- `product`: Bill of quantities/pricing (Bordereau des Prix)
- `form`: Forms (declarations, engagement acts)
- `other`: Miscellaneous documents
- `unknown`: Classification failed

## Environment Variables

```bash
# AWS Configuration
AWS_REGION=eu-west-3
S3_BUCKET_NAME=your-bucket-name

# SQS Queues
CLASSIFICATION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../classification-queue
EXTRACTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../extraction-queue

# S3 Paths
MARKDOWN_PREFIX=markdown_tender/

# OpenRouter API
OPENROUTER_API_KEY=sk-or-v1-...
```

## Input Message Format (from OCR Container)

```json
{
  "tender_ref": "AO_123/2024",
  "markdown_paths": [
    "markdown_tender/AO_123_2024/AO_123_2024_ocr.md"
  ]
}
```

## Output

### S3 Markdown File

Classified markdown with injected headers:

```markdown
# File: avis.pdf

> Document Type: avis

Content of the tender notice...

---

# File: CPS.docx

> Document Type: specification

Content of technical specifications...
```

**File Naming**: Original `_ocr.md` suffix is removed

- Input: `markdown_tender/TEST_REF/TEST_REF_ocr.md`
- Output: `markdown_tender/TEST_REF/TEST_REF.md`

### SQS Message (to Extraction Container)

```json
{
  "tender_ref": "AO_123/2024",
  "markdown_paths": ["markdown_tender/AO_123_2024/AO_123_2024.md"],
  "classification_complete": true
}
```

## Local Development

### Setup

```bash
cd /home/naoufel/projects/AO_scrape/classification_container

# Create .env file
cp .env.example .env
# Edit .env with your credentials

# Install dependencies
pip install -r requirements.txt
```

### Run Locally

```bash
python main.py
```

### Test Classification

```bash
# Test Step 1
python -c "
from src.classifier import DocumentClassifier

classifier = DocumentClassifier()
result = classifier.step1_classify('Avis_AO_123.pdf', 'Il sera procédé à...')
print(f'Result: {result}')
"

# Test Step 2
python -c "
from src.classifier import DocumentClassifier

classifier = DocumentClassifier()
short_text = 'avis d\\'appel d\\'offres...' * 50
result = classifier.step2_classify('unknown', short_text)
print(f'Result: {result}')
"
```

## Docker Deployment

### Build Image

```bash
cd /home/naoufel/projects/AO_scrape/classification_container
docker build -t classification-container:latest .
```

### Run Container

```bash
docker run --env-file .env classification-container:latest
```

### Deploy to AWS ECS/ECR

```bash
# Tag image
docker tag classification-container:latest <account-id>.dkr.ecr.eu-west-3.amazonaws.com/classification-container:latest

# Push to ECR
docker push <account-id>.dkr.ecr.eu-west-3.amazonaws.com/classification-container:latest

# Update ECS task definition and service
```

## Monitoring

### Logs

The container logs classification results for each document:

```
INFO - Processing tender: AO_123/2024
INFO - Split into 5 logical documents
INFO -   'avis.pdf' → avis (step 1, confidence: high)
INFO -   'RC.docx' → administrative (step 1, confidence: medium)
INFO -   'CPS.pdf' → specification (step 2, confidence: high)
INFO -   'BDP.xlsx' → product (step 1, confidence: high)
INFO -   'unknown.pdf' → other (step 3, confidence: ai)
INFO - ✓ Successfully processed AO_123/2024
```

### Metrics to Monitor

- Number of documents processed
- Classification step distribution (Step 1 vs Step 2 vs Step 3)
- Confidence level distribution
- Unknown document rate
- Processing time per tender
- SQS queue depth
- OpenRouter API errors (Step 3 failures)

## Troubleshooting

### Documents Always Classified as "unknown"

- Check regex patterns in `classifier.py`
- Verify content encoding (UTF-8)
- Check if OpenRouter API key is valid

### OpenRouter Step 3 Failures

- Verify `OPENROUTER_API_KEY` is set
- Check network connectivity to `openrouter.ai`
- Review model availability (`xiaomi/mimo-v2-flash:free`)

### SQS Message Not Received

- Verify `CLASSIFICATION_QUEUE_URL` is correct
- Check IAM permissions for SQS receive/delete
- Monitor queue visibility timeout

## Performance

- **Step 1**: ~10ms per document (regex matching)
- **Step 2**: ~20ms per document (content analysis)
- **Step 3**: ~500-2000ms per document (AI inference)

Most documents (70-80%) should be classified in Step 1, minimizing AI API costs.
