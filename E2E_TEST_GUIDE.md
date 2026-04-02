# End-to-End Single-Tender Test Guide

This guide explains how to run the complete 5-stage pipeline for testing a single tender using the `e2e_test.sh` helper script.

## Quick Start

**Run a complete end-to-end test with logging:**

```bash
cd /home/naoufel/projects/tender_scrape
bash e2e_test.sh --build --limit 1 --monitor
```

This will:
1. Build all Docker images
2. Create the shared Docker network
3. Start Fuseki (triple store) on port 3030
4. Start OCR, Classification, Extraction, and Ingestion microservices
5. Run the scraper limited to 1 tender
6. Tail logs from all containers in real-time

**Stop all services when done:**

```bash
bash e2e_test.sh --stop
```

---

## Pipeline Overview

The pipeline has 5 stages connected via AWS SQS and S3:

```
┌──────────────┐
│  1_Update    │  Web scraper → S3 + SQS
└──────┬───────┘
       ↓ (OCR_QUEUE)
┌──────────────┐
│  2_Ocr       │  PDF → Markdown + SQS
└──────┬───────┘
       ↓ (CLASSIFICATION_QUEUE)
┌──────────────────────┐
│ 3_Classification     │  Document type detection + SQS
└──────┬───────────────┘
       ↓ (EXTRACTION_QUEUE)
┌──────────────┐
│ 4_Extraction │  Markdown → JSON chunks + SQS
└──────┬───────┘
       ↓ (DB_FILLER_QUEUE)
┌──────────────┐
│ 5_Ingestion  │  JSON → RDF → Apache Jena
└──────────────┘
```

---

## Script Options

### `--build`
Force rebuild all Docker images. Useful when code has changed.

```bash
bash e2e_test.sh --build
```

Without `--build`, cached images are used (faster startup).

### `--limit N`
Process only N tenders (default: 1). Useful for testing with more data.

```bash
bash e2e_test.sh --limit 5
```

### `--skip-scraper`
Skip the web scraper (1_Update) and use an existing `new_references.json`.

**Useful when**: The scraper times out or you want to test only the pipeline stages.

```bash
bash e2e_test.sh --skip-scraper --monitor
```

**Prerequisites**: You must have `1_Update/new_references.json` with tender references already populated.

### `--monitor`
After startup, tail logs from all containers in real-time.

```bash
bash e2e_test.sh --monitor
```

Press `Ctrl+C` to stop monitoring (services keep running).

### `--stop`
Stop and remove all test containers and services.

```bash
bash e2e_test.sh --stop
```

This removes running containers but **keeps the Docker network** (you can remove it manually if needed).

### `--help`
Show usage information.

```bash
bash e2e_test.sh --help
```

---

## Common Usage Patterns

### Pattern 1: Fresh Build & Test

```bash
bash e2e_test.sh --build --limit 1 --monitor
```

- **When to use**: After pulling code changes, first-time setup
- **What it does**: Rebuilds all images, starts everything, runs 1 tender, shows live logs

### Pattern 2: Quick Test (Cached Images)

```bash
bash e2e_test.sh --monitor
```

- **When to use**: Testing without code changes
- **What it does**: Uses cached images (faster), runs 1 tender, shows logs

### Pattern 3: Batch Test (Multiple Tenders)

```bash
bash e2e_test.sh --build --limit 5
```

- **When to use**: Testing with more data
- **What it does**: Rebuilds images, processes 5 tenders, no log monitoring
- **Verify**: Check Jena manually afterward

### Pattern 4: Skip the Scraper (Known Issues)

```bash
bash e2e_test.sh --skip-scraper --monitor
```

- **When to use**: Web scraper times out or `ref_updater.py` hangs
- **Prerequisite**: You have `1_Update/new_references.json` with tender refs
- **What it does**: Skips Phase 1 (ref_updater.py), runs Phases 2-3 + stages 2-5

### Pattern 5: Cleanup

```bash
bash e2e_test.sh --stop
```

- **When to use**: Done testing, want to stop all containers
- **What it does**: Removes all containers and services
- **Note**: Docker network persists (can be removed manually)

---

## Monitoring Data Flow

### Option 1: Live Log Monitoring

Run with `--monitor` flag to see logs from all stages in real-time:

```bash
bash e2e_test.sh --monitor
```

Key log markers to watch for:

- **2_Ocr**: `"Processing tender_ref: AO_XXX"` → `"Uploaded markdown to S3"`
- **3_Classification**: `"Classified as: avis|administrative|specification"` → `"Posted to EXTRACTION_QUEUE"`
- **4_Extraction**: `"Extracting chunks..."` → `"Posted N JSON chunks to DB_FILLER_QUEUE"`
- **5_Ingestion**: `"Inserted N triples into Jena"` → `"Embedding vectors generated and stored"`

### Option 2: Manual Monitoring After Startup

After starting services without `--monitor`, check progress separately:

**View current logs:**

```bash
docker-compose -f 5_Ingestion/docker-compose.fuseki.yml logs -f kb_ingestion
docker-compose -f 2_Ocr/docker-compose.yml logs -f ocr-service
docker logs -f e2e_classification
docker logs -f e2e_extraction
```

**Check SQS queue depths:**

```bash
aws sqs get-queue-attributes \
  --queue-url $OCR_QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages
```

(Replace `$OCR_QUEUE_URL` with actual queue URL from `.env`)

---

## Verification: Check Jena for Results

After the tender flows through all stages, verify it landed in Jena:

### Web UI

Open Jena Fuseki UI in a browser:

```
http://localhost:3030
```

Navigate to the dataset (e.g., `tenders`) and run a SPARQL query:

```sparql
SELECT DISTINCT ?type (COUNT(?s) as ?count)
WHERE {
  ?s a ?type .
}
GROUP BY ?type
LIMIT 10
```

