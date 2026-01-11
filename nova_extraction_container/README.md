# Nova Extraction Container

Unified container that replaces both OCR and Extraction containers, using Amazon Nova Lite v1 for multimodal document processing via OpenRouter.

## Features

- **Unified Processing**: Combines OCR and extraction in a single step
- **Multimodal**: Uses Nova Lite for both text and image-based PDF processing
- **Intelligent Classification**: Automatically filters unwanted documents (acte d'engagement, plans, etc.)
- **Universal Prompts**: Single comprehensive prompt handles all document types (no type-specific branching)
- **Three-Tier Fallback**: Nova Lite → Mistral Small 3.2 → Nova 2 Lite
- **Text Layer Detection**: Automatically uses text extraction if PDF has text layer
- **OpenRouter Only**: All model inference via OpenRouter (no Bedrock)

## Architecture

```
SQS (OCR_QUEUE) → Download PDFs → Classify → Process with Nova Lite → Upload JSON → SQS (DB_FILLER_QUEUE)
```

**Replaces**:

- `ocr_container` (no longer needed)
- `extraction_container` (no longer needed)

## Prerequisites

- Docker and Docker Compose
- AWS credentials (for S3 and SQS)
- OpenRouter API key

## Setup

1. **Copy environment template**:

   ```bash
   cp .env.example .env
   ```

2. **Configure `.env`**:
   - Set `OCR_QUEUE_URL` (SQS queue to poll)
   - Set `DB_FILLER_QUEUE_URL` (downstream queue)
   - Set `OPENROUTER_API_KEY` (your API key)
   - Configure other settings as needed

3. **Build and start**:

   ```bash
   ./start.sh
   ```

4. **View logs**:

   ```bash
   docker logs -f nova-extraction-container
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OCR_QUEUE_URL` | SQS queue to poll for messages | Required |
| `DB_FILLER_QUEUE_URL` | Downstream queue for completion messages | Required |
| `OPENROUTER_API_KEY` | OpenRouter API key | Required |
| `S3_BUCKET_NAME` | S3 bucket name | `my-tender-documents-bucket` |
| `S3_SOURCE_PREFIX` | S3 prefix for tender documents | `tenders_doc_final/` |
| `PRIMARY_MODEL` | Primary model ID | `amazon/nova-lite` |
| `FALLBACK_MODEL_1` | First fallback model | `mistralai/mistral-small-3.2-24b-instruct` |
| `FALLBACK_MODEL_2` | Second fallback model | `amazon/nova-2-lite` |
| `MAX_WORKERS` | Parallel processing workers | `3` |

### Document Classification

**Excluded Documents** (automatically skipped):

- Acte d'engagement
- Engagement sur l'honneur
- Plans/Drawings
- Attestations
- Certificats
- Administrative forms

**Supported Documents** (processed):

- Avis (tender announcements)
- RC (règlement de consultation)
- CPS (cahier des prescriptions spéciales)
- BDP (bordereau des prix)
- CCTP (technical specifications)

## Processing Workflow

1. **Poll SQS**: Receive message with `tender_ref`
2. **Download**: Get all PDFs from `s3://bucket/tenders_doc_final/{tender_ref}/`
3. **Classify**: Determine document type and filter excluded types (for logging/filtering only)
4. **Detect Text Layer**: Check if PDF has extractable text
5. **Process**:
   - If text layer exists → Extract text and send to LLM
   - If scanned → Convert to images and send to multimodal model
6. **Extract**: Use universal prompt with Nova Lite to extract structured data
   - **Universal Prompt**: Single comprehensive prompt handles all document types
   - LLM intelligently determines what to extract based on content
   - Works correctly regardless of classification accuracy
7. **Fallback**: If Nova fails, try Mistral Small, then Nova 2 Lite
8. **Aggregate**: Combine results from all documents
9. **Validate**: Run integrity checks
10. **Upload**: Save JSON to S3
11. **Notify**: Send completion message to DB_FILLER_QUEUE
12. **Cleanup**: Delete temp files and SQS message

## Output Format

### S3 Output

```
s3://my-tender-documents-bucket/tenders_doc_final/{tender_ref}/nova_extracted_metadata.json
```

### JSON Structure

```json
{
  "tender_info": {
    "tender_reference": "DSAO01_2026_ABC",
    "buyer": "Office Chérifien des Phosphates",
    "buyer_initials": "OCP",
    "deadline": "2026-02-15T15:00:00",
    "location": "Casablanca",
    "global_budget": 5000000.0,
    ...
  },
  "lots": [
    {
      "lot_number": "1",
      "lot_reference": "DSAO01_2026_ABC_1",
      "title": "Construction de bâtiments",
      "budget_lot": 2000000.0
    }
  ],
  "products": [
    {
      "designation": "Béton armé",
      "unit": "m3",
      "quantity": 500.0,
      "estimated_price": 1200.0,
      "lot_number": "1"
    }
  ]
}
```

### SQS Completion Message

```json
{
  "tender_ref": "DSAO01_2026_ABC",
  "tender_id": 12345,
  "metadata_key": "tenders_doc_final/DSAO01_2026_ABC/nova_extracted_metadata.json",
  "status": "nova_extraction_complete",
  "documents_processed": 8,
  "documents_skipped": 3,
  "processing_time_seconds": 45.2
}
```

## Development

### Local Testing

1. Set up environment:

   ```bash
   cp .env.example .env
   # Configure .env with your credentials
   ```

2. Run without Docker:

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python main.py
   ```

### Project Structure

```
nova_extraction_container/
├── main.py                   # Main orchestration
├── config.py                 # Configuration
├── logger.py                 # Logging utilities
├── s3_utils.py              # S3 client
├── sqs_utils.py             # SQS client
├── src/
│   ├── __init__.py
│   ├── models.py            # Pydantic models
│   ├── prompts.py           # Universal prompts (NEW)
│   ├── document_classifier.py  # Document classification
│   ├── pdf_processor.py     # PDF text/image processing
│   ├── nova_extractor.py    # Nova Lite extraction
│   ├── text_layer_detector.py  # Text layer detection
│   └── integrity.py         # Data validation
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Unified Prompt System

The container uses a **universal prompt approach** for maximum robustness:

**Key Benefits**:

- ✅ **Robustness**: Works correctly even when document classification fails
- ✅ **Reliability**: Handles `unknown` or misclassified documents gracefully
- ✅ **Maintainability**: Single source of truth for extraction rules
- ✅ **Flexibility**: LLM determines extraction strategy based on content

**How it works**:

1. Document is classified (for logging/filtering only)
2. Universal prompt is sent to LLM regardless of type
3. Prompt contains comprehensive instructions for ALL document types:
   - Avis (tender notices)
   - RC (administrative regulations)
   - CPS/CCTP (technical specifications)
   - BDP (pricing tables)
   - Administrative documents
   - Mixed/unknown documents
4. LLM intelligently extracts relevant data based on content
5. No type-specific branching = fewer failure points

**Prompts Module** (`src/prompts.py`):

- `get_extraction_prompt()` - Universal extraction for metadata, lots, products
- `get_chunking_prompt(content)` - Universal chunking for document segmentation

## Troubleshooting

### Container won't start

- Check `.env` file exists and is configured
- Verify AWS credentials are available
- Check Docker logs: `docker logs nova-extraction-container`

### OpenRouter API errors

- Verify `OPENROUTER_API_KEY` is correct
- Check OpenRouter credit balance
- Review rate limits

### No messages received

- Verify `OCR_QUEUE_URL` is correct
- Check SQS queue has messages
- Ensure IAM permissions allow SQS access

### Extraction failures

- Check logs for specific model errors
- Verify fallback models are accessible
- Review PDF quality (scanned vs text layer)

## Cost Optimization

- **Text Layer Detection**: Saves costs by using text extraction instead of OCR when possible
- **Smart Filtering**: Skips unnecessary documents (reduces API calls by ~30-40%)
- **Batch Processing**: Processes multiple documents per tender in one session
- **Fallback Chain**: Uses cheaper models when possible

## Migration from Old Containers

This container **replaces** both:

1. `ocr_container` - No longer needed
2. `extraction_container` - No longer needed

**Queue Migration**:

- Uses same queue as `ocr_container` (OCR_QUEUE_URL)
- Output goes to DB_FILLER_QUEUE (same as before)

**No database changes needed** - output format is compatible.

## License

Internal project - not for public distribution.
