# 5_Ingestion Avis Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove obsolete avis metadata extraction and lot node creation from 5_Ingestion; replace with a single avis vectorization that stores the vector key as a data property on the existing tender node.

**Architecture:** Surgical removal of `AvisMetadata`, `LotMetadata`, `map_avis()`, `_map_lots()`, and `_process_avis()`. Replace with `map_avis_vector_key()` in the mapper and `_process_avis_vector()` in the orchestrator. The tender node and buyer/lot nodes are now fully owned by 1_Update/kg_builder; 5_Ingestion only enriches with document-derived nodes and the avis vector key.

**Tech Stack:** Python 3.11, rdflib, pyshacl, pydantic v2, boto3, pytest

---

## File Map

| File | Action |
|---|---|
| `src/models.py` | Remove `AvisMetadata`, `LotMetadata`; update `ChunkItem` union |
| `src/json_to_rdf.py` | Remove `map_avis`, `_map_lots`; add `map_avis_vector_key` |
| `main.py` | Remove `_process_avis`; add `_process_avis_vector` |
| `ontology/tender_structure_final.owl` | Add `ts:Has_Avis_Vector_Key` DatatypeProperty |
| `tests/test_json_to_rdf.py` | Remove avis/lot tests; add `test_map_avis_vector_key` |

---

### Task 1: Update tests — replace avis/lot tests with vector key test

**Files:**
- Modify: `tests/test_json_to_rdf.py`

- [ ] **Step 1: Remove obsolete test functions and imports**

Replace the top of `tests/test_json_to_rdf.py` (lines 1–68) with:

```python
import pytest
from rdflib import RDF, XSD, Literal
from src.json_to_rdf import JsonToRdfMapper
from src.models import ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from src.uri_builder import TS, get_spec_chunk_uri, get_admin_chunk_uri
```

Remove the two functions `test_map_avis_basic` (lines 8–40) and `test_map_avis_multilot` (lines 43–68) entirely.

- [ ] **Step 2: Add the new failing test**

Append to `tests/test_json_to_rdf.py`:

```python
def test_map_avis_vector_key():
    """map_avis_vector_key() writes ts:Has_Avis_Vector_Key on the tender node."""
    mapper = JsonToRdfMapper("AO_TEST_AVIS_VEC")
    vector_key = "index/tender-index/AO_TEST_AVIS_VEC/avis_chunk_0_vector.json"

    mapper.map_avis_vector_key(vector_key)
    g = mapper.graph

    assert (
        mapper.tender_uri,
        TS.Has_Avis_Vector_Key,
        Literal(vector_key, datatype=XSD.string),
    ) in g
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
pytest tests/test_json_to_rdf.py::test_map_avis_vector_key -v
```

Expected: `FAILED` — `AttributeError: 'JsonToRdfMapper' object has no attribute 'map_avis_vector_key'`

---

### Task 2: Update `src/models.py` — remove AvisMetadata and LotMetadata

**Files:**
- Modify: `src/models.py`

- [ ] **Step 1: Remove AvisMetadata class (lines 5–39)**

Delete the entire `AvisMetadata` class block including its `@field_validator`.

- [ ] **Step 2: Remove LotMetadata class (lines 42–69)**

Delete the entire `LotMetadata` class block including its `@field_validator`.

- [ ] **Step 3: Update ChunkItem metadata union (line 138)**

Change:
```python
    metadata: Union[
        AvisMetadata,
        SpecificationMetadata,
        AdministrativeMetadata,
        ProductChunkMetadata,
        dict
    ] = Field(None, description="Structured metadata for the specific section.")
```

To:
```python
    metadata: Union[
        SpecificationMetadata,
        AdministrativeMetadata,
        ProductChunkMetadata,
        dict
    ] = Field(None, description="Structured metadata for the specific section.")
```

- [ ] **Step 4: Update the imports line at the top of models.py**

Change:
```python
from typing import List, Optional, Union, Any, Literal, Dict
```

To:
```python
from typing import List, Optional, Union, Any, Literal
```

(Remove `Dict` — no longer needed after LotMetadata removal.)

- [ ] **Step 5: Run existing passing tests to confirm no regressions**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
pytest tests/test_json_to_rdf.py -v -k "not test_map_avis_vector_key"
```

Expected: all remaining tests PASS (`test_map_products`, `test_map_specification_chunk_as_node`, `test_map_administrative_chunk_as_node`, `test_extract_nested_products`)

---

### Task 3: Update `src/json_to_rdf.py` — remove map_avis/_map_lots, add map_avis_vector_key

**Files:**
- Modify: `src/json_to_rdf.py`

- [ ] **Step 1: Update imports at line 22**

Change:
```python
from .models import AvisMetadata, LotMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from .uri_builder import (
    get_tender_uri, get_bordereau_uri,
    get_article_uri, get_specification_uri, get_reglement_uri,
    get_lot_uri, get_spec_chunk_uri, get_admin_chunk_uri,
    TS
)
```

To:
```python
from .models import ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from .uri_builder import (
    get_tender_uri, get_bordereau_uri,
    get_article_uri, get_specification_uri, get_reglement_uri,
    get_spec_chunk_uri, get_admin_chunk_uri,
    TS
)
```

- [ ] **Step 2: Remove map_avis method (lines 52–120)**

Delete the entire `map_avis` method block including its docstring.

- [ ] **Step 3: Remove _map_lots method (lines 126–167)**

Delete the entire `_map_lots` method block including its docstring.

- [ ] **Step 4: Add map_avis_vector_key method**

Add after the `__init__` method (before the product mapping section):

```python
    # ------------------------------------------------------------------ #
    # Avis vector key                                                      #
    # ------------------------------------------------------------------ #

    def map_avis_vector_key(self, vector_key: str):
        """Write the avis embedding vector S3 key onto the existing tender node."""
        self.graph.add((self.tender_uri, TS.Has_Avis_Vector_Key, Literal(vector_key, datatype=XSD.string)))
