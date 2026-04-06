# Result Scrape Refactor — Design Spec

**Date:** 2026-04-06
**Status:** Draft

## Overview

Refactor the `Result_scrape/` pipeline into two new stages (`6_Result_Update`, `7_Result_Ingestion`) that replace the RDS-based approach with Fuseki/Jena, share OCR with the tender pipeline, and add full RDF ingestion with SHACL validation.

## Architecture & Data Flow

```
6_Result_Update/
  SPARQL query Fuseki → scrape marchespublics.gov.ma → upload PDF to S3 → RESULTS_OCR_QUEUE

2_Ocr/ (modified)
  Polls OCR_QUEUE (tenders) AND RESULTS_OCR_QUEUE (results)
  Results path: OCR → upload markdown to S3 → RESULTS_INGESTION_QUEUE

7_Result_Ingestion/
  Polls RESULTS_INGESTION_QUEUE → fetch markdown from S3
  → call Ollama (deepseek-r1:1.5b) for structured extraction
  → map JSON → RDF (TenderResults, TenderBids, Contractor)
  → SHACL validation + logical assertions
  → INSERT into Jena
  → set ts:Is_Result=true on tender node
```

### SQS Queues (new)

| Queue | Producer | Consumer |
|-------|----------|----------|
| `RESULTS_OCR_QUEUE` | 6_Result_Update | 2_Ocr |
| `RESULTS_INGESTION_QUEUE` | 2_Ocr | 7_Result_Ingestion |

### S3 Paths

| Path | Content | Producer |
|------|---------|----------|
| `tender_results/{ref}_result.pdf` | Raw result PDFs | 6_Result_Update |
| `Results_markdown/markdown_files/{ref}.md` | OCR markdown output | 2_Ocr |

## 6_Result_Update — Fuseki Query & Scraping

### Fuseki Query

Find tenders where deadline passed by at least 1 day and `ts:Is_Result` is not set:

```sparql
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?tender ?ref ?originalRef ?buyer WHERE {
  ?tender a ts:Tenders ;
          ts:Ref ?ref .
  ?tender ts:Has_Deadline ?deadline .
  FILTER(?deadline < "{{yesterday}}"^^xsd:dateTime)
  FILTER NOT EXISTS { ?tender ts:Is_Result "true"^^xsd:boolean }
  OPTIONAL { ?tender ts:Has_Original_Reference ?originalRef }
  OPTIONAL { ?tender ts:Launched_by ?buyerNode .
             ?buyerNode rdfs:label ?buyer }
}
```

Where `{{yesterday}}` is computed as `datetime.now() - timedelta(days=1)` formatted as `xsd:dateTime`.

### Scraping Flow

1. For each tender returned by SPARQL, extract `originalRef`. If missing, derive from composite ref: `ref.rsplit('_', 1)[0]`.
2. Navigate to marchespublics.gov.ma advanced search, fill `originalRef`, select type "Annonce d'extrait de PV" (value `5`).
3. Match the correct result row using the tuple `(original_reference, buyer_name)`:
   - Extract buyer name from `panelBlocDenomination` div on the search results page.
   - Normalize both buyer names (strip accents, lowercase, collapse whitespace).
   - Compare `(originalRef, normalized_buyer_from_page)` against `(originalRef, normalized_buyer_from_fuseki)`.
4. If matched → click through to detail page → download "Fichier joint" PDF.
5. If not found → skip (results not published yet).
6. Upload PDF to S3: `tender_results/{ref}_result.pdf`.
7. Send SQS message to `RESULTS_OCR_QUEUE`:

```json
{
  "tender_ref": "003_2026_SRMCS",
  "s3_key": "tender_results/003_2026_SRMCS_result.pdf",
  "bucket": "tender-scrape-data",
  "timestamp": "2026-04-06T10:00:00"
}
```

### Dependencies

- `playwright`, `playwright-stealth`, `beautifulsoup4` — web scraping
- `boto3` — S3 upload, SQS send
- `requests` — Fuseki SPARQL HTTP
- No RDS/PostgreSQL dependency

## 2_Ocr Modifications — Dual Queue Polling

### Changes

1. **New env vars:** `RESULTS_OCR_QUEUE_URL`, `RESULTS_INGESTION_QUEUE_URL`
2. **`config.py`:** Add new env var declarations.
3. **`sqs_utils.py`:** Already supports `queue_url` parameter — no structural change needed.
4. **`monitor.py` (main loop):** Add dual-queue polling:
   - Poll `OCR_QUEUE` — process → send to `CLASSIFICATION_QUEUE` (existing)
   - Poll `RESULTS_OCR_QUEUE` — same OCR processing → upload markdown to `Results_markdown/markdown_files/{ref}.md` → send to `RESULTS_INGESTION_QUEUE`
