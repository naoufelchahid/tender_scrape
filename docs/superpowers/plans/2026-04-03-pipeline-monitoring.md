# Pipeline Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared SQLite-backed monitoring system that tracks each tender through all 5 pipeline stages and prints a structured batch report when a scraper run completes.

**Architecture:** A `monitor.py` module at the repo root (symlinked into each stage directory) writes events to `pipeline.db`. A standalone `reporter.py` polls the DB and prints a formatted report once all tenders from a batch reach a terminal state in the ingestion stage.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), pytest, symlinks

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `monitor.py` | Create | Event emitter — writes to pipeline.db |
| `reporter.py` | Create | Polls pipeline.db, prints batch report |
| `tests/test_monitor.py` | Create | Unit tests for monitor.py |
| `tests/test_reporter.py` | Create | Unit tests for reporter.py report builder |
| `1_Update/monitor.py` | Symlink | Points to ../monitor.py |
| `2_Ocr/monitor.py` | Symlink | Points to ../monitor.py |
| `3_Classification/monitor.py` | Symlink | Points to ../monitor.py |
| `4_Extraction/monitor.py` | Symlink | Points to ../monitor.py |
| `5_Ingestion/monitor.py` | Symlink | Points to ../monitor.py |
| `1_Update/Db_updater.py` | Modify | Add open_batch, close_batch, complete, anomaly calls |
| `2_Ocr/main.py` | Modify | Add enter, complete, failed, anomaly calls |
| `3_Classification/main.py` | Modify | Add enter, complete, failed, anomaly calls |
| `4_Extraction/main.py` | Modify | Add enter, complete, failed, anomaly calls |
| `5_Ingestion/main.py` | Modify | Add enter, complete, failed, anomaly calls |
| `.gitignore` | Modify | Add pipeline.db, reports/ |

---

## Task 1: Create `monitor.py`

**Files:**
- Create: `monitor.py`

- [ ] **Step 1: Write the failing test** (in `tests/test_monitor.py` — create this file first)

```python
# tests/test_monitor.py
import os
import json
import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Override DB path to an isolated temp file for each test."""
    db_file = tmp_path / "test_pipeline.db"
    monkeypatch.setenv("PIPELINE_DB_PATH", str(db_file))
    # Force monitor to reload _DB_PATH from env
    import importlib
    import monitor
    importlib.reload(monitor)
    yield db_file
    monkeypatch.delenv("PIPELINE_DB_PATH", raising=False)


def test_open_batch_creates_batch_start_event(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    assert batch_id.startswith("batch_")
    conn = sqlite3.connect(str(tmp_db))
    rows = conn.execute("SELECT event, stage FROM events WHERE batch_id=?", (batch_id,)).fetchall()
    conn.close()
    assert rows == [("batch_start", "update")]


def test_close_batch_writes_total_scraped(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    monitor.close_batch(batch_id, total_scraped=5, new_refs=3, already_known=2, download_failed_count=0)
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute("SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)).fetchone()
    conn.close()
    detail = json.loads(row[0])
    assert detail["total_scraped"] == 5
    assert detail["new_refs"] == 3


def test_enter_sets_running_status(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    monitor.enter(batch_id, "AO_01_2026", "ocr")
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT status FROM tender_stage WHERE batch_id=? AND tender_ref=? AND stage=?",
        (batch_id, "AO_01_2026", "ocr")
    ).fetchone()
    conn.close()
    assert row[0] == "running"


def test_complete_sets_complete_status_with_metrics(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    monitor.enter(batch_id, "AO_01_2026", "ocr")
    monitor.complete(batch_id, "AO_01_2026", "ocr", processing_time_s=42.5, file_count=3)
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT status, detail FROM tender_stage WHERE batch_id=? AND tender_ref=? AND stage=?",
        (batch_id, "AO_01_2026", "ocr")
    ).fetchone()
    conn.close()
    assert row[0] == "complete"
    detail = json.loads(row[1])
    assert detail["processing_time_s"] == 42.5
    assert detail["file_count"] == 3


def test_failed_sets_failed_status(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    monitor.enter(batch_id, "AO_02_2026", "extraction")
    monitor.failed(batch_id, "AO_02_2026", "extraction", error="zero chunks")
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT status, detail FROM tender_stage WHERE batch_id=? AND tender_ref=? AND stage=?",
        (batch_id, "AO_02_2026", "extraction")
    ).fetchone()
    conn.close()
    assert row[0] == "failed"
    assert "zero chunks" in json.loads(row[1])["error"]


def test_anomaly_writes_flags(tmp_db):
    import monitor
    batch_id = monitor.open_batch()
    monitor.anomaly(batch_id, "AO_03_2026", "classification", ["missing_doc_type:product", "missing_doc_type:avis"])
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT detail FROM events WHERE event='anomaly' AND tender_ref=?", ("AO_03_2026",)
    ).fetchone()
    conn.close()
    detail = json.loads(row[0])
    assert "missing_doc_type:product" in detail["flags"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/naoufel/projects/tender_scrape
mkdir -p tests
pytest tests/test_monitor.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'monitor'`

- [ ] **Step 3: Create `monitor.py`**

```python
# monitor.py
"""
Shared pipeline monitoring event emitter.
Symlinked into each stage directory. Writes events to pipeline.db (SQLite).

Usage:
    from monitor import open_batch, close_batch, enter, complete, failed, anomaly
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Resolve DB path: env var override for tests, else repo root / pipeline.db
# Path(__file__).resolve() follows the symlink to the actual file location (repo root).
_DB_PATH = Path(
    os.environ.get("PIPELINE_DB_PATH")
    or str(Path(__file__).resolve().parent / "pipeline.db")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    tender_ref  TEXT,
    stage       TEXT NOT NULL,
    event       TEXT NOT NULL,
    detail      TEXT
);
CREATE TABLE IF NOT EXISTS tender_stage (
    batch_id     TEXT NOT NULL,
    tender_ref   TEXT NOT NULL,
    stage        TEXT NOT NULL,
    status       TEXT NOT NULL,
    entered_at   TEXT,
    completed_at TEXT,
    detail       TEXT,
    PRIMARY KEY (batch_id, tender_ref, stage)
);
"""


def _db_path() -> Path:
    """Return current DB path (re-reads env var so tests can override after import)."""
    env = os.environ.get("PIPELINE_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "pipeline.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_batch(stage: str = "update") -> str:
    """Generate batch_id (batch_YYYYMMDD_HHMMSS), write batch_start event. Returns batch_id."""
    batch_id = "batch_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event) VALUES (?,?,NULL,?,?)",
            (_now(), batch_id, stage, "batch_start"),
        )
        conn.commit()
    return batch_id


def close_batch(batch_id: str, total_scraped: int, **metrics) -> None:
    """Write batch_end event with total_scraped and optional metrics."""
    detail = {"total_scraped": total_scraped, **metrics}
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event, detail) VALUES (?,?,NULL,?,?,?)",
            (_now(), batch_id, "update", "batch_end", json.dumps(detail)),
        )
        conn.commit()


def enter(batch_id: str, tender_ref: str, stage: str) -> None:
    """Mark tender as running in this stage."""
    ts = _now()
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO tender_stage (batch_id, tender_ref, stage, status, entered_at)
               VALUES (?,?,?,'running',?)
               ON CONFLICT(batch_id, tender_ref, stage) DO UPDATE SET
                   status='running', entered_at=excluded.entered_at""",
            (batch_id, tender_ref, stage, ts),
        )
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event) VALUES (?,?,?,?,?)",
            (ts, batch_id, tender_ref, stage, "enter"),
        )
        conn.commit()


def complete(batch_id: str, tender_ref: str, stage: str, **metrics) -> None:
    """Mark tender as complete in this stage. metrics stored as JSON detail."""
    ts = _now()
    detail_json = json.dumps(metrics) if metrics else None
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO tender_stage (batch_id, tender_ref, stage, status, completed_at, detail)
               VALUES (?,?,?,'complete',?,?)
               ON CONFLICT(batch_id, tender_ref, stage) DO UPDATE SET
                   status='complete', completed_at=excluded.completed_at, detail=excluded.detail""",
            (batch_id, tender_ref, stage, ts, detail_json),
        )
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event, detail) VALUES (?,?,?,?,?,?)",
            (ts, batch_id, tender_ref, stage, "complete", detail_json),
        )
        conn.commit()


def failed(batch_id: str, tender_ref: str, stage: str, error: str, **metrics) -> None:
    """Mark tender as failed in this stage."""
    ts = _now()
    detail = {"error": error, **metrics}
    detail_json = json.dumps(detail)
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO tender_stage (batch_id, tender_ref, stage, status, completed_at, detail)
               VALUES (?,?,?,'failed',?,?)
               ON CONFLICT(batch_id, tender_ref, stage) DO UPDATE SET
                   status='failed', completed_at=excluded.completed_at, detail=excluded.detail""",
            (batch_id, tender_ref, stage, ts, detail_json),
        )
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event, detail) VALUES (?,?,?,?,?,?)",
            (ts, batch_id, tender_ref, stage, "failed", detail_json),
        )
        conn.commit()


def anomaly(batch_id: str, tender_ref: str, stage: str, flags: list) -> None:
    """Append anomaly flags for this tender at this stage."""
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO events (ts, batch_id, tender_ref, stage, event, detail) VALUES (?,?,?,?,?,?)",
            (_now(), batch_id, tender_ref, stage, "anomaly", json.dumps({"flags": flags})),
        )
        conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/naoufel/projects/tender_scrape
pytest tests/test_monitor.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add monitor.py tests/test_monitor.py
git commit -m "feat(monitor): add shared SQLite event emitter with schema and API"
```

