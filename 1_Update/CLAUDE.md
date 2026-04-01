# 1_Update: Web Scraper Stage

This container handles the **first stage** of the pipeline: scraping tender data from marchespublics.gov.ma, extracting metadata, downloading documents, and uploading to S3 + knowledge graph.

## Purpose

- **Scrape** tender data from Morocco's public procurement website
- **Extract** 18 taxonomy fields from each tender (reference, buyer, categories, deadlines, lots, etc.)
- **Download** all available documents (PDFs, DOCs) from each tender
- **Upload** raw documents to S3 (`tender_doc_final/`) and metadata to local storage
- **Build** RDF knowledge graph triples from tender metadata
- **Update** reference data (regions, activities, suppliers) from official sources

## Key Files

| File | Purpose |
|------|---------|
| `Db_updater.py` | Main scraper entry point. Reads `new_references.json`, extracts metadata, downloads files, uploads to S3, saves per-tender JSON to `tenders_metadata/` |
| `kg_builder.py` | Converts tender metadata (JSON) → RDF triples in Turtle format. Handles SKOS mapping, URI normalization, vector embeddings |
| `ref_updater.py` | Updates reference data (regions, activity sectors, suppliers) from external sources. Fetches from `marchespublics.gov.ma` API endpoints |
| `analyze_graph.py` | Queries and analyzes the RDF knowledge graph (SPARQL). Generates statistics, validation reports |
| `visualize_graphistry.py` | Exports graph to Graphistry for visualization |
| `browser_config/` | Playwright browser configuration with stealth plugins |

## Data Flow

```
new_references.json (tender refs)
  ↓
Db_updater.py extracts metadata, downloads files
  ↓
S3: tender_doc_final/{tender_ref}/{file}   (raw PDFs/DOCs)
tenders_metadata/{tender_ref}.json        (metadata JSON)
processed_tenders.json                    (all processed tenders)
  ↓
kg_builder.py generates RDF triples
  ↓
Local RDF file (Turtle)
```

## Local Development

### Setup
```bash
cd 1_Update
pip install -r requirements.txt
```

### Environment Variables
```bash
# AWS credentials
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-west-3

# S3
S3_BUCKET_NAME=tender-scrape-data

# Playwright
HEADLESS_BROWSER=true  # false for visual debugging
```

### Running Commands

**Main scraper:**
```bash
python Db_updater.py
# Reads new_references.json, downloads files, uploads to S3, saves metadata
# Output: tenders_metadata/*.json, processed_tenders.json, S3 uploads
```

**Update reference data:**
```bash
python ref_updater.py
# Fetches regions, activities, suppliers from marchespublics API
# Handles website timeouts with retry logic
```

**Generate RDF knowledge graph:**
```bash
python kg_builder.py
# Converts processed_tenders.json → RDF Turtle triples
# Output: RDF file suitable for Jena ingestion
```

**Analyze graph:**
```bash
python analyze_graph.py
# Queries RDF triples using SPARQL
# Shows statistics, validation results
```

**Visualize graph:**
```bash
python visualize_graphistry.py
# Exports graph to Graphistry visualization platform
```

## Testing & Validation

### Smoke Tests
```bash
# Test metadata extraction
python -c "from Db_updater import extract_metadata; print('Import OK')"

# Test RDF generation
python -c "from kg_builder import build_graph; print('Import OK')"

# Verify S3 connectivity
python -c "import boto3; s3 = boto3.client('s3'); s3.list_buckets()"
```

### Debugging

**Scraper hangs:**
- Check Playwright browser initialization in `browser_config/browser_config.py`
- Monitor `Db_updater.py` logs for page timeouts
- If website is slow, adjust `WaitTimeSeconds` in page wait logic

**Metadata extraction failing:**
- Verify HTML structure on marchespublics.gov.ma hasn't changed
- Check BeautifulSoup CSS selectors in `Db_updater.py` (~line 200-300)
- Run on a single tender ref to isolate issue

**S3 upload errors:**
- Check AWS credentials in `.env`
- Verify bucket exists and is accessible: `aws s3 ls s3://tender-scrape-data`
- Check file permissions in `tenders_metadata/`

**Reference data timeout:**
- Known blocker: `ref_updater.py` hits website timeout during reference fetch
- Workaround: Set longer timeout or skip update: edit `ref_updater.py` timeout value

## Code Patterns

### Async Scraping
- Uses `asyncio` for concurrent page navigation and file downloads
- `playwright.async_api` for non-blocking browser automation
- Stealth plugins to avoid bot detection

### Metadata Extraction
- **18 taxonomy fields**: reference, buyer, categories, deadlines, lots, budget, regions, activity, suppliers
- Normalized per-tender JSON in `tenders_metadata/{ref}.json`
- All tenders aggregated in `processed_tenders.json`

### RDF Generation
- JSON → RDF mapping in `kg_builder.py` (function `build_graph`)
- Custom namespaces: `TS` (tender schema), `REGIONS`, `ACTIVITY`
- SKOS `exactMatch` for reference data alignment
- Vector embeddings for avis (if enabled)

## Integration Points

- **Input**: `new_references.json` (list of tender references to scrape)
- **Output to S3**: Raw documents in `tender_doc_final/{tender_ref}/`
- **Output locally**: Metadata in `tenders_metadata/`, aggregated in `processed_tenders.json`
- **Downstream**: 2_Ocr consumer reads raw documents from S3; 5_Ingestion reads RDF from this stage
- **SQS**: Does not produce SQS messages (1_Update is the pipeline source)

## Common Tasks

### Adding a New Metadata Field
1. Add CSS selector in `Db_updater.py` around line 250-300 (extraction logic)
2. Add field name to TAXONOMY_FIELDS dict
3. Update Pydantic model (if exists) to validate the new field
4. Re-run scraper: `python Db_updater.py`

### Debugging Website Changes
- The marchespublics.gov.ma HTML structure may change
- Check Network tab in browser DevTools for API endpoints used
- Update CSS selectors in `Db_updater.py` if selectors break

### Batch Re-processing Tenders
- Delete from `tenders_metadata/`, keep `processed_tenders.json` as reference
- Re-run `python Db_updater.py` for selective tenders
- Use tender ref filter at start of script to limit scope

## Deployment

### Docker
```bash
cd 1_Update
docker build -t tender-scrape-updater:latest .
docker run --env-file .env tender-scrape-updater:latest python Db_updater.py
```

### AWS ECS
- See root `CLAUDE.md` for full ECS deployment (uses `2_Ocr/deploy_to_ecs.sh` pattern)
- Requires ECR repository and task definition

## Related Documentation

- **Root CLAUDE.md**: Pipeline architecture, inter-stage contracts
- **5_Ingestion/CLAUDE.md**: RDF ingestion into Jena (receives output from this stage)
- **Memory**: `project_context.md`, `pipeline_operations.md`
