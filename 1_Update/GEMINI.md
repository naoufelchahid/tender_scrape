# 1_Update: Scraper & Data Updater

This is the **first stage** of the pipeline: scraping tender metadata and documents from the procurement portal and initiating the processing flow.

## Purpose

- **Scrape** the Moroccan procurement portal (marchespublics.gov.ma) for new tenders.
- **Extract** metadata: reference, buyer, categories, deadlines, lots, and estimated budget.
- **Download** tender documents (ZIP files containing PDFs/DOCs).
- **Upload** raw files and metadata JSON to S3.
- **Initiate** the pipeline by sending tender references to the `OCR_QUEUE`.

## Key Files

| File | Purpose |
|------|---------|
| `Db_updater.py` | Main scraper entry point. Manages the scraping sessions and S3 uploads. |
| `ref_updater.py` | Updates reference data (categories, regions, buyers) in the Knowledge Graph. |
| `kg_builder.py` | Helper for building the initial RDF structure for a new tender. |
| `browser_config/` | Playwright configuration for the scraper. |

## Workflow

1. **Search**: The scraper navigates the portal using Playwright to find new tenders.
2. **Metadata Extraction**: Parses the tender details page for structured information.
3. **Document Download**: Identifies and downloads the consultation documents.
4. **S3 Storage**:
   - Metadata: `tenders_metadata/{tender_ref}.json`
   - Documents: `tender_doc_final/{tender_ref}/*.pdf`
5. **Queue**: Sends a message to `OCR_QUEUE` to trigger Stage 2.

## Local Development

### Setup
```bash
cd 1_Update
pip install -r requirements.txt
playwright install
```

### Commands
```bash
# Run the main scraper
python Db_updater.py

# Update reference data
python ref_updater.py
```

## Integration Notes

- **Entry Point**: This stage is the source of all data in the pipeline.
- **Throttling**: The scraper includes delays to avoid being blocked by the portal.
- **S3 Layout**: Uses the `{tender_ref}` as the primary key for organizing documents in S3.