5. **Routing decision:** Based on which queue the message came from (no `type` field needed).
6. **`docker-compose.yml`:** Add new env vars.

### SQS Message to RESULTS_INGESTION_QUEUE

```json
{
  "tender_ref": "003_2026_SRMCS",
  "markdown_s3_key": "Results_markdown/markdown_files/003_2026_SRMCS.md",
  "bucket": "tender-scrape-data",
  "timestamp": "2026-04-06T10:05:00"
}
```

OCR processing is identical for both paths — same `DocumentProcessor`, same GPU pipeline. Only downstream routing differs.

## 7_Result_Ingestion — Extraction, RDF Mapping, Validation & Ingestion

### SQS Polling & Markdown Fetch

- Poll `RESULTS_INGESTION_QUEUE`
- Download markdown from S3 at `markdown_s3_key`

### Structured Extraction via Ollama

- Call `http://ollama:11434/v1/chat/completions` with model `deepseek-r1:1.5b`
- Same extraction prompt pattern as current `data_extractor.py`:
  - Extract lots, winner (company_name, winning_amount), bidders (company_name, bid_amount, status, rejection_reason)
  - Parse JSON response into structured data
- Temperature: 0.1 for deterministic output

### RDF Mapping (following ontology)

For each lot in the extracted data:

**TenderResults node:**
```turtle
ts:Result_{ref}[_lotIdx]  a  ts:TenderResults .
ts:Tender_{ref}  ts:Is_Opened  ts:Result_{ref} .
ts:Result_{ref}  ts:Is_Proces_Verbal_of  ts:Tender_{ref} .
ts:Result_{ref}  ts:Has_PV  "true"^^xsd:boolean .
```

**Winner — TenderBids + Contractor nodes:**
```turtle
ts:Bid_Winner_{ref}[_lotIdx]  a  ts:TenderBids .
ts:Result_{ref}  ts:Is_Winner_Bid  ts:Bid_Winner_{ref} .
ts:Result_{ref}  ts:Has_Bid  ts:Bid_Winner_{ref} .
ts:Bid_Winner_{ref}  ts:Is_Bid_in  ts:Result_{ref} .
ts:Bid_Winner_{ref}  ts:Has_Bid_Amount  "123456.78"^^xsd:decimal .

ts:Contractor_{slug}  a  ts:Contractor .
ts:Contractor_{slug}  rdfs:label  "Company Name" .
ts:Bid_Winner_{ref}  ts:Is_Bid_of  ts:Contractor_{slug} .
ts:Contractor_{slug}  ts:Formulate_Bid  ts:Bid_Winner_{ref} .
```

**Other bidders (admitted/rejected):**
```turtle
ts:Bid_{ref}_{idx}  a  ts:TenderBids .
ts:Result_{ref}  ts:Has_Bid  ts:Bid_{ref}_{idx} .
ts:Bid_{ref}_{idx}  ts:Is_Bid_in  ts:Result_{ref} .
ts:Bid_{ref}_{idx}  ts:Has_Bid_Amount  "..."^^xsd:decimal .
ts:Bid_{ref}_{idx}  ts:Is_Bid_of  ts:Contractor_{slug} .
ts:Contractor_{slug}  ts:Formulate_Bid  ts:Bid_{ref}_{idx} .

# If rejected:
ts:Result_{ref}  ts:Rejected_Bid  ts:Bid_{ref}_{idx} .
```

**Tender update (after successful ingestion):**
```turtle
ts:Tender_{ref}  ts:Is_Result  "true"^^xsd:boolean .
```

### URI Generation

| Node | URI Pattern |
|------|-------------|
| TenderResults | `ts:Result_{slugify(ref)}` or `ts:Result_{slugify(ref)}_{lotIdx}` for multi-lot |
| Winner Bid | `ts:Bid_Winner_{slugify(ref)}_{lotIdx}` |
| Other Bid | `ts:Bid_{slugify(ref)}_{lotIdx}_{bidIdx}` |
| Contractor | `ts:Contractor_{slugify(company_name)}` |

`slugify()` reuses the same logic as `kg_builder.py` (strip accents, replace special chars with `_`, uppercase).

### SHACL Validation