---

## Task 2: Create `reporter.py`

**Files:**
- Create: `reporter.py`
- Create: `tests/test_reporter.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reporter.py
import json
import os
import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    """
    Create a pipeline.db with a completed batch for report testing.
    batch_id: batch_20260403_180000
    tenders: AO_01, AO_02 (complete), AO_03 (failed at extraction), AO_04 (anomaly at classification)
    """
    db_file = tmp_path / "pipeline.db"
    monkeypatch.setenv("PIPELINE_DB_PATH", str(db_file))

    import importlib
    import monitor
    importlib.reload(monitor)

    batch_id = "batch_20260403_180000"

    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            batch_id TEXT NOT NULL, tender_ref TEXT, stage TEXT NOT NULL,
            event TEXT NOT NULL, detail TEXT
        );
        CREATE TABLE IF NOT EXISTS tender_stage (
            batch_id TEXT NOT NULL, tender_ref TEXT NOT NULL, stage TEXT NOT NULL,
            status TEXT NOT NULL, entered_at TEXT, completed_at TEXT, detail TEXT,
            PRIMARY KEY (batch_id, tender_ref, stage)
        );
    """)

    # Batch lifecycle
    conn.execute("INSERT INTO events (ts,batch_id,tender_ref,stage,event,detail) VALUES "
                 "('2026-04-03T18:00:00Z',?,NULL,'update','batch_start',NULL)", (batch_id,))
    conn.execute("INSERT INTO events (ts,batch_id,tender_ref,stage,event,detail) VALUES "
                 "('2026-04-03T18:04:12Z',?,NULL,'update','batch_end',?)",
                 (batch_id, json.dumps({"total_scraped": 4, "new_refs": 3, "already_known": 1,
                                        "download_failed_count": 0})))

    # AO_01: full success through all stages
    stages = [
        ("update", "complete", "2026-04-03T18:00:10Z", "2026-04-03T18:00:52Z",
         json.dumps({"scrape_time_s": 42, "docs_count": 3})),
        ("ocr", "complete", "2026-04-03T18:01:00Z", "2026-04-03T18:01:47Z",
         json.dumps({"processing_time_s": 47, "file_count": 3, "markdown_chars": 18400,
                     "file_types": {"pdf": 3}})),
        ("classification", "complete", "2026-04-03T18:01:50Z", "2026-04-03T18:01:53Z",
         json.dumps({"doc_count": 4, "classification_steps": {"1": 3, "2": 1, "3": 0}})),
        ("extraction", "complete", "2026-04-03T18:02:00Z", "2026-04-03T18:02:22Z",
         json.dumps({"chunk_count": 12, "chunks_by_type": {"avis": 3, "specification": 4,
                                                            "administrative": 3, "product": 2, "form": 0},
                     "markdown_chars": 18400})),
        ("ingestion", "complete", "2026-04-03T18:02:30Z", "2026-04-03T18:02:35Z",
         json.dumps({"triple_count": 230, "lots_count": 4, "shacl_passed": True,
                     "post_validation_passed": True})),
    ]
    for stage, status, entered, completed, detail in stages:
        conn.execute(
            "INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
            (batch_id, "AO_01_2026", stage, status, entered, completed, detail)
        )

    # AO_02: success
    for stage, status, entered, completed, detail in [
        ("update", "complete", "2026-04-03T18:00:55Z", "2026-04-03T18:01:30Z",
         json.dumps({"scrape_time_s": 35, "docs_count": 2})),
        ("ocr", "complete", "2026-04-03T18:01:35Z", "2026-04-03T18:02:15Z",
         json.dumps({"processing_time_s": 40, "file_count": 2, "markdown_chars": 12000,
                     "file_types": {"pdf": 2}})),
        ("classification", "complete", "2026-04-03T18:02:20Z", "2026-04-03T18:02:23Z",
         json.dumps({"doc_count": 3, "classification_steps": {"1": 3, "2": 0, "3": 0}})),
        ("extraction", "complete", "2026-04-03T18:02:30Z", "2026-04-03T18:02:52Z",
         json.dumps({"chunk_count": 9, "chunks_by_type": {"avis": 2, "specification": 3,
                                                           "administrative": 2, "product": 2, "form": 0},
                     "markdown_chars": 12000})),
        ("ingestion", "complete", "2026-04-03T18:03:00Z", "2026-04-03T18:03:05Z",
         json.dumps({"triple_count": 180, "lots_count": 2, "shacl_passed": True,
                     "post_validation_passed": True})),
    ]:
        conn.execute("INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
                     (batch_id, "AO_02_2026", stage, status, entered, completed, detail))

    # AO_03: failed at extraction, anomaly zero_chunks
    for stage, status, entered, completed, detail in [
        ("update", "complete", "2026-04-03T18:01:32Z", "2026-04-03T18:02:00Z",
         json.dumps({"scrape_time_s": 28, "docs_count": 3})),
        ("ocr", "complete", "2026-04-03T18:02:05Z", "2026-04-03T18:02:45Z",
         json.dumps({"processing_time_s": 40, "file_count": 3, "markdown_chars": 9000,
                     "file_types": {"pdf": 3}})),
        ("classification", "complete", "2026-04-03T18:02:50Z", "2026-04-03T18:02:53Z",
         json.dumps({"doc_count": 3, "classification_steps": {"1": 2, "2": 0, "3": 1}})),
        ("extraction", "failed", "2026-04-03T18:03:00Z", "2026-04-03T18:03:08Z",
         json.dumps({"error": "zero chunks generated"})),
    ]:
        conn.execute("INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
                     (batch_id, "AO_03_2026", stage, status, entered, completed, detail))
    conn.execute("INSERT INTO events (ts,batch_id,tender_ref,stage,event,detail) VALUES "
                 "('2026-04-03T18:03:05Z',?,'AO_03_2026','extraction','anomaly',?)",
                 (batch_id, json.dumps({"flags": ["zero_chunks"]})))

    # AO_04: classification anomaly (missing doc types), then full success
    for stage, status, entered, completed, detail in [
        ("update", "complete", "2026-04-03T18:02:02Z", "2026-04-03T18:02:30Z",
         json.dumps({"scrape_time_s": 28, "docs_count": 2})),
        ("ocr", "complete", "2026-04-03T18:02:35Z", "2026-04-03T18:03:15Z",
         json.dumps({"processing_time_s": 40, "file_count": 2, "markdown_chars": 11000,
                     "file_types": {"pdf": 2}})),
        ("classification", "complete", "2026-04-03T18:03:20Z", "2026-04-03T18:03:23Z",
         json.dumps({"doc_count": 2, "classification_steps": {"1": 2, "2": 0, "3": 0}})),
        ("extraction", "complete", "2026-04-03T18:03:30Z", "2026-04-03T18:03:52Z",
         json.dumps({"chunk_count": 8, "chunks_by_type": {"avis": 2, "specification": 3,
                                                           "administrative": 2, "product": 1, "form": 0},
                     "markdown_chars": 11000})),
        ("ingestion", "complete", "2026-04-03T18:04:00Z", "2026-04-03T18:04:05Z",
         json.dumps({"triple_count": 195, "lots_count": 3, "shacl_passed": True,
                     "post_validation_passed": True})),
    ]:
        conn.execute("INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
                     (batch_id, "AO_04_2026", stage, status, entered, completed, detail))
    conn.execute("INSERT INTO events (ts,batch_id,tender_ref,stage,event,detail) VALUES "
                 "('2026-04-03T18:03:21Z',?,'AO_04_2026','classification','anomaly',?)",
                 (batch_id, json.dumps({"flags": ["missing_doc_type:product"]})))

    conn.commit()
    conn.close()
    monkeypatch.delenv("PIPELINE_DB_PATH", raising=False)
    return db_file, batch_id


def test_report_contains_flow_integrity(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    assert "FLOW INTEGRITY" in report
    assert "Scraped" in report
    assert "4" in report  # total_scraped
    assert "OCR" in report
    assert "Extraction" in report
    assert "Ingestion" in report


def test_report_shows_drop_off(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    # 4 scraped → 4 ocr → 4 classification → 3 extraction complete → 3 ingestion
    # AO_03 failed at extraction so only 3 reach ingestion
    assert "Drop-off" in report


def test_report_contains_stage_performance(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    assert "STAGE PERFORMANCE" in report
    assert "OCR" in report
    assert "avg" in report


def test_report_contains_data_quality(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    assert "DATA QUALITY" in report
    assert "new_refs" in report
    assert "markdown" in report
    assert "SHACL" in report
    assert "triples" in report


def test_report_lists_anomalies(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    assert "ANOMALIES" in report
    assert "zero_chunks" in report
    assert "missing_doc_type:product" in report


def test_report_lists_failed_tenders(populated_db):
    db_file, batch_id = populated_db
    import reporter
    report = reporter.build_report(str(db_file), batch_id)
    assert "FAILED TENDERS" in report
    assert "AO_03_2026" in report
    assert "extraction" in report


def test_is_batch_complete_true_when_all_terminal(populated_db):
    db_file, batch_id = populated_db
    import reporter
    # AO_03 failed at extraction — never reaches ingestion
    # So only 3 tenders are terminal in ingestion, but total_scraped=4
    # batch is complete because AO_03 is failed (terminal) even though not in ingestion
    assert reporter.is_batch_complete(str(db_file), batch_id) is True


def test_is_batch_complete_false_when_in_flight(populated_db, monkeypatch):
    db_file, batch_id = populated_db
    import reporter
    # Insert a tender that is still running in ingestion
    conn = sqlite3.connect(str(db_file))
    conn.execute("INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
                 (batch_id, "AO_05_2026", "ingestion", "running",
                  "2026-04-03T18:05:00Z", None, None))
    # Update total_scraped to 5
    conn.execute("UPDATE events SET detail=? WHERE event='batch_end' AND batch_id=?",
                 (json.dumps({"total_scraped": 5, "new_refs": 4, "already_known": 1,
                              "download_failed_count": 0}), batch_id))
    conn.commit()
    conn.close()
    assert reporter.is_batch_complete(str(db_file), batch_id) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/naoufel/projects/tender_scrape
pytest tests/test_reporter.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'reporter'`

