# Marker OCR + Classification Merge Design

**Date:** 2026-04-11
**Status:** Draft
**Author:** Brainstorming session

## Overview

Merge the OCR container (2_Ocr) and Classification container (3_Classification) into a single GPU container (2_Marker) using [VikParuchuri/marker](https://github.com/VikParuchuri/marker) as the core processing engine. Rename 4_Extraction to 4_Embedding, stripping it down to embedding-only. This reduces the pipeline from 4 processing containers to 3, eliminates 2 SQS queues, and produces cleaner structured JSON output with layout-aware document classification.

## Motivation

- **Docling → Marker:** Marker provides superior layout detection, section hierarchy, and reading order — information the classifier currently has to reconstruct from raw markdown lines.
- **Eliminate inter-container overhead:** OCR → Classification handoff via SQS + S3 adds latency and complexity. Merging removes it.
- **Structured JSON output:** Marker's native JSON renderer preserves block types, spatial coordinates (polygons/bboxes), and section hierarchy. Classification and chunking can leverage this rich structure directly.
- **Cleaner document identification:** Marker's `SectionHeader` blocks with hierarchy levels give the classifier precise section boundaries instead of guessing from markdown formatting.

## Architecture

### Container Topology

```
BEFORE (4 containers):
  2_Ocr (GPU) → 3_Classification (CPU) → 4_Extraction (CPU) → 5_Ingestion

AFTER (3 containers):
  2_Marker (GPU) → 4_Embedding (CPU) → 5_Ingestion
```

### Queue Topology

```
BEFORE: OCR_QUEUE → CLASSIFICATION_QUEUE → EXTRACTION_QUEUE → KB_INGESTION_QUEUE
AFTER:  OCR_QUEUE → EMBEDDING_QUEUE → KB_INGESTION_QUEUE
```

- `OCR_QUEUE` — unchanged (1_Update produces to it)
- `CLASSIFICATION_QUEUE` — deleted
- `EXTRACTION_QUEUE` — deleted
- `EMBEDDING_QUEUE` — new
- `KB_INGESTION_QUEUE` — unchanged

### Data Flow

```
1_Update posts to OCR_QUEUE
  → 2_Marker consumes message (tender_ref, s3_paths)
  → Downloads raw documents from S3 (tenders_doc_final/{tender_ref}/*)
  → Legacy format conversion (.doc/.xls via LibreOffice)
  → Marker PdfConverter: layout detection + OCR (GPU) + table extraction (CPU)
  → TenderClassifierProcessor: regex/keyword on SectionHeader blocks → 8 doc types
  → TenderChunkerProcessor: group blocks into chunks per doc type
  → Upload classified_chunks.json to S3 (chunks_tender/{tender_ref}/)
  → Post to EMBEDDING_QUEUE

  → 4_Embedding consumes message
  → Downloads classified_chunks.json
  → Embeds each chunk (sentence-transformers, CPU)
  → Uploads embedded_chunks.json to S3 (embedded_tender/{tender_ref}/)
  → Post to KB_INGESTION_QUEUE

  → 5_Ingestion consumes message
  → Reads embedded_chunks.json
  → Ingests into knowledge base
```

## Component Design

### 2_Marker: TenderPdfConverter

Subclass of Marker's `PdfConverter`. Appends two custom processors after Marker's ~27 default processors:

```python
class TenderPdfConverter(PdfConverter):
    default_processors = (
        # ... Marker's built-in processors (unchanged) ...
        "TenderClassifierProcessor",
        "TenderChunkerProcessor",
    )
```

Renderer: `JSONRenderer` (Marker built-in).

#### vRAM Budget (6GB total)

| Component | Device | Estimated vRAM |
|---|---|---|
| Layout detection model (float16) | GPU | ~1.5GB |
| Surya OCR model (float16) | GPU | ~2.5GB |
| PyTorch overhead | GPU | ~0.5GB |
| **Total** | | **~4.5GB** |
| **Headroom** | | **~1.5GB** |

Configuration (illustrative — exact Marker config keys to be verified during implementation):
- Layout detection: GPU
- Surya OCR: GPU
- Table structure recognition: CPU
- Torch dtype: float16

#### Input Handling

Supported formats (same as current): `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.jpeg`, `.jpg`, `.png`

Marker natively handles PDF, DOCX, PPTX, XLSX, images. Legacy `.doc` and `.xls` files are pre-converted to `.docx`/`.xlsx` via LibreOffice before passing to Marker (same approach as current Docling pipeline).

### TenderClassifierProcessor

Custom Marker processor that walks the block tree and assigns document types to sections.

**2-pass classification, no LLM:**

**Pass 1 — Anchor matching on SectionHeaders:**

Scan all `SectionHeader` blocks for high-confidence regex patterns. When matched, all blocks from that header until the next anchor (or page boundary) are tagged with the document type.

| Pattern Example | Document Type |
|---|---|
| `avis d'appel d'offres` | `avis_fr` |
| `إعلان عن طلب عروض` | `avis_ar` |
| `cahier des prescriptions spéciales` | `specification` |
| `règlement de la consultation` | `administrative` |
| `bordereau des prix` / `détail estimatif` | `product` |
| `acte d'engagement` | `acte_engagement` |
| `déclaration sur l'honneur` | `declaration` |
| `annexe` | `annexe` |

These are the ~80 proven regex patterns migrated from `3_Classification/src/classifier.py`.

**Pass 2 — Vocabulary density fallback:**

For sections not matched by Pass 1, count domain-specific keywords in `Text` blocks. Assign the type with highest keyword density above a confidence threshold. Unclassified blocks get `tender_doc_type: "unknown"` with `needs_review: true`.

**Block metadata added:**
- `tender_doc_type`: one of 8 types or `unknown`
- `classification_confidence`: `high` (anchor) or `medium` (vocabulary)

### TenderChunkerProcessor

Groups classified blocks into semantically meaningful chunks.

**Chunking strategy per document type:**

| Document Type | Strategy | Rationale |
|---|---|---|
| `avis_fr`, `avis_ar` | Per-article (split at SectionHeader) | Numbered articles are self-contained |
| `specification` | Per-article (split at SectionHeader) | CPS follows strict article structure |
| `administrative` | Per-article (split at SectionHeader) | RC follows article numbering |
| `product` | Per-table (Table block + surrounding context) | Pricing tables are primary content |
| `acte_engagement`, `declaration` | Whole-document (single chunk) | Short documents |
| `annexe` | Per-page (split at PageGroup) | Heterogeneous content |
| `unknown` | Per-page | Conservative default |

### Output JSON Schema

```json
{
  "tender_ref": "04_BM_2026",
  "processed_at": "2026-04-11T14:30:00Z",
  "marker_version": "1.x.x",
  "document_types_found": ["avis_fr", "specification", "product", "administrative"],
  "document_types_missing": ["avis_ar", "acte_engagement", "declaration", "annexe"],
  "chunks": [
    {
      "chunk_id": "avis_fr_001",
      "doc_type": "avis_fr",
      "classification_confidence": "high",
      "title": "Article 1: Objet de l'appel d'offres",
      "content": "Le présent appel d'offres...",
      "content_html": "<p>Le présent appel d'offres...</p>",
      "page_range": [0, 1],
      "bbox": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
      "block_types_contained": ["SectionHeader", "Text", "ListItem"],
      "word_count": 342
    }
  ],
  "anomalies": [
    {"type": "missing_doc_type", "doc_type": "avis_ar", "severity": "warning"}
  ]
}
```

**S3 output path:** `chunks_tender/{tender_ref}/classified_chunks.json`

### 4_Embedding (renamed from 4_Extraction)

Lightweight CPU container. All chunking and classification logic removed.

**Embedding model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 384-dimensional vectors
- ~120MB model size
- French + Arabic support
- ~50ms per chunk on CPU

**Processing flow:**
1. Consume from `EMBEDDING_QUEUE`
2. Download `classified_chunks.json` from S3
3. Embed each `chunk.content` → 384-dim vector
4. Add `"embedding"` field to each chunk
5. Upload to S3: `embedded_tender/{tender_ref}/embedded_chunks.json`
6. Post to `KB_INGESTION_QUEUE`

**Dependencies:** `sentence-transformers`, `boto3`, `python-dotenv` — no OpenRouter, no langchain, no sqlalchemy.

### 5_Ingestion (minor update)

Currently reads 4 separate JSON files (`avis.json`, `specification.json`, `administrative.json`, `product.json`). Updated to read a single `embedded_chunks.json`, iterating over the `chunks` array and using `doc_type` field for any type-specific ingestion logic.

## Docker Infrastructure

### Dockerfile: 2_Marker

```dockerfile
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Python 3.11, LibreOffice (legacy .doc/.xls), poppler-utils
# pip install marker-pdf[full] torch torchvision --index-url cu121
# Pre-cache Marker layout + OCR models at build time
# No Docling, no RapidOCR, no ModelScope
```

### Dockerfile: 4_Embedding

```dockerfile
FROM python:3.11-slim

# pip install sentence-transformers boto3 python-dotenv
# Pre-cache embedding model at build time
# No GPU, no OpenRouter, no langchain
```

### docker-compose.verify.yml

```yaml
services:
  marker:
    build: ./2_Marker
    runtime: nvidia
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - TORCH_DTYPE=float16
      - MARKER_TABLE_GPU=false
    volumes:
      - ./pipeline.db:/app/pipeline.db
      - ./Logs/2_Marker:/app/logs
    env_file:
      - 2_Marker/.env

  embedding:
    build: ./4_Embedding
    volumes:
      - ./pipeline.db:/app/pipeline.db
      - ./Logs/4_Embedding:/app/logs
    env_file:
      - 4_Embedding/.env

  ingestion:
    # Minor update: reads embedded_chunks.json
    depends_on:
      - embedding
    # ... rest unchanged
```

### Monitor Integration

Stage name `marker` replaces both `ocr` and `classification` in pipeline.db events.

Event types emitted by 2_Marker:
- `enter` — tender processing started
- `classification_complete` — intermediate checkpoint (classification done, chunking starting)
- `complete` — full processing done, JSON uploaded to S3
- `failed` — error with details

Stage name `embedding` replaces `extraction` in pipeline.db events.

## Migration

### Deleted

- `2_Ocr/` — entire directory
- `3_Classification/` — entire directory
- `4_Extraction/` — gutted (chunking logic, OpenRouter, langchain removed)
- SQS queues: `CLASSIFICATION_QUEUE`, `EXTRACTION_QUEUE`

### Created

- `2_Marker/`
  - `Dockerfile`
  - `main.py` — SQS poll loop, S3 download/upload
  - `src/tender_converter.py` — TenderPdfConverter subclass
  - `src/tender_classifier_processor.py` — document-type classification
  - `src/tender_chunker_processor.py` — chunking logic
  - `src/patterns.py` — regex patterns migrated from 3_Classification
  - `requirements.txt`
  - `.env`
- `4_Embedding/`
  - `Dockerfile`
  - `main.py` — SQS poll → embed → upload
  - `src/embedder.py` — sentence-transformers wrapper
  - `requirements.txt`
  - `.env`
- SQS queue: `EMBEDDING_QUEUE`

### Modified

- `docker-compose.verify.yml` — new service topology
- `5_Ingestion/main.py` — read single `embedded_chunks.json` instead of 4 files
- `e2e_test.sh` — updated container names, queue references, log paths
- `monitor.py` / `reporter.py` — stage name updates

### Pattern Migration

The ~80 regex patterns in `3_Classification/src/classifier.py` and vocabulary keyword sets move to `2_Marker/src/patterns.py`. Same patterns, applied to Marker's `SectionHeader` block text instead of raw markdown lines. No rewrite needed.

### Rollback

Current containers and queues remain untouched until new pipeline passes e2e testing. Both pipelines can coexist on different queue names. Cut-over: point 1_Update at same OCR_QUEUE (no change), delete old queues.

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| Processing engine | Marker (subclassed PdfConverter) | Layout detection, section hierarchy, reading order built-in |
| Integration pattern | Subclassed converter with custom processors | First-class extension point in Marker's architecture |
| Classification method | Regex/keyword on block tree, no LLM | Fast, deterministic, proven patterns from existing classifier |
| Output format | Structured JSON with chunks + metadata | Richer than markdown, native Marker support |
| Extraction → Embedding | Strip chunking, keep embedding only | Chunking absorbed by Marker container |
| Embedding model | paraphrase-multilingual-MiniLM-L12-v2 | French + Arabic, 384-dim, CPU-friendly |
| vRAM strategy | GPU layout+OCR, CPU tables, float16 | ~4.5GB of 6GB used, safe headroom |
| Queue topology | OCR_QUEUE → EMBEDDING_QUEUE → KB_INGESTION_QUEUE | 2 queues removed, clean linear flow |