New file `shapes_results.ttl`:

```turtle
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix ts:  <http://www.tenderintelligence.io/ontology/tender-structure#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ts:TenderResultsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderResults ;
    sh:property [
        sh:path ts:Is_Proces_Verbal_of ;
        sh:minCount 1 ;
        sh:message "A TenderResults must link to a Tender via ts:Is_Proces_Verbal_of." ;
    ] ;
    sh:property [
        sh:path ts:Has_Bid ;
        sh:minCount 1 ;
        sh:message "A TenderResults must have at least one Bid (ts:Has_Bid)." ;
    ] .

ts:TenderBidsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderBids ;
    sh:property [
        sh:path ts:Is_Bid_of ;
        sh:minCount 1 ;
        sh:message "A TenderBids must link to a Contractor via ts:Is_Bid_of." ;
    ] ;
    sh:property [
        sh:path ts:Is_Bid_in ;
        sh:minCount 1 ;
        sh:message "A TenderBids must link to a TenderResults via ts:Is_Bid_in." ;
    ] .
```

### Logical Assertions

- Every TenderResults must link back to an existing Tender in Jena (ASK query)
- Winner bid must have `Has_Bid_Amount > 0`
- Winner bid's contractor must exist as a node in the graph
- At least one `Is_Winner_Bid` per TenderResults

### Jena Insert

- Serialize graph as N-Triples (`graph.serialize(format="nt")`)
- `INSERT DATA` via SPARQL UPDATE (same pattern as `5_Ingestion/src/jena_client.py`)
- Separate `INSERT DATA` to set `ts:Is_Result "true"^^xsd:boolean` on the tender node

### Post-ingestion Quality Gates

- ASK: tender has a TenderResults node via `ts:Is_Opened`
- ASK: at least one TenderBids linked to the result via `ts:Has_Bid`

## File Structure

```
6_Result_Update/
├── result_updater.py       # Main entry: Fuseki query → scrape → S3 → SQS
├── fuseki_client.py         # SPARQL queries to find pending tenders
├── scraper.py               # Playwright scraping logic
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.template
└── run_result_update.sh

7_Result_Ingestion/
├── result_ingestor.py       # Main entry: SQS poll → extract → RDF → validate → Jena
├── ollama_client.py         # Ollama API calls for structured extraction
├── rdf_mapper.py            # JSON → RDF mapping (TenderResults, TenderBids, Contractor)
├── uri_builder.py           # URI generation for result/bid/contractor nodes
├── shacl_validator.py       # SHACL + logical assertions
├── jena_client.py           # SPARQL query/update (reuse pattern from 5_Ingestion)
├── ontology/
│   ├── tender_structure_final.owl
│   └── shapes_results.ttl
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.template

2_Ocr/ (modified files only)
├── monitor.py               # Add dual-queue polling loop
├── sqs_utils.py             # Add RESULTS_OCR_QUEUE routing
├── config.py                # Add new env vars
└── docker-compose.yml       # Add new env vars
```

## Ontology Change

Add one new data property to the tender node:

```turtle
ts:Is_Result
    a owl:DatatypeProperty ;
    rdfs:domain ts:Tenders ;
    rdfs:range xsd:boolean ;
    skos:prefLabel "A des resultats"@fr ;
    skos:definition "Indique si les resultats de l'appel d'offres ont ete trouves et ingeres."@fr .
```

This property is set to `true` after successful result ingestion. The `6_Result_Update` SPARQL query filters on `FILTER NOT EXISTS { ?tender ts:Is_Result "true"^^xsd:boolean }` to avoid re-processing.

## Environment Variables

### 6_Result_Update
```
JENA_ENDPOINT=http://fuseki:3030
JENA_DATASET=tenders
JENA_USERNAME=admin
JENA_PASSWORD=admin
AWS_REGION=eu-west-3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=tender-scrape-data
RESULTS_OCR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../RESULTS_OCR_QUEUE
```

### 7_Result_Ingestion
```
JENA_ENDPOINT=http://fuseki:3030
JENA_DATASET=tenders
JENA_USERNAME=admin
JENA_PASSWORD=admin
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=deepseek-r1:1.5b
AWS_REGION=eu-west-3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=tender-scrape-data
RESULTS_INGESTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../RESULTS_INGESTION_QUEUE
```

### 2_Ocr (additions)
```
RESULTS_OCR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../RESULTS_OCR_QUEUE
RESULTS_INGESTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/.../RESULTS_INGESTION_QUEUE
```