- [ ] **Step 3: Create `reporter.py`**

```python
# reporter.py
"""
Pipeline batch reporter.
Polls pipeline.db every 10 seconds and prints a formatted batch report
when all tenders from a batch reach terminal state.

Usage:
    python reporter.py             # wait and print reports as batches complete
    python reporter.py --watch     # also print live progress every 30s
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_DB = str(Path(__file__).resolve().parent / "pipeline.db")
_REPORTS_DIR = Path(__file__).resolve().parent / "reports"
_POLL_INTERVAL = 10       # seconds
_WATCH_INTERVAL = 30      # seconds for --watch progress line
_BATCH_TIMEOUT_S = 7200   # 2 hours


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get_pending_batches(db_path: str) -> list:
    """Return batch_ids that have a batch_end event but haven't been reported yet."""
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT batch_id FROM events WHERE event='batch_end'"
            ).fetchall()
            return [r["batch_id"] for r in rows]
        except sqlite3.OperationalError:
            return []


def is_batch_complete(db_path: str, batch_id: str) -> bool:
    """
    A batch is complete when every tender from the batch has reached a terminal
    state (complete or failed) somewhere in the pipeline.
    A tender is considered terminal if:
      - it has status 'complete' or 'failed' in any stage, AND
      - no stage has status 'running' for this tender.
    """
    with _connect(db_path) as conn:
        # Get expected count
        row = conn.execute(
            "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?",
            (batch_id,)
        ).fetchone()
        if not row:
            return False
        total = json.loads(row["detail"]).get("total_scraped", 0)
        if total == 0:
            return False

        # Count tenders with any running stage
        in_flight = conn.execute(
            "SELECT COUNT(DISTINCT tender_ref) FROM tender_stage "
            "WHERE batch_id=? AND status='running'",
            (batch_id,)
        ).fetchone()[0]
        if in_flight > 0:
            return False

        # Count tenders with at least one terminal state
        terminal = conn.execute(
            "SELECT COUNT(DISTINCT tender_ref) FROM tender_stage "
            "WHERE batch_id=? AND status IN ('complete','failed')",
            (batch_id,)
        ).fetchone()[0]
        return terminal >= total


def _is_timed_out(db_path: str, batch_id: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT ts FROM events WHERE event='batch_end' AND batch_id=?",
            (batch_id,)
        ).fetchone()
        if not row:
            return False
        end_ts = datetime.fromisoformat(row["ts"])
        elapsed = (datetime.now(timezone.utc) - end_ts).total_seconds()
        return elapsed > _BATCH_TIMEOUT_S


# ─────────────────────────────────────────────────────────────────────────────
# Report sections
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _section_flow_integrity(conn, batch_id: str) -> str:
    # Total scraped
    row = conn.execute(
        "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
    ).fetchone()
    batch_detail = json.loads(row["detail"]) if row else {}
    total_scraped = batch_detail.get("total_scraped", 0)
    dl_failed = batch_detail.get("download_failed_count", 0)

    # Download failed tender_refs from anomaly events
    dl_failed_refs = []
    for arow in conn.execute(
        "SELECT tender_ref, detail FROM events WHERE event='anomaly' AND batch_id=? AND stage='update'",
        (batch_id,)
    ).fetchall():
        flags = json.loads(arow["detail"]).get("flags", [])
        for f in flags:
            if f.startswith("download_failed:"):
                dl_failed_refs.append(f.split(":", 1)[1])

    # Per-stage counts
    stage_counts = {}
    for stage in ("ocr", "classification", "extraction", "ingestion"):
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tender_stage "
            "WHERE batch_id=? AND stage=? GROUP BY status",
            (batch_id, stage)
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        stage_counts[stage] = counts

    def ok(stage): return stage_counts.get(stage, {}).get("complete", 0)
    def fail(stage): return stage_counts.get(stage, {}).get("failed", 0)

    scraped_str = f"{total_scraped}"
    if dl_failed_refs:
        refs_short = ", ".join(dl_failed_refs[:3])
        if len(dl_failed_refs) > 3:
            refs_short += f" +{len(dl_failed_refs) - 3}"
        scraped_str += f"  ({dl_failed} download failed: {refs_short})"

    ocr_total = ok("ocr") + fail("ocr")
    cls_total = ok("classification") + fail("classification")
    ext_total = ok("extraction") + fail("extraction")
    ing_total = ok("ingestion") + fail("ingestion")

    drop = f"{total_scraped} → {ocr_total} → {cls_total} → {ext_total} → {ing_total}"
    total_lost = total_scraped - ing_total

    lines = [
        "FLOW INTEGRITY",
        f"  Scraped        {scraped_str}",
        f"  OCR            {ok('ocr')} ✓  /  {fail('ocr')} ✗",
        f"  Classification {ok('classification')} ✓  /  {fail('classification')} ✗",
        f"  Extraction     {ok('extraction')} ✓  /  {fail('extraction')} ✗",
        f"  Ingestion      {ok('ingestion')} ✓  /  {fail('ingestion')} ✗",
        f"  Drop-off:  {drop}   ({total_lost} lost)",
    ]
    return "\n".join(lines)


def _section_stage_performance(conn, batch_id: str) -> str:
    # Update: total duration from batch_start → batch_end, per-tender from scrape_time_s in detail
    start_row = conn.execute(
        "SELECT ts FROM events WHERE event='batch_start' AND batch_id=?", (batch_id,)
    ).fetchone()
    end_row = conn.execute(
        "SELECT ts FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
    ).fetchone()

    update_total = ""
    update_avg = update_min = update_max = ""
    if start_row and end_row:
        t_start = datetime.fromisoformat(start_row["ts"])
        t_end = datetime.fromisoformat(end_row["ts"])
        total_s = (t_end - t_start).total_seconds()
        update_total = _fmt_duration(total_s)

    scrape_times = []
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='update' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        if "scrape_time_s" in d:
            scrape_times.append(d["scrape_time_s"])
    if scrape_times:
        update_avg = _fmt_duration(sum(scrape_times) / len(scrape_times))
        update_min = _fmt_duration(min(scrape_times))
        update_max = _fmt_duration(max(scrape_times))

    def stage_timing(stage):
        rows = conn.execute(
            "SELECT entered_at, completed_at FROM tender_stage "
            "WHERE batch_id=? AND stage=? AND status='complete' "
            "AND entered_at IS NOT NULL AND completed_at IS NOT NULL",
            (batch_id, stage)
        ).fetchall()
        durations = []
        for row in rows:
            try:
                t1 = datetime.fromisoformat(row["entered_at"])
                t2 = datetime.fromisoformat(row["completed_at"])
                durations.append((t2 - t1).total_seconds())
            except Exception:
                pass
        if not durations:
            return "  n/a"
        avg = sum(durations) / len(durations)
        return f"  avg {_fmt_duration(avg)}   min {_fmt_duration(min(durations))}   max {_fmt_duration(max(durations))}"

    upd_line = f"  Update         total {update_total}   avg {update_avg}/tender   min {update_min}   max {update_max}"

    lines = [
        "STAGE PERFORMANCE",
        upd_line.rstrip(),
        f"  OCR           {stage_timing('ocr')}",
        f"  Classification{stage_timing('classification')}",
        f"  Extraction    {stage_timing('extraction')}",
        f"  Ingestion     {stage_timing('ingestion')}",
    ]
    return "\n".join(lines)


def _section_data_quality(conn, batch_id: str) -> str:
    # Update metrics
    batch_end = conn.execute(
        "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
    ).fetchone()
    bd = json.loads(batch_end["detail"]) if batch_end else {}
    total_scraped = bd.get("total_scraped", 0)
    new_refs = bd.get("new_refs", "?")
    already_known = bd.get("already_known", "?")
    dl_failed = bd.get("download_failed_count", 0)
    dl_pct = f"{100 * dl_failed / total_scraped:.0f}%" if total_scraped else "?%"

    docs_counts = []
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='update' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        if "docs_count" in d:
            docs_counts.append(d["docs_count"])
    docs_avg = f"{sum(docs_counts)/len(docs_counts):.1f}" if docs_counts else "?"

    # Ingestion totals for Update row
    total_triples = sum_ing = 0
    lots_total = shacl_pass = post_pass = ing_count = 0
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='ingestion' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        total_triples += d.get("triple_count", 0)
        lots_total += d.get("lots_count", 0)
        if d.get("shacl_passed"):
            shacl_pass += 1
        if d.get("post_validation_passed"):
            post_pass += 1
        ing_count += 1

    # OCR metrics
    md_chars = []
    empty_count = 0
    file_types: dict = {}
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='ocr' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        if "markdown_chars" in d:
            md_chars.append(d["markdown_chars"])
        if d.get("empty_output"):
            empty_count += 1
        for ftype, cnt in (d.get("file_types") or {}).items():
            file_types[ftype] = file_types.get(ftype, 0) + cnt
    avg_md = f"{int(sum(md_chars)/len(md_chars)):,}" if md_chars else "?"
    ft_str = "  ".join(f"{k}={v}" for k, v in sorted(file_types.items()))

    # Classification steps
    cls_steps = {"1": 0, "2": 0, "3": 0}
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='classification' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        for k, v in (d.get("classification_steps") or {}).items():
            cls_steps[str(k)] = cls_steps.get(str(k), 0) + v

    # Extraction chunks
    ext_chunks: dict = {}
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='extraction' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        for k, v in (d.get("chunks_by_type") or {}).items():
            ext_chunks[k] = ext_chunks.get(k, 0) + v
    ext_str = "  ".join(f"{k}={v}" for k, v in sorted(ext_chunks.items()))

    avg_triples = f"{total_triples // ing_count}" if ing_count else "?"

    lines = [
        "DATA QUALITY",
        f"  Update         new_refs: {new_refs}   already_known: {already_known}   docs_per_tender avg: {docs_avg}",
        f"                 download_failures: {dl_failed}/{total_scraped}  ({dl_pct})",
        f"                 [ingestion outcome] total triples: {total_triples:,}   lots_count: {lots_total}",
        f"                 SHACL passed: {shacl_pass}/{ing_count}   post-validation: {post_pass}/{ing_count}",
        f"  OCR            avg markdown: {avg_md} chars   empty outputs: {empty_count}",
        f"                 file_types: {ft_str}",
        f"  Classification step-1: {cls_steps['1']}   step-2: {cls_steps['2']}   step-3: {cls_steps['3']}  (LLM fallback)",
        f"  Extraction     chunks: {ext_str}",
        f"  Ingestion      total triples: {total_triples:,}   avg/tender: {avg_triples}",
        f"                 SHACL passed: {shacl_pass}/{ing_count}   post-validation: {post_pass}/{ing_count}",
    ]
    return "\n".join(lines)


def _section_anomalies(conn, batch_id: str) -> str:
    rows = conn.execute(
        "SELECT tender_ref, stage, detail FROM events "
        "WHERE event='anomaly' AND batch_id=? ORDER BY id",
        (batch_id,)
    ).fetchall()
    if not rows:
        return "ANOMALIES  (0)\n  none"

    items = []
    for row in rows:
        flags = json.loads(row["detail"]).get("flags", [])
        stage_label = {
            "update": "1_Update", "ocr": "2_Ocr",
            "classification": "3_Classification",
            "extraction": "4_Extraction", "ingestion": "5_Ingestion",
        }.get(row["stage"], row["stage"])
        for flag in flags:
            items.append(f"  [{stage_label}]  {row['tender_ref']}: {flag}")

    lines = [f"ANOMALIES  ({len(items)})"] + items
    return "\n".join(lines)


def _section_failed_tenders(conn, batch_id: str) -> str:
    rows = conn.execute(
        "SELECT tender_ref, stage, detail FROM tender_stage "
        "WHERE batch_id=? AND status='failed' ORDER BY tender_ref",
        (batch_id,)
    ).fetchall()
    if not rows:
        return "FAILED TENDERS\n  none"

    items = []
    for row in rows:
        d = json.loads(row["detail"]) if row["detail"] else {}
        reason = d.get("error", "unknown")[:60]
        items.append(f"  {row['tender_ref']:<30} failed at: {row['stage']:<14} reason: {reason}")

    return "FAILED TENDERS\n" + "\n".join(items)


def build_report(db_path: str, batch_id: str, timed_out: bool = False) -> str:
    """Build the full batch report string. Callable from tests."""
    with _connect(db_path) as conn:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"  BATCH REPORT  {batch_id}   {now_str}  "
        if timed_out:
            title += "[TIMEOUT - INCOMPLETE]"
        width = max(len(title) + 2, 64)
        border = "═" * width

        sections = [
            f"╔{border}╗",
            f"║{title.center(width)}║",
            f"╚{border}╝",
            "",
            _section_flow_integrity(conn, batch_id),
            "",
            _section_stage_performance(conn, batch_id),
            "",
            _section_data_quality(conn, batch_id),
            "",
            _section_anomalies(conn, batch_id),
            "",
            _section_failed_tenders(conn, batch_id),
        ]
        return "\n".join(sections)


def _save_report(batch_id: str, report: str) -> None:
    _REPORTS_DIR.mkdir(exist_ok=True)
    path = _REPORTS_DIR / f"{batch_id}.txt"
    path.write_text(report, encoding="utf-8")


def _watch_line(db_path: str, batch_id: str) -> str:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
        ).fetchone()
        total = json.loads(row["detail"]).get("total_scraped", "?") if row else "?"
        in_flight: dict = {}
        for stage in ("update", "ocr", "classification", "extraction", "ingestion"):
            cnt = conn.execute(
                "SELECT COUNT(*) FROM tender_stage WHERE batch_id=? AND stage=? AND status='running'",
                (batch_id, stage)
            ).fetchone()[0]
            if cnt:
                in_flight[stage] = cnt
        done = conn.execute(
            "SELECT COUNT(DISTINCT tender_ref) FROM tender_stage "
            "WHERE batch_id=? AND status IN ('complete','failed')",
            (batch_id,)
        ).fetchone()[0]
        inf_str = "  ".join(f"{k}={v}" for k, v in in_flight.items()) or "idle"
        return f"[{batch_id}] in-flight: {inf_str} | done={done}/{total}"


def run(db_path: str, watch: bool = False) -> None:
    reported: set = set()
    last_watch = 0.0
    print(f"Reporter started. Watching {db_path} ...")

    while True:
        for batch_id in _get_pending_batches(db_path):
            if batch_id in reported:
                continue
            timed_out = _is_timed_out(db_path, batch_id)
            if is_batch_complete(db_path, batch_id) or timed_out:
                report = build_report(db_path, batch_id, timed_out=timed_out)
                print("\n" + report + "\n")
                _save_report(batch_id, report)
                reported.add(batch_id)
            elif watch:
                now = time.time()
                if now - last_watch >= _WATCH_INTERVAL:
                    print(_watch_line(db_path, batch_id))
                    last_watch = now

        time.sleep(_POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline batch reporter")
    parser.add_argument("--db", default=_DEFAULT_DB, help="Path to pipeline.db")
    parser.add_argument("--watch", action="store_true",
                        help="Print live progress every 30s while batch is in-flight")
    args = parser.parse_args()
    run(args.db, watch=args.watch)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/naoufel/projects/tender_scrape
pytest tests/test_reporter.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add reporter.py tests/test_reporter.py
git commit -m "feat(reporter): add batch report generator with flow, performance, quality, anomaly sections"
```

