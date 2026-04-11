# 5_Ingestion: Knowledge Graph Ingestion Service

This is the **fifth stage** of the pipeline: consuming structured JSON chunks, mapping them to RDF, validating against an OWL ontology, and persisting to an Apache Jena triple store.

## Purpose

- **Poll** SQS `DB_FILLER_QUEUE` for extracted JSON data.
- **Enrich** tender data by fetching all related JSON chunks from S3.
- **Map** JSON data to RDF triples using `JsonToRdfMapper`.
- **Validate** quality using **Test-Driven Data (TDD)**: SHACL shape validation before insertion.
- **Persist** to Apache Jena Fuseki triple store.
- **Generate** vector embeddings for document chunks and store them in S3.
- **Track** ingestion status via the shared `monitor` module.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer and main KBIngestor orchestration. |
| `src/json_to_rdf.py` | Logic for mapping Pydantic models to RDF triples. |
| `src/data_tester.py` | SHACL validation and business logic constraints. |
| `src/jena_client.py` | Client for SPARQL updates to Fuseki. |
| `src/embedding_client.py`| Client for generating vector embeddings. |
| `monitor.py` | (Symlink) Event emitter for pipeline tracking. |
| `ontology/` | Directory containing OWL definitions and SHACL shapes. |

## Monitoring Integration

This stage emits events to `pipeline.db` using the `monitor` module:
- `enter`: Called when ingestion starts for a tender.
- `complete`: Called when triples are inserted and embeddings are saved.
- `failed`: Called on SHACL validation failures or SPARQL errors.

## Data Flow

```
SQS Input (DB_FILLER_QUEUE)
  ↓
Fetch all JSON chunks from S3 (extracted_json/{tender_ref}/)
  ↓
JSON → RDF Mapping (rdflib)
  ↓
SHACL Validation (src/data_tester.py)
  ↓
SPARQL INSERT (Apache Jena)
  ↓
Vector Embeddings (OpenRouter) → Upload to S3
```

## Local Development

### Setup
```bash
cd 5_Ingestion
pip install -r requirements.txt
```

### Commands
```bash
# Run the ingestion service
python main.py

# Run SHACL validation tests
pytest tests/test_data_tester.py
```

## Configuration

| Variable | Purpose | Example |
|---|---|---|
| `KB_INGESTION_QUEUE_URL` | Input queue URL | — |
| `JENA_ENDPOINT` | Fuseki base URL | `http://fuseki:3030` |
| `JENA_DATASET` | Dataset name | `tenders` |
| `ONTOLOGY_DIR` | Path to OWL/SHACL files | `/app/ontology` |
| `VALIDATION_STRICT` | Abort on SHACL failures | `true` |

## Integration Notes

- **Primary Ingestion**: This stage completes the ingestion of the *initial* tender data (announcement, specs, BDP).
- **Post-Deadline Results**: Award information is handled separately by Stage 8.