```

- [ ] **Step 5: Run the new test — it should now pass**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
pytest tests/test_json_to_rdf.py::test_map_avis_vector_key -v
```

Expected: `PASSED`

- [ ] **Step 6: Run all json_to_rdf tests**

```bash
pytest tests/test_json_to_rdf.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/models.py src/json_to_rdf.py tests/test_json_to_rdf.py
git commit -m "refactor: remove AvisMetadata/LotMetadata, replace map_avis with map_avis_vector_key"
```

---

### Task 4: Update `main.py` — replace _process_avis with _process_avis_vector

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update imports at line 9**

Change:
```python
from src.models import ChunkingOutput, AvisMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata
```

To:
```python
from src.models import ChunkingOutput, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata
```

- [ ] **Step 2: Replace _process_avis method (lines 145–154) with _process_avis_vector**

Remove:
```python
    def _process_avis(self, key: str, mapper: JsonToRdfMapper):
        """Download avis JSON and map to RDF."""
        data = self._get_s3_json(key)
        for chunk in data.get('chunks', []):
            meta = chunk.get('metadata', {})
            if isinstance(meta, dict) and meta.get('type') == 'avis':
                try:
                    mapper.map_avis(AvisMetadata(**meta))
                except Exception as e:
                    logger.warning(f"Failed to parse avis metadata: {e}")
```

Add in its place:
```python
    async def _process_avis_vector(self, key: str, mapper: JsonToRdfMapper):
        """Download avis JSON, embed all content as a single vector, save to S3,
        and write the vector key as ts:Has_Avis_Vector_Key on the tender node."""
        data = self._get_s3_json(key)
        text = " ".join(c.get('content', '') for c in data.get('chunks', []))
        if not text.strip():
            logger.warning(f"Avis key {key} has no text content — skipping vectorization.")
            return
        embeddings = await self.embedder.async_batch_get_embeddings([text])
        if not embeddings or embeddings[0] is None:
            logger.warning(f"Embedding failed for avis {key} — skipping vector key.")
            return
        vector_key = await self.vector_store.async_save_vector(
            tender_ref=mapper.tender_ref,
            doc_type='avis',
            chunk_index=0,
            h3_header=None,
            vector=embeddings[0],
        )
        if vector_key:
            mapper.map_avis_vector_key(vector_key)
```

- [ ] **Step 3: Update process_message to call the new async method (lines 75–78)**

Change:
```python
            # -- Avis --
            avis_key = body.get('avis_key') or self._guess_key(folder, 'avis')
            if avis_key:
                self._process_avis(avis_key, mapper)
```

To:
```python
            # -- Avis --
            avis_key = body.get('avis_key') or self._guess_key(folder, 'avis')
            if avis_key:
                await self._process_avis_vector(avis_key, mapper)
```

- [ ] **Step 4: Run full test suite**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "refactor: replace _process_avis with async _process_avis_vector in KBIngestor"
```

---

### Task 5: Update OWL ontology — add ts:Has_Avis_Vector_Key

**Files:**
- Modify: `ontology/tender_structure_final.owl`

- [ ] **Step 1: Find insertion point**

Search for the block containing `ts:Has_Vector_Key` in `ontology/tender_structure_final.owl` to find where similar data properties are declared. Add the new property adjacent to it.

- [ ] **Step 2: Add DatatypeProperty declaration**

Insert the following XML block inside the `<!-- Object Properties -->` or `<!-- Data Properties -->` section of the OWL file, after the `ts:Has_Vector_Key` property declaration:

```xml
    <!-- http://www.tenderintelligence.io/ontology/tender-structure#Has_Avis_Vector_Key -->

    <owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Avis_Vector_Key">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
        <skos:prefLabel xml:lang="fr">Clé vecteur de l'avis</skos:prefLabel>
        <skos:definition xml:lang="fr">Clé S3 du vecteur d'embedding de l'avis d'appel d'offres.</skos:definition>
    </owl:DatatypeProperty>
```

- [ ] **Step 3: Verify the OWL file parses cleanly**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
python -c "
from rdflib import Graph
g = Graph()
g.parse('ontology/tender_structure_final.owl', format='xml')
print(f'OWL loaded: {len(g)} triples')
from src.uri_builder import TS
props = [str(p) for p in g.subjects() if 'Has_Avis_Vector_Key' in str(p)]
print('Has_Avis_Vector_Key found:', props)
"
```

Expected output contains: `Has_Avis_Vector_Key found: ['http://www.tenderintelligence.io/ontology/tender-structure#Has_Avis_Vector_Key']`

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 5: Verify no stale AvisMetadata references remain**

```bash
grep -r "AvisMetadata\|LotMetadata\|map_avis\|_process_avis\b" \
  src/ main.py tests/ \
  --include="*.py"
```

Expected: no output (zero matches)

- [ ] **Step 6: Final commit**

```bash
git add ontology/tender_structure_final.owl
git commit -m "feat: add ts:Has_Avis_Vector_Key DatatypeProperty to OWL ontology"
```