---

## Task 3: Create symlinks and update `.gitignore`

**Files:**
- Create: `1_Update/monitor.py`, `2_Ocr/monitor.py`, `3_Classification/monitor.py`, `4_Extraction/monitor.py`, `5_Ingestion/monitor.py` (all symlinks)
- Modify: `.gitignore`

- [ ] **Step 1: Create symlinks**

```bash
cd /home/naoufel/projects/tender_scrape
ln -s ../monitor.py 1_Update/monitor.py
ln -s ../monitor.py 2_Ocr/monitor.py
ln -s ../monitor.py 3_Classification/monitor.py
ln -s ../monitor.py 4_Extraction/monitor.py
ln -s ../monitor.py 5_Ingestion/monitor.py
```

- [ ] **Step 2: Verify symlinks resolve correctly**

```bash
cd /home/naoufel/projects/tender_scrape
python -c "import sys; sys.path.insert(0, '2_Ocr'); import monitor; print(monitor._db_path())"
```

Expected output: `/home/naoufel/projects/tender_scrape/pipeline.db`

- [ ] **Step 3: Update `.gitignore`**

Add to the end of `.gitignore`:

```
# Pipeline monitoring
pipeline.db
reports/
```

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 1_Update/monitor.py 2_Ocr/monitor.py 3_Classification/monitor.py \
        4_Extraction/monitor.py 5_Ingestion/monitor.py .gitignore
