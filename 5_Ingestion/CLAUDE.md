# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_data_tester.py

# Run a specific test function
pytest tests/test_data_tester.py::test_passed_validation

# Run tests with verbose output
pytest -v tests/

# Run the ingestion service
python main.py

# Run standalone SHACL validation debug tool
python test_pyshacl.py
```

## Architecture

This is a **Knowledge Base Ingestion microservice** that consumes SQS messages, enriches tender data from S3, validates against an OWL ontology, and persists to an Apache Jena Fuseki triple store with vector embeddings in S3.

### Data Flow

```
SQS message (tender_ref)
  → locate Tender IRI in Jena via SPARQL
  → fetch chunked documents from S3
  → map JSON chunks to RDF triples (JsonToRdfMapper)
  → SHACL validation (DataTester)
  → SPARQL INSERT into Jena (jena_client)
  → concurrent embedding generation (OpenRouter via EmbeddingClient)
  → concurrent vector saves to S3 (VectorStorage)
  → export N-Triples to /tmp/nt_output (diagnostics/audit trail)
  → on failure: route message to DLQ
```

### Module Responsibilities

- **main.py** — `KBIngestor` orchestrates the full pipeline. The SQS polling loop calls `process_message()`, which dispatches to `_process_avis()`, `_process_products()`, `_process_doc_chunks()`.
- **src/json_to_rdf.py** — `JsonToRdfMapper` transforms Pydantic-validated metadata into rdflib `Graph` objects. Each document type has its own mapping method (`map_avis`, `map_products`, `map_specification`, `map_administrative`, `map_lots`).
- **src/data_tester.py** — `DataTester` runs a three-stage validation: SHACL shape check → SPARQL constraint checks → business logic checks (budget > 0, required relationships). Lazy-loads ontology/shapes on first use.
- **src/jena_client.py** — Dependency-injection pattern: accepts callable functions for SPARQL query/update so tests can inject mocks without subclassing.
- **src/models.py** — Pydantic v2 models for each document type. Validators handle French number formatting (spaces as thousands separator, commas as decimal, DH currency suffix).
- **src/uri_builder.py** — Single source of truth for all RDF namespaces (`TS`, `REGIONS`, `ACTIVITY`) and URI construction helpers.
- **src/embedding_client.py** — Sync and async wrappers around OpenRouter embedding API. `async_batch_get_embeddings()` uses `asyncio.gather()` for concurrency.
- **src/vector_storage.py** — Saves embedding vectors as JSON to S3 under `index/tender-index/{slug}/{doc_type}_chunk_{index}_vector.json`.

### Key Design Patterns

- **Dependency injection on JenaClient**: SPARQL functions are passed as callables, making unit tests straightforward with `unittest.mock.MagicMock`.
- **Chunk-as-node RDF pattern**: Document chunks become first-class RDF nodes linked to their parent tender entity, carrying metadata and an S3 vector key.
- **Multilot support**: Tenders with multiple lots produce individual `Lot` RDF nodes; `map_lots()` in `JsonToRdfMapper` handles this.
- **Async concurrency**: Embedding and vector storage use `asyncio.gather()` — keep this pattern when adding new async I/O.

### Ontology & Validation

- `ontology/tender_structure.owl` — OWL ontology defining the Tender class hierarchy. Loaded by `DataTester` for SHACL inference.
- `shapes.ttl` — SHACL shapes file (not committed; must be present at `ONTOLOGY_DIR` at runtime). Referenced as `SHACL_SHAPES_FILE` in config.
- SHACL validation runs against a local rdflib graph (not Jena) before insertion. Post-insertion verification queries Jena directly.

### Environment Variables

Key variables (full list in `src/config.py`):

| Variable | Purpose |
|---|---|
| `KB_INGESTION_QUEUE_URL` | SQS queue to poll |
| `S3_BUCKET_NAME` | Bucket containing chunked tender documents |
| `JENA_ENDPOINT` | Fuseki base URL (default: `http://fuseki:3030`) |
| `JENA_DATASET` | Dataset name (default: `tenders`) |
| `OPENROUTER_API_KEY` | API key for embeddings |
| `ONTOLOGY_DIR` | Path to OWL/SHACL files (default: `/app/ontology`) |
| `VALIDATION_STRICT` | If true, SHACL failures abort insertion |
| `NT_OUTPUT_DIR` | Directory for N-Triples export (default: `/tmp/nt_output`) |
