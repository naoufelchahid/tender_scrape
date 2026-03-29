# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

Moroccan public tender scraper subsystem. Scrapes marchespublics.gov.ma, compares with Apache Jena Fuseki triple store (AWS EC2), downloads tender ZIP files, uploads to S3, then removes processed entries from the JSON input file. The system uses RDF for data representation and SPARQL for queries.

## Critical Architecture

- **Parent project dependency**: imports `database.models` and `scraper.browser_config` from parent dir via `PYTHONPATH="$SCRIPT_DIR/..:$PYTHONPATH"` — code cannot run from this directory alone.
- **Local `browser_config/` is unused**: both scripts import `create_browser` from parent's `scraper.browser_config`, NOT from the local `browser_config/browser_config.py`.
- **Three-phase pipeline** orchestrated by `run_updates.sh`:
  - **Phase 1** (Reference Fetching): runs `ref_updater.py` per category (services, travaux, fournitures — in that order)
  - **Phase 2** (Data Processing): runs `Db_updater.py` per category to download tender files and upload to S3
  - **Phase 3** (Knowledge Graph Build): runs `kg_builder.py` per category to build RDF triples and upload N-Triples to S3
- **Apache Jena Integration**: Uses `rdflib` Python library to interact with Jena Fuseki via SPARQL 1.1 endpoints. All tender data is stored as RDF triples using the MoroccanTenders ontology.
- **Composite references**: tenders are identified by `{original_reference}_{buyer_initials}` (e.g., `33/2025/ALEM_AGELOGEQUMIL`). The `generate_initials()` logic is duplicated in both scripts and must stay in sync — it strips French articles, uses full words for 2-3 word names, first-3-letters-per-word for 4+ words.
- **Both scripts run headed** (`headless=False`) — `playwright_stealth` + fake Moroccan identities fill forms. The site actively blocks automation.
- Processed tenders are **removed from the input JSON file** after successful S3 upload, making the JSON file a mutable work queue.
- Date parsing includes a fix for malformed dates without spaces (e.g., `03/02/202610:00` → `03/02/2026 10:00`).
- S3 metadata must be ASCII-safe — `_sanitize_metadata()` strips accents via NFKD normalization.
- **Phase 3 (kg_builder.py)**: Reads `processed_tenders.json` from Phase 2, builds RDF triples using `tender_structure.owl`, validates with SHACL constraints (`tender_shacl_shapes.ttl`), and uploads N-Triples to S3 at `knowledge_Base/Daybatch/batch_YYYYMMDD_HHMMSS.nt`.

## Commands

```bash
# Full pipeline (all three phases, all 3 categories)
bash run_updates.sh

# Phase 1 only: fetch new references for one category
python3 ref_updater.py --category services --output new_references_services.json

# Phase 2 only: process tenders from a references file
python3 Db_updater.py --input-file new_references_services.json --max-tenders 10

# Phase 3 only: build knowledge graph from processed tenders
python3 kg_builder.py --input-file processed_tenders_services.json
```

## Phase 3: Knowledge Graph Builder (`kg_builder.py`)

### Input Structure

The `kg_builder.py` reads `processed_tenders.json` files produced by `Db_updater.py`. Each file contains:

```json
{
  "processed_date": "2026-03-25T16:00:00",
  "total_processed": 5,
  "tenders": [
    {
      "reference": "33/2025/ALEM_AGELOGEQUMIL",
      "original_reference": "33/2025/ALEM",
      "buyer": "Agence logistique des equipements militaires",
      "category": "fournitures",
      "object": "Acquisition de pièces de rechange",
      "launch_date": "03/02/2026",
      "deadline": "03/02/2026 10:00",
      "city": "Rabat",
      "s3_folder": "tender-documents/33_2025_ALEM_AGELOGEQUMIL/",
      "processed_at": "2026-03-25T16:00:00",
      "lots": [
        {
          "lot_number": 1,
          "designation": "Lot unique",
          "budget": "150000",
          "caution": "1500"
        }
      ]
    }
  ]
}
```

### JSON → OWL Property Mapping

| JSON field | OWL Property | XSD Type | Required |
|---|---|---|---|
| `reference` | `ts:Ref` | `xsd:string` | Yes |
| `original_reference` | `ts:Has_Original_Reference` | `xsd:string` | Yes |
| `object` | `ts:Has_Object` | `xsd:string` | Yes |
| `deadline` | `ts:Has_Deadline` | `xsd:dateTime` | No |
| `launch_date` | `ts:Has_Publication_Date` | `xsd:dateTime` | No |
| `city` | `ts:Has_City` | `xsd:string` | No |
| `category` | `ts:Has_Category` | ObjectProperty → `activity:*` | No |
| `s3_folder` | `ts:Has_CPS_Doc` | `xsd:anyURI` | No |
| `buyer` | `ts:Launched_by` | ObjectProperty → `ts:Buyers` | Yes |
| `lots` presence | `ts:Has_Multilot` | `xsd:boolean` | Always |

### Validation Pipeline

1. **Consistency Check**: SPARQL ASK queries verify ontology constraints (every Tender has type, Launched_by, Has_Object, Ref; every Buyer has type and label)
2. **SHACL Validation**: Uses `pyshacl` to validate against `tender_shacl_shapes.ttl`
3. **S3 Upload**: Only proceeds if validation passes

### Exit Codes

- 0: Success
- 1: Input error (file missing or malformed JSON)
- 2: Consistency check failed
- 3: SHACL validation failed
- 4: S3 upload failed

## Environment

Requires `.env` with: `JENA_ENDPOINT` (SPARQL query endpoint URL), `JENA_UPDATE_ENDPOINT` (for INSERT/DELETE), `JENA_USERNAME`, `JENA_PASSWORD` (Jena Fuseki auth), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`. Virtual env expected at `./venv` or `../venv`.
