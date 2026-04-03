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
