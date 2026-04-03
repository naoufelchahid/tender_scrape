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
