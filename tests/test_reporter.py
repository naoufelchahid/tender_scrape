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
    assert reporter.is_batch_complete(str(db_file), batch_id) is True


def test_is_batch_complete_false_when_in_flight(populated_db):
    db_file, batch_id = populated_db
    import reporter
    conn = sqlite3.connect(str(db_file))
    conn.execute("INSERT INTO tender_stage VALUES (?,?,?,?,?,?,?)",
                 (batch_id, "AO_05_2026", "ingestion", "running",
                  "2026-04-03T18:05:00Z", None, None))
    conn.execute("UPDATE events SET detail=? WHERE event='batch_end' AND batch_id=?",
                 (json.dumps({"total_scraped": 5, "new_refs": 4, "already_known": 1,
                              "download_failed_count": 0}), batch_id))
    conn.commit()
    conn.close()
    assert reporter.is_batch_complete(str(db_file), batch_id) is False
