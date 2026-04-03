# Pipeline Monitoring Design
**Date**: 2026-04-03
**Status**: Approved

## Overview

A continuous production monitoring system for the 5-stage tender pipeline. After each scraper run (1_Update batch), a batch report is printed to stdout summarising flow integrity, stage performance, data quality, and anomalies across all 5 stages.

---

## Architecture

```
tender_scrape/
├── monitor.py              ← shared event emitter (symlinked into each stage dir)
├── reporter.py             ← standalone reporter process (run alongside pipeline)
├── pipeline.db             ← SQLite event store (gitignored)
├── reports/                ← archived batch report text files (gitignored)
│
├── 1_Update/monitor.py     → symlink to ../monitor.py
├── 2_Ocr/monitor.py        → symlink to ../monitor.py
├── 3_Classification/monitor.py → symlink to ../monitor.py
├── 4_Extraction/monitor.py → symlink to ../monitor.py
└── 5_Ingestion/monitor.py  → symlink to ../monitor.py
```

**Batch boundary**: Defined by 1_Update. When the scraper finishes downloading, it calls `close_batch(batch_id, total_scraped)`. The reporter uses `total_scraped` as the expected count to detect when the batch has fully drained through all 5 stages.

**Reporter polling**: `reporter.py` polls `pipeline.db` every 10 seconds. A batch is considered complete when all `total_scraped` tender_refs have reached a terminal state (`complete` or `failed`) in the `ingestion` stage, or after a 2-hour timeout.

---

## SQLite Schema

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    tender_ref  TEXT,                    -- NULL for batch-level events
    stage       TEXT NOT NULL,           -- update|ocr|classification|extraction|ingestion
    event       TEXT NOT NULL,           -- batch_start|batch_end|enter|complete|failed|anomaly
    detail      TEXT                     -- JSON blob
);

CREATE TABLE tender_stage (
    batch_id     TEXT NOT NULL,
    tender_ref   TEXT NOT NULL,
    stage        TEXT NOT NULL,
    status       TEXT NOT NULL,          -- pending|running|complete|failed
    entered_at   TEXT,
    completed_at TEXT,
    detail       TEXT,                   -- JSON: metrics, anomaly flags
    PRIMARY KEY (batch_id, tender_ref, stage)
);
```

---

## `monitor.py` — Public API

```python
def open_batch(stage="update") -> str:
    """Generate batch_id (batch_YYYYMMDD_HHMMSS), write batch_start event. Returns batch_id."""

def close_batch(batch_id: str, total_scraped: int) -> None:
    """Write batch_end event with total_scraped count."""

def enter(batch_id: str, tender_ref: str, stage: str) -> None:
    """Mark tender as running in this stage."""

def complete(batch_id: str, tender_ref: str, stage: str, **metrics) -> None:
    """Mark tender as complete in this stage. metrics go into detail JSON."""

def failed(batch_id: str, tender_ref: str, stage: str, error: str, **metrics) -> None:
    """Mark tender as failed in this stage."""

def anomaly(batch_id: str, tender_ref: str, stage: str, flags: list[str]) -> None:
    """Append anomaly flags for this tender at this stage."""
```

`monitor.py` resolves `pipeline.db` at `Path(__file__).resolve().parent.parent / "pipeline.db"` — works correctly whether called from a symlink in a stage dir or from the root.

---

## Events Per Stage

### 1_Update (`Db_updater.py`)

| Call | When | Key metrics |
|---|---|---|
| `open_batch()` | Scraper starts | — |
| `complete(tender_ref, stage="update")` | Tender scraped + downloaded | `scrape_time_s`, `docs_count` |
| `anomaly([f"download_failed:{tender_ref}"])` | Download fails | — |
| `failed(tender_ref, stage="update", error=...)` | Unrecoverable failure | `error` |
| `close_batch(batch_id, total_scraped)` | Scraper finishes | `total_scraped`, `new_refs`, `already_known`, `download_failed_count` |

### 2_Ocr (`main.py`)

| Call | When | Key metrics |
|---|---|---|
| `enter(tender_ref, stage="ocr")` | Message received | — |
| `complete(tender_ref, stage="ocr")` | Markdown uploaded to S3 | `processing_time_s`, `file_count`, `markdown_chars`, `file_types` (dict) |
| `anomaly(["empty_output"])` | Markdown is empty | — |
| `failed(tender_ref, stage="ocr", error=...)` | Processing exception | `error` |

### 3_Classification (`main.py`)

| Call | When | Key metrics |
|---|---|---|
| `enter(tender_ref, stage="classification")` | Message received | — |
| `complete(tender_ref, stage="classification")` | Message sent to extraction queue | `doc_count`, `classification_steps` (dict: `{1: N, 2: N, 3: N}`) |
| `anomaly([f"missing_doc_type:{t}", ...])` | Any expected doc type absent | One flag per missing type |
| `failed(tender_ref, stage="classification", error=...)` | Processing exception | `error` |

### 4_Extraction (`main.py`)

| Call | When | Key metrics |
|---|---|---|
| `enter(tender_ref, stage="extraction")` | Message received | — |
| `complete(tender_ref, stage="extraction")` | Chunks uploaded to S3 | `chunk_count`, `chunks_by_type` (dict: `{avis:N, spec:N, admin:N, product:N, form:N}`), `markdown_chars` |
| `anomaly(["zero_chunks"])` | No chunks generated | — |
| `anomaly(["zero_lots_in_avis"])` | Avis extracted but lots=0 | — |
| `failed(tender_ref, stage="extraction", error=...)` | Processing exception | `error` |

### 5_Ingestion (`main.py`)

| Call | When | Key metrics |
|---|---|---|
| `enter(tender_ref, stage="ingestion")` | Message received | — |
| `complete(tender_ref, stage="ingestion")` | Triples inserted + post-validation passed | `triple_count`, `lots_count`, `shacl_passed`, `post_validation_passed` |
| `anomaly(["shacl_failed"])` | SHACL validation fails | — |
| `anomaly(["post_validation_failed"])` | Post-insertion SPARQL check fails | — |
| `anomaly(["zero_triples"])` | N-Triples file is empty | — |
| `anomaly(["tender_not_in_jena"])` | Tender not found in KB pre-check | — |
| `failed(tender_ref, stage="ingestion", error=...)` | Processing exception | `error` |

---

## `reporter.py` — Report Format

Printed to stdout and written to `reports/{batch_id}.txt`:

```
╔══════════════════════════════════════════════════════════════╗
║  BATCH REPORT  batch_20260403_180000   2026-04-03 20:14:32  ║
╚══════════════════════════════════════════════════════════════╝