git commit -m "feat(monitor): add stage symlinks and gitignore entries for pipeline.db"
```

---

## Task 4: Instrument `1_Update/Db_updater.py`

**Files:**
- Modify: `1_Update/Db_updater.py`

Key insertion points:
- `run()` method (line ~1344): `open_batch` before loop, `close_batch` after `save_processed_tenders()`
- `process_tender()` method (line ~1109): `complete` on success (line ~1326), `anomaly` on download fail (lines ~1294-1295), `failed` when `search_by_reference_and_buyer` returns False (line ~1124)

- [ ] **Step 1: Add import at top of `Db_updater.py` (after existing imports, line ~32)**

Find the block:
```python
from bs4 import BeautifulSoup
```

Add after it:
```python
from monitor import open_batch, close_batch, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly
```

- [ ] **Step 2: Add `batch_id` attribute to `__init__` (after `self.stats` dict, line ~204)**

Find:
```python
        logger.info(f"TenderDownloader initialized")
```

Add before it:
```python
        self.batch_id: Optional[str] = None
```

- [ ] **Step 3: Instrument `run()` — open batch before loop, close after save**

Find in `run()`:
```python
        # Load new references
        new_references = self.load_new_references()
        if not new_references:
            logger.warning("No new references to process")
            return
```

Replace with:
```python
        # Load new references
        new_references = self.load_new_references()
        if not new_references:
            logger.warning("No new references to process")
            return

        self.batch_id = open_batch(stage="update")