This shows all RDF types and their counts. Should see entries for `Tender`, `Avis`, `Lot`, `Product`, etc.

### Command Line

Query Jena via curl:

```bash
curl -s -X POST "http://localhost:3030/tenders/query" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "query=SELECT%20*%20WHERE%20%7B%20%3Fs%20a%20%3Fo%20%7D%20LIMIT%2010"
```

Or count all triples:

```bash
curl -s -X POST "http://localhost:3030/tenders/query" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "query=SELECT%20(COUNT(%3Fs)%20as%20%3Fcount)%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20%7D"
```

---

## Troubleshooting

### Issue: Fuseki healthcheck fails

**Symptom**: Script exits with "Fuseki healthcheck failed after 60s"

**Causes**:
- Docker out of memory
- Port 3030 already in use
- Fuseki image couldn't start

**Solution**:

```bash
# Check if container is running
docker ps | grep fuseki

# View Fuseki logs
docker logs fuseki

# Kill any lingering processes on port 3030
lsof -ti :3030 | xargs kill -9 2>/dev/null || true

# Retry
bash e2e_test.sh --stop
bash e2e_test.sh
```

### Issue: ref_updater.py times out (Phase 1)

**Symptom**: Script hangs at "PHASE 1: Reference comparison"

**Cause**: Website `marchespublics.gov.ma` is slow or unreachable

**Solution**: Use `--skip-scraper` flag

```bash
# Pre-populate new_references.json with test data, then:
bash e2e_test.sh --skip-scraper --monitor
```

Or manually provide tender references in `1_Update/new_references.json`:

```json
{
  "new_references": [
    "AO_123_2024",
    "AO_124_2024"
  ]
}
```

### Issue: SQS queue not configured

**Symptom**: Logs show "Queue URL not found" or "InvalidQueueName"

**Cause**: `.env` files missing SQS queue URLs

**Solution**:

1. Ensure AWS credentials are set in `.env`:
   ```bash
   echo "OCR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../ocr-queue" >> .env
   ```

2. Or, if using local SQS mock (LocalStack), configure endpoints:
   ```bash
   export AWS_ENDPOINT_URL=http://localhost:4566
   ```

### Issue: S3 upload fails

**Symptom**: "NoCredentialsError" or "Access Denied" in 2_Ocr or 4_Extraction logs

**Solution**:

1. Check AWS credentials in `.env`:
   ```bash
   grep AWS_ACCESS_KEY_ID .env
   grep AWS_SECRET_ACCESS_KEY .env
   ```

2. Verify bucket exists:
   ```bash
   aws s3 ls s3://my-tender-documents-bucket/
   ```

3. Or, use AWS CLI to test:
   ```bash
   aws sts get-caller-identity
   ```

### Issue: SHACL validation hangs

**Symptom**: 5_Ingestion logs show "Validating against shapes..." but then no progress

**Cause**: Complex SHACL shapes can hang on large graphs

**Solution**: Set `SKIP_SHACL=true` in `5_Ingestion/.env`

```bash
echo "SKIP_SHACL=true" >> 5_Ingestion/.env
bash e2e_test.sh --skip-scraper --monitor
```

---

## Stopping Services

### Keep Services Running (for further testing)

After running the test, services stay running. You can:

- Re-run the scraper: `cd 1_Update && bash run_updates.sh`
- Query Jena: `http://localhost:3030`
- Stop whenever ready: `bash e2e_test.sh --stop`

### Stop Everything

```bash
bash e2e_test.sh --stop
```

To also remove the Docker network:

```bash
docker network rm tender_network
```

---

## Performance Notes

- **First run**: ~5-10 minutes (image builds + scraping + processing)
- **Cached run**: ~2-5 minutes (depends on document complexity)
- **Per-tender time**: ~30-120s (OCR slowest, depends on PDF size)

The script processes tenders sequentially through each stage (SQS-based polling).

---

## File Locations

Critical files for the test:

| File | Purpose |
|------|---------|
| `e2e_test.sh` | Main orchestration script |
| `.env` | Root-level configuration |
| `1_Update/.env` | Scraper config |
| `2_Ocr/.env` | OCR service config |
| `3_Classification/.env` | Classification config |
| `4_Extraction/.env` | Extraction config |
| `5_Ingestion/.env` | Ingestion config |
| `5_Ingestion/docker-compose.fuseki.yml` | Fuseki + Ingestion compose |
| `2_Ocr/docker-compose.yml` | OCR compose |
| `1_Update/new_references.json` | Tender references to process |
| `1_Update/tenders_metadata/` | Generated tender metadata |

---

## Docker Containers

After running `e2e_test.sh`, these containers are active:

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `fuseki` | `stain/jena-fuseki:latest` | 3030 | Triple store |
| `kb_ingestion` | `tender-ingestion:latest` | — | RDF ingestion microservice |
| `ocr-container` | `tender-ocr:latest` | — | OCR microservice |
| `e2e_classification` | `tender-classification:latest` | — | Classification microservice |
| `e2e_extraction` | `tender-extraction:latest` | — | Extraction microservice |

View running containers:

```bash
docker ps
```

View all container logs:

```bash
docker logs <container-name>
```

---

## Related Documentation

- **CLAUDE.md** — Project architecture and conventions
- **1_Update/CLAUDE.md** — Scraper stage details
- **5_Ingestion/CLAUDE.md** — Ingestion stage details
- **Memory** — `pipeline_operations.md`, `pipeline_fixes_2026-03-31.md`

---

## Questions?

For issues or questions:

1. Check the **Troubleshooting** section above
2. Review stage-specific **CLAUDE.md** files
3. Check container logs: `docker logs <container>`
4. Check SQS queue depths and S3 uploads
