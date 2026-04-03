# Design: 5_Ingestion Refactor — Align with 1_Update Workflow

**Date:** 2026-04-01  
**Status:** Approved

## Context

`1_Update/kg_builder.py` now creates the full `ts:Tenders` node and `ts:Buyer` node in Jena, including all metadata scraped from the site (object, deadline, category, location, mode_passation, qualifications, agrements, estimated_value, etc.). Lot data is also fully captured by 1_Update.

The `4_Extraction` container no longer extracts structured metadata from the avis document. The avis is now treated as raw text only.

Therefore `5_Ingestion` must stop re-writing avis metadata onto the tender node and stop creating Lot nodes. Its role is:
1. Vectorize the avis document as a single chunk → store vector key as a data property on the existing tender node
2. Add Bordereau + Articles (product chunks)
3. Add TenderSpecifications chunk nodes (specification chunks)
4. Add TenderReglement chunk nodes (administrative chunks)

## Data Flow

```
SQS message (tender_ref)
  → locate tender IRI in Jena
  → avis JSON        → concatenate text → embed (1 vector) → S3 → ts:Has_Avis_Vector_Key on tender node
  → product JSON     → Bordereau + Articles nodes
  → spec JSON        → TenderSpecifications chunk nodes + vectors
  → admin JSON       → TenderReglement chunk nodes + vectors
  → SHACL validation → SPARQL INSERT → post-ingestion quality gates
```

## Changes Per File

### `src/models.py`
- Remove `AvisMetadata` class (all fields now owned by 1_Update)
- Remove `LotMetadata` class (lots fully captured by 1_Update)
- Remove `AvisMetadata` and `LotMetadata` from `ChunkItem.metadata` union type

### `src/json_to_rdf.py`
- Remove `map_avis()` method
- Remove `_map_lots()` method
- Remove `AvisMetadata`, `LotMetadata` imports
- Add `map_avis_vector_key(vector_key: str)`:
  ```python
  def map_avis_vector_key(self, vector_key: str):
      self.graph.add((self.tender_uri, TS.Has_Avis_Vector_Key,
                      Literal(vector_key, datatype=XSD.string)))
  ```

### `main.py`
- Remove `_process_avis()` method
- Remove `AvisMetadata` import
- Add `async _process_avis_vector(key, mapper)`:
  - Download avis JSON from S3
  - Concatenate all chunk `content` fields into single text
  - Embed as single vector via `EmbeddingClient`
  - Save vector to S3 via `VectorStorage` (doc_type='avis', chunk_index=0)
  - Call `mapper.map_avis_vector_key(vector_key)`
- Update `process_message()`: replace `_process_avis(...)` call with `await _process_avis_vector(...)`

### `ontology/tender_structure_final.owl`
- Add `ts:Has_Avis_Vector_Key` as `owl:DatatypeProperty`:
  - domain: `ts:Tenders`
  - range: `xsd:string`

### `ontology/shapes_enrichment.ttl`
- No changes. No avis shapes existed; the vector key is optional and needs no SHACL constraint.

## What Is NOT Changed
- `map_specification()` and `map_administrative()` — unchanged
- `_process_products()` — unchanged
- `_process_doc_chunks()` — unchanged
- `DataTester` / SHACL validation logic — unchanged
- `JenaClient`, `EmbeddingClient`, `VectorStorage` — unchanged
- `uri_builder.py` — unchanged (no new URI pattern needed for avis vector key)

## Verification
1. Run `pytest tests/` — all existing tests must pass
2. Run `python test_pyshacl.py` — SHACL validation must pass with a graph containing only Bordereau/Articles/Spec/Admin nodes
3. Process a test tender locally: confirm `ts:Has_Avis_Vector_Key` triple is written to the graph
4. Confirm no `AvisMetadata` or `LotMetadata` references remain via `grep -r AvisMetadata 5_Ingestion/`
