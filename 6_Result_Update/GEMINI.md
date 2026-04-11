# 6_Result_Update: Result Update Service

This service handles the **sixth stage** of the pipeline (post-deadline): identifying tenders that have passed their submission deadline and scraping for award results (PV documents).

## Purpose

- **Identify** tenders in Apache Jena that are past their deadline but lack result data.
- **Scrape** the Moroccan procurement portal (marchespublics.gov.ma) for result PV (Procès-Verbal) documents.
- **Download** result PDFs and upload them to S3.
- **Trigger** the next stage by sending a message to the `RESULTS_OCR_QUEUE`.

## Key Files

| File | Purpose |
|------|---------|
| `result_updater.py` | Main service orchestrator. Queries Fuseki and manages the scraping loop. |
| `scraper.py` | Playwright-based scraper specialized in finding PV documents. |
| `fuseki_client.py` | Client for querying Jena Fuseki using SPARQL. |
| `Dockerfile` | Container definition for the service. |
| `run_result_update.sh`| Shell script to run the updater locally. |

## Workflow

1. **Query**: The service runs a SPARQL query against Jena to find Tender IRIs where `ts:deadline` < `NOW()` and no `ts:hasWinner` relation exists.
2. **Search**: For each identified tender, the `ResultScraper` navigates to the tender's result page on the portal.
3. **Extract**: If a PV document is found, it is downloaded.
4. **Persist**: The PDF is uploaded to S3 under `tender_results/{tender_ref}/pv.pdf`.
5. **Route**: A message is sent to SQS with the `tender_ref` and S3 path.

## Local Development

### Setup
```bash
cd 6_Result_Update
pip install -r requirements.txt
playwright install chromium
```

### Commands
```bash
# Run the result update service
python result_updater.py
```

## Configuration

| Variable | Purpose |
|---|---|
| `RESULTS_OCR_QUEUE_URL` | SQS queue for the next stage (Stage 7) |
| `JENA_ENDPOINT` | URL of the Fuseki server |
| `S3_BUCKET_NAME` | S3 bucket for storing PV documents |

## Integration Notes

- **Initial Pipeline Dependency**: This stage relies on Stage 5 having already ingested the tender metadata and deadline into Jena.
- **Dynamic Content**: Uses Playwright to handle the portal's dynamic tables and document links.