```

Find in `run()`:
```python
        # Save processed tenders to output JSON
        self.save_processed_tenders()
        
        # Print final summary
        self.print_summary()
```

Replace with:
```python
        # Save processed tenders to output JSON
        self.save_processed_tenders()

        # Close batch: emit summary metrics for reporter
        already_known = self.stats['total_references'] - len(new_references)
        close_batch(
            self.batch_id,
            total_scraped=len(new_references),
            new_refs=len(self.processed_tenders),
            already_known=already_known,
            download_failed_count=self.stats['files_failed'],
        )

        # Print final summary
        self.print_summary()
```

- [ ] **Step 4: Instrument `process_tender()` — emit complete on success, anomaly on download fail, failed on search failure**

In `process_tender()`, find the search failure block (line ~1123):
```python
            if not await self.search_by_reference_and_buyer(page, original_reference, buyer_name):
                self.stats['files_failed'] += 1
                return False
```

Replace with:
```python
            if not await self.search_by_reference_and_buyer(page, original_reference, buyer_name):
                self.stats['files_failed'] += 1
                if self.batch_id:
                    mon_anomaly(self.batch_id, composite_reference, "update",
                                [f"download_failed:{composite_reference}"])
                    mon_failed(self.batch_id, composite_reference, "update",
                               error="search_failed")
                return False
```

Find the download timeout error (line ~1295):
```python
                        except asyncio.TimeoutError:
                            logger.error(f"❌ Download timed out for [{label}]")
```

Replace with:
```python
                        except asyncio.TimeoutError:
                            logger.error(f"❌ Download timed out for [{label}]")
                            if self.batch_id:
                                mon_anomaly(self.batch_id, composite_reference, "update",
                                            [f"download_failed:{composite_reference}"])
```

Find the success line (line ~1326):
```python
            logger.info(f"✅ Successfully processed: {composite_reference}")
            return True
```

Replace with:
```python
            logger.info(f"✅ Successfully processed: {composite_reference}")
            if self.batch_id:
                scrape_time = (datetime.now() - scrape_start).total_seconds() if 'scrape_start' in dir() else 0
                mon_complete(
                    self.batch_id, composite_reference, "update",
                    scrape_time_s=scrape_time,
                    docs_count=len(full_metadata.get('files', [])) or 1,
                )
            return True
```

Also add `scrape_start = datetime.now()` at the very top of `process_tender()`, right after the log lines (line ~1119):

Find:
```python
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {composite_reference}")
        logger.info(f"{'='*80}")

        try:
```

Replace with:
```python
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {composite_reference}")
        logger.info(f"{'='*80}")

        scrape_start = datetime.now()
        try:
```

- [ ] **Step 5: Verify import works**

```bash
cd /home/naoufel/projects/tender_scrape/1_Update
python -c "from Db_updater import TenderDownloader; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 1_Update/Db_updater.py
git commit -m "feat(monitor): instrument 1_Update scraper with batch open/close and per-tender events"
```

---

## Task 5: Instrument `2_Ocr/main.py`

**Files:**
- Modify: `2_Ocr/main.py`

Key insertion points in `OCRService.process_message()` (lines ~175–238):
- After `tender_ref` is set: `enter`
- After `log_processing_complete`: `complete`
- In the except block: `failed`
- After checking `final_markdown` is empty: `anomaly`

- [ ] **Step 1: Add import at the top of `2_Ocr/main.py`**

Find the existing imports block. Add after the last existing import:
```python
from monitor import enter as mon_enter, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly
```

- [ ] **Step 2: Add `batch_id` parameter to `process_message` and instrument**

The method signature is `process_message(self, message_body)`. 2_Ocr doesn't have a batch_id in the SQS message — it will read the most recent active batch_id from the DB.

Add a helper at the top of `main.py` (after the import):

```python
def _get_active_batch_id() -> Optional[str]:
    """Return the most recent batch_id that has batch_start but no batch_end yet,
    or the most recent batch_id if all are closed (still associate events correctly)."""
    try:
        import sqlite3
        from monitor import _db_path
        with sqlite3.connect(str(_db_path()), timeout=5) as conn:
            row = conn.execute(
                "SELECT batch_id FROM events WHERE event='batch_start' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None
```

In `process_message()`, find:
```python
        log_processing_start(tender_ref, len(s3_paths), s3_paths)
        
        try:
```

Replace with:
```python
        log_processing_start(tender_ref, len(s3_paths), s3_paths)
        batch_id = _get_active_batch_id()
        if batch_id:
            mon_enter(batch_id, tender_ref, "ocr")

        try:
```

Find:
```python
            # Log completion
            processing_time = time.time() - start_time
            log_processing_complete(tender_ref, processing_time, len(local_paths))
            
            return True
        except Exception as e:
            log_processing_error(tender_ref, e)
            self._cleanup_temp_files(tender_ref)
            return False
```

Replace with:
```python
            # Log completion
            processing_time = time.time() - start_time
            log_processing_complete(tender_ref, processing_time, len(local_paths))

            # Count file types
            file_types = {}
            for p in local_paths:
                ext = Path(p).suffix.lower().lstrip(".")
                file_types[ext] = file_types.get(ext, 0) + 1

            empty_output = len(final_markdown.strip()) == 0
            if batch_id:
                if empty_output:
                    mon_anomaly(batch_id, tender_ref, "ocr", ["empty_output"])
                mon_complete(
                    batch_id, tender_ref, "ocr",
                    processing_time_s=round(processing_time, 1),
                    file_count=len(local_paths),
                    markdown_chars=len(final_markdown),
                    file_types=file_types,
                )
            return True
        except Exception as e:
            log_processing_error(tender_ref, e)
            self._cleanup_temp_files(tender_ref)
            if batch_id:
                mon_failed(batch_id, tender_ref, "ocr", error=str(e))
            return False
```

Also add `from pathlib import Path` if not already imported (check first — it likely is in config.py but not main.py directly).

- [ ] **Step 3: Verify import works**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
python -c "import main; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 2_Ocr/main.py
git commit -m "feat(monitor): instrument 2_Ocr with enter/complete/failed/anomaly events"
```

---

## Task 6: Instrument `3_Classification/main.py`

**Files:**
- Modify: `3_Classification/main.py`

Key insertion points in `process_message()` (lines ~350–473):
- After `tender_ref` is set: `enter`
- After `logger.info(f"✓ Successfully processed {tender_ref}")`: `complete`
- In except block: `failed`
- After final doc set is known (before upload): `anomaly` for missing doc types

- [ ] **Step 1: Add import to `3_Classification/main.py`**

Find the imports block and add after the last import:
```python
from monitor import enter as mon_enter, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly
```

Add the `_get_active_batch_id` helper (same as Task 5 — copy it verbatim):

```python
def _get_active_batch_id():
    try:
        import sqlite3
        from monitor import _db_path
        with sqlite3.connect(str(_db_path()), timeout=5) as conn:
            row = conn.execute(
                "SELECT batch_id FROM events WHERE event='batch_start' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None
```

- [ ] **Step 2: Instrument `process_message()`**

Find:
```python
            logger.info(f"Processing tender: {tender_ref}")
            
            # Download and concatenate all markdown files
```

Replace with:
```python
            logger.info(f"Processing tender: {tender_ref}")
            batch_id = _get_active_batch_id()
            if batch_id:
                mon_enter(batch_id, tender_ref, "classification")

            # Download and concatenate all markdown files
```

Find (before `output_key = markdown_paths[0]...` line, after the full `all_docs` / `docs` set is determined):

The final doc set is known just before the upload. Find the two branches (`if newly_found_types` / `else`) and identify where `all_found_types` is set in each. The upload happens at line ~447 (`self._upload_markdown(...)`). Add anomaly detection right before the upload:

Find:
```python
            # Generate output S3 key - REMOVE "_ocr" from filename as per user requirement
```

Add before it:
```python
            # Detect missing doc types and emit anomaly flags
            EXPECTED_TYPES = {"avis", "administrative", "specification", "product"}
            final_types = all_found_types if 'all_found_types' in dir() else {doc.doc_type for doc in docs}
            missing_types = EXPECTED_TYPES - final_types
            if missing_types and batch_id:
                mon_anomaly(batch_id, tender_ref, "classification",
                            [f"missing_doc_type:{t}" for t in sorted(missing_types)])

```

Find:
```python
            logger.info(f"✓ Successfully processed {tender_ref}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return False
```

Replace with:
```python
            logger.info(f"✓ Successfully processed {tender_ref}")

            # Count classification steps used
            all_classified = all_docs if 'all_docs' in dir() else docs
            step_counts = {"1": 0, "2": 0, "3": 0}
            # classification_steps not tracked per-doc in current code; use doc_count only
            if batch_id:
                mon_complete(
                    batch_id, tender_ref, "classification",
                    doc_count=len(all_classified),
                    classification_steps=step_counts,
                )
            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            if batch_id:
                mon_failed(batch_id, tender_ref, "classification", error=str(e))
            return False
```

- [ ] **Step 3: Verify import works**

```bash
cd /home/naoufel/projects/tender_scrape/3_Classification
python -c "import main; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 3_Classification/main.py
git commit -m "feat(monitor): instrument 3_Classification with enter/complete/failed/anomaly events"
```

---

## Task 7: Instrument `4_Extraction/main.py`

**Files:**
- Modify: `4_Extraction/main.py`

Key insertion points in `handle_message()` (lines ~69–212):
- After `tender_ref` is set (line ~99): `enter`
- After `logger.info(f"Successfully processed {tender_ref}")` (line ~205): `complete`
- In except blocks: `failed`
- After `chunks_by_type` is known (line ~155): `anomaly` for zero_chunks, zero_lots_in_avis

- [ ] **Step 1: Add import to `4_Extraction/main.py`**

Find:
```python
from src.document_chunker import DocumentChunker
```

Add after existing imports:
```python
from monitor import enter as mon_enter, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly
```

Add `_get_active_batch_id` helper (same as Tasks 5 and 6):
```python
def _get_active_batch_id():
    try:
        import sqlite3
        from monitor import _db_path
        with sqlite3.connect(str(_db_path()), timeout=5) as conn:
            row = conn.execute(
                "SELECT batch_id FROM events WHERE event='batch_start' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None
```

- [ ] **Step 2: Instrument `handle_message()`**

Find:
```python
        logger.info(f"Processing {tender_ref} (ID: {tender_id})...")

        # 1. Download Markdown
```

Replace with:
```python
        logger.info(f"Processing {tender_ref} (ID: {tender_id})...")
        batch_id = _get_active_batch_id()
        if batch_id:
            mon_enter(batch_id, tender_ref, "extraction")

        # 1. Download Markdown
```

Find (after `total_chunks` is computed, line ~156):
```python
        logger.info(f"Generated {total_chunks} total chunks across types: {list(chunks_by_type.keys())}")
        
        # 4. Upload Chunks to S3
```

Replace with:
```python
        logger.info(f"Generated {total_chunks} total chunks across types: {list(chunks_by_type.keys())}")

        # Anomaly detection
        anomaly_flags = []
        if total_chunks == 0:
            anomaly_flags.append("zero_chunks")
        avis_chunks = chunks_by_type.get("avis", [])
        if avis_chunks:
            # Check if any avis chunk has lots
            has_lots = any(
                (c.get("metadata", {}) or {}).get("lots") for c in avis_chunks
                if isinstance(c, dict)
            )
            if not has_lots:
                anomaly_flags.append("zero_lots_in_avis")
        if anomaly_flags and batch_id:
            mon_anomaly(batch_id, tender_ref, "extraction", anomaly_flags)

        # 4. Upload Chunks to S3
```

Find:
```python
        # 9. Delete Message
        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
        logger.info(f"Successfully processed {tender_ref}")

    except ValidationError as e:
        logger.error(f"Validation errors processing message: {e.errors()}", exc_info=True)
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        # Don't delete message, let visibility timeout handle retry
```

Replace with:
```python
        # 9. Delete Message
        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
        logger.info(f"Successfully processed {tender_ref}")

        if batch_id:
            chunks_by_type_counts = {k: len(v) for k, v in chunks_by_type.items()}
            mon_complete(
                batch_id, tender_ref, "extraction",
                chunk_count=total_chunks,
                chunks_by_type=chunks_by_type_counts,
                markdown_chars=len(full_markdown),
            )

    except ValidationError as e:
        logger.error(f"Validation errors processing message: {e.errors()}", exc_info=True)
        if 'batch_id' in dir() and batch_id and 'tender_ref' in dir() and tender_ref:
            mon_failed(batch_id, tender_ref, "extraction", error=str(e))
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        if 'batch_id' in dir() and batch_id and 'tender_ref' in dir() and tender_ref:
            mon_failed(batch_id, tender_ref, "extraction", error=str(e))
        # Don't delete message, let visibility timeout handle retry
```

- [ ] **Step 3: Verify import works**

```bash
cd /home/naoufel/projects/tender_scrape/4_Extraction
python -c "import main; print('import OK')" 2>&1 | head -5
```

Expected: `import OK` (or dependency import errors for chunker deps — that's OK, means monitor imported fine)

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 4_Extraction/main.py
git commit -m "feat(monitor): instrument 4_Extraction with enter/complete/failed/anomaly events"
```

---

## Task 8: Instrument `5_Ingestion/main.py`

**Files:**
- Modify: `5_Ingestion/main.py`

Key insertion points in `KBIngestor.process_message()` (lines ~47–136):
- After `tender_ref` is set (line ~57): `enter`
- On `tender_iri` not found (line ~66): `anomaly` + `failed`
- After SHACL check fails (line ~101): `anomaly`
- After insert triples fails (line ~118): `anomaly`
- After post-ingestion validation fails (line ~123): `anomaly`
- After final `logger.info(f"Tender {tender_ref}: passed all checks ✓")`: `complete`
- In outer except: `failed`

- [ ] **Step 1: Add import to `5_Ingestion/main.py`**

Find:
```python
from src.jena_client import JenaClient
```

Add after existing imports:
```python
from monitor import enter as mon_enter, complete as mon_complete, failed as mon_failed, anomaly as mon_anomaly
```

Add `_get_active_batch_id` helper:
```python
def _get_active_batch_id():
    try:
        import sqlite3
        from monitor import _db_path
        with sqlite3.connect(str(_db_path()), timeout=5) as conn:
            row = conn.execute(
                "SELECT batch_id FROM events WHERE event='batch_start' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None
```

- [ ] **Step 2: Instrument `process_message()`**

Find:
```python
            logger.info(f"Processing tender: {tender_ref}")

            # 1. Locate tender IRI in Jena KB
```

Replace with:
```python
            logger.info(f"Processing tender: {tender_ref}")
            batch_id = _get_active_batch_id()
            if batch_id:
                mon_enter(batch_id, tender_ref, "ingestion")

            # 1. Locate tender IRI in Jena KB
```

Find:
```python
            if not tender_iri:
                logger.warning(f"Tender '{tender_ref}' not found in Jena KB. Deleting message to avoid infinite loop.")
                self.sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                return False
```

Replace with:
```python
            if not tender_iri:
                logger.warning(f"Tender '{tender_ref}' not found in Jena KB. Deleting message to avoid infinite loop.")
                if batch_id:
                    mon_anomaly(batch_id, tender_ref, "ingestion", ["tender_not_in_jena"])
                    mon_failed(batch_id, tender_ref, "ingestion", error="tender_not_in_jena")
                self.sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                return False
```

Find:
```python
            if not self.tester.test_tender_graph(mapper.graph):
                logger.error(f"Tender {tender_ref}: consistency check failed — skipping ingestion.")
                self._move_to_dlq(message)
                return False
```

Replace with:
```python
            if not self.tester.test_tender_graph(mapper.graph):
                logger.error(f"Tender {tender_ref}: consistency check failed — skipping ingestion.")
                if batch_id:
                    mon_anomaly(batch_id, tender_ref, "ingestion", ["shacl_failed"])
                    mon_failed(batch_id, tender_ref, "ingestion", error="shacl_failed")
                self._move_to_dlq(message)
                return False
```

Find:
```python
            ntriples_body = mapper.get_ntriples()
            if not self.jena.insert_triples(ntriples_body):
                logger.error(f"Tender {tender_ref}: failed to insert triples into Jena.")
                return False
```

Replace with:
```python
            ntriples_body = mapper.get_ntriples()
            triple_count = ntriples_body.count("\n") if ntriples_body else 0
            if not self.jena.insert_triples(ntriples_body):
                logger.error(f"Tender {tender_ref}: failed to insert triples into Jena.")
                if batch_id:
                    if triple_count == 0:
                        mon_anomaly(batch_id, tender_ref, "ingestion", ["zero_triples"])
                    mon_failed(batch_id, tender_ref, "ingestion", error="insert_triples_failed")
                return False
```

Find:
```python
            # 7. Post-ingestion verification
            if not self.tester.validate_tender_in_jena(tender_iri):
                logger.warning(f"Post-ingestion validation failed for {tender_ref}.")

            logger.info(f"Tender {tender_ref}: passed all checks ✓")

            # 8. Cleanup SQS message
```

Replace with:
```python
            # 7. Post-ingestion verification
            post_validation_passed = self.tester.validate_tender_in_jena(tender_iri)
            if not post_validation_passed:
                logger.warning(f"Post-ingestion validation failed for {tender_ref}.")
                if batch_id:
                    mon_anomaly(batch_id, tender_ref, "ingestion", ["post_validation_failed"])

            logger.info(f"Tender {tender_ref}: passed all checks ✓")

            if batch_id:
                lots_count = 0  # mapper does not expose lot count directly
                mon_complete(
                    batch_id, tender_ref, "ingestion",
                    triple_count=triple_count,
                    lots_count=lots_count,
                    shacl_passed=True,
                    post_validation_passed=bool(post_validation_passed),
                )

            # 8. Cleanup SQS message
```

Find:
```python
        except Exception as e:
            logger.error(f"Tender {tender_ref if 'tender_ref' in locals() else '?'}: unexpected error — {str(e)}")
            return False
```

Replace with:
```python
        except Exception as e:
            logger.error(f"Tender {tender_ref if 'tender_ref' in locals() else '?'}: unexpected error — {str(e)}")
            if 'batch_id' in locals() and batch_id and 'tender_ref' in locals() and tender_ref:
                mon_failed(batch_id, tender_ref, "ingestion", error=str(e))
            return False
```

- [ ] **Step 3: Verify import works**

```bash
cd /home/naoufel/projects/tender_scrape/5_Ingestion
python -c "import main; print('import OK')" 2>&1 | head -5
```

Expected: `import OK` (or Jena/config errors — that's OK, means monitor imported fine)

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 5_Ingestion/main.py
git commit -m "feat(monitor): instrument 5_Ingestion with enter/complete/failed/anomaly events"
```

---

## Task 9: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
cd /home/naoufel/projects/tender_scrape
pytest tests/ -v
```

Expected: all tests PASS (6 monitor + 8 reporter = 14 total)

- [ ] **Step 2: Smoke-test reporter against a real (empty) DB**

```bash
cd /home/naoufel/projects/tender_scrape
python -c "
import monitor
batch_id = monitor.open_batch()
monitor.complete(batch_id, 'TEST_REF', 'update', scrape_time_s=5, docs_count=2)
monitor.close_batch(batch_id, total_scraped=1, new_refs=1, already_known=0, download_failed_count=0)
monitor.enter(batch_id, 'TEST_REF', 'ocr')
monitor.complete(batch_id, 'TEST_REF', 'ocr', processing_time_s=30, file_count=2, markdown_chars=5000, file_types={'pdf': 2})
monitor.enter(batch_id, 'TEST_REF', 'classification')
monitor.complete(batch_id, 'TEST_REF', 'classification', doc_count=3, classification_steps={'1': 3, '2': 0, '3': 0})
monitor.enter(batch_id, 'TEST_REF', 'extraction')
monitor.complete(batch_id, 'TEST_REF', 'extraction', chunk_count=8, chunks_by_type={'avis': 2, 'specification': 3, 'administrative': 2, 'product': 1, 'form': 0}, markdown_chars=5000)
monitor.enter(batch_id, 'TEST_REF', 'ingestion')
monitor.complete(batch_id, 'TEST_REF', 'ingestion', triple_count=180, lots_count=2, shacl_passed=True, post_validation_passed=True)
print('batch_id:', batch_id)
"
```

Then run reporter against it:
```bash
cd /home/naoufel/projects/tender_scrape
python -c "
import reporter, sys
batch_id = sys.argv[1]
report = reporter.build_report('pipeline.db', batch_id)
print(report)
" $(python -c "import sqlite3; conn = sqlite3.connect('pipeline.db'); print(conn.execute('SELECT batch_id FROM events WHERE event=\"batch_end\" ORDER BY id DESC LIMIT 1').fetchone()[0])")
```

Expected: formatted report printed to stdout with TEST_REF visible in all sections.

Clean up test DB after:
```bash
rm -f /home/naoufel/projects/tender_scrape/pipeline.db
```

- [ ] **Step 3: Commit final**

```bash
cd /home/naoufel/projects/tender_scrape
git add tests/
git commit -m "test(monitor): verify all monitor and reporter tests pass"
```