FLOW INTEGRITY
  Scraped        12  (2 download failed: TC4130186, AO_03_2026)
  OCR            10 ✓  /  2 ✗
  Classification  9 ✓  /  1 ✗
  Extraction      9 ✓  /  0 ✗
  Ingestion       8 ✓  /  1 ✗
  Drop-off:  12 → 10 → 9 → 9 → 8   (4 lost)

STAGE PERFORMANCE
  Update         total 4m 12s   avg 21s/tender   min 8s   max 67s
  OCR            avg 47s        min 12s          max 134s
  Classification avg  3s        min  1s          max   9s
  Extraction     avg 22s        min  8s          max  61s
  Ingestion      avg  5s        min  2s          max  12s

DATA QUALITY
  Update         new_refs: 10   already_known: 2   docs_per_tender avg: 3.2
                 download_failures: 2/12  (16%)
  OCR            avg markdown: 18 400 chars   empty outputs: 0
                 file_types: pdf=28  doc=4  img=2
  Classification step-1: 6   step-2: 2   step-3: 1  (LLM fallback)
  Extraction     chunks: avis=9 spec=7 admin=8 product=4 form=2
  Ingestion      total triples: 1 842   avg/tender: 230
                 SHACL passed: 8/9   post-validation: 8/9

ANOMALIES  (6)
  [1_Update]       download_failed: TC4130186_2026_ONEEBELEC
  [1_Update]       download_failed: AO_03_2026_LAAT
  [3_Classification] AO_05_2026: missing_doc_type:product
  [4_Extraction]   AO_07_2026: zero_chunks
  [5_Ingestion]    AO_08_2026: shacl_failed
  [5_Ingestion]    AO_09_2026: post_validation_failed

FAILED TENDERS
  TC4130186   failed at: update      reason: download_failed
  AO_07_2026  failed at: extraction  reason: zero_chunks
```

---

## Batch Completion Detection

Reporter queries:
1. Get `total_scraped` from the latest `batch_end` event for this `batch_id`
2. Count tender_refs in `tender_stage` where `stage='ingestion'` AND `status IN ('complete','failed')`
3. When count >= `total_scraped` → batch complete → print report

Timeout: if 2 hours elapse after `batch_end` and batch is still incomplete, reporter prints a partial report flagged as `[TIMEOUT - INCOMPLETE]`, listing tenders still in-flight per stage.

---

## Running

```bash
# Terminal 1 — start the reporter alongside the pipeline
python reporter.py

# reporter.py watches pipeline.db and prints a report after each batch completes
# also accepts --watch to tail in-progress batch state every 30s
```

`reporter.py --watch` prints a live progress line every 30 seconds while a batch is in flight:

```
[batch_20260403_180000] in-flight: update=0 ocr=3 classification=2 extraction=1 ingestion=0 | done=6/12
```

---

## Files Changed Per Stage

| File | Change |
|---|---|
| `monitor.py` | New file (root) |
| `reporter.py` | New file (root) |
| `1_Update/Db_updater.py` | Add `open_batch`, `close_batch`, `complete`/`anomaly`/`failed` calls |
| `2_Ocr/main.py` | Add `enter`, `complete`/`failed`/`anomaly` calls |
| `3_Classification/main.py` | Add `enter`, `complete`/`failed`/`anomaly` calls |
| `4_Extraction/main.py` | Add `enter`, `complete`/`failed`/`anomaly` calls |
| `5_Ingestion/main.py` | Add `enter`, `complete`/`failed`/`anomaly` calls |
| `1_Update/monitor.py` | Symlink → `../monitor.py` |
| `2_Ocr/monitor.py` | Symlink → `../monitor.py` |
| `3_Classification/monitor.py` | Symlink → `../monitor.py` |
| `4_Extraction/monitor.py` | Symlink → `../monitor.py` |
| `5_Ingestion/monitor.py` | Symlink → `../monitor.py` |
| `.gitignore` | Add `pipeline.db`, `reports/` |

---

## Non-Goals

- No network calls — fully local SQLite only
- No changes to existing log format in any stage
- No dashboards or web UI
- No alerting or notifications
