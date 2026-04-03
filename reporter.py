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
    """Return batch_ids that have a batch_end event."""
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
    state (complete or failed) somewhere in the pipeline, with no stage still running.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?",
            (batch_id,)
        ).fetchone()
        if not row:
            return False
        total = json.loads(row["detail"]).get("total_scraped", 0)
        if total == 0:
            return False

        in_flight = conn.execute(
            "SELECT COUNT(DISTINCT tender_ref) FROM tender_stage "
            "WHERE batch_id=? AND status='running'",
            (batch_id,)
        ).fetchone()[0]
        if in_flight > 0:
            return False

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
        if end_ts.tzinfo is None:
            end_ts = end_ts.replace(tzinfo=timezone.utc)
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
    row = conn.execute(
        "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
    ).fetchone()
    batch_detail = json.loads(row["detail"]) if row else {}
    total_scraped = batch_detail.get("total_scraped", 0)
    dl_failed = batch_detail.get("download_failed_count", 0)

    dl_failed_refs = []
    for arow in conn.execute(
        "SELECT tender_ref, detail FROM events WHERE event='anomaly' AND batch_id=? AND stage='update'",
        (batch_id,)
    ).fetchall():
        flags = json.loads(arow["detail"]).get("flags", [])
        for f in flags:
            if f.startswith("download_failed:"):
                dl_failed_refs.append(f.split(":", 1)[1])

    stage_counts = {}
    for stage in ("ocr", "classification", "extraction", "ingestion"):
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tender_stage "
            "WHERE batch_id=? AND stage=? GROUP BY status",
            (batch_id, stage)
        ).fetchall()
        stage_counts[stage] = {r["status"]: r["cnt"] for r in rows}

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
    total_lost = total_scraped - ing_total

    lines = [
        "FLOW INTEGRITY",
        f"  Scraped        {scraped_str}",
        f"  OCR            {ok('ocr')} ✓  /  {fail('ocr')} ✗",
        f"  Classification {ok('classification')} ✓  /  {fail('classification')} ✗",
        f"  Extraction     {ok('extraction')} ✓  /  {fail('extraction')} ✗",
        f"  Ingestion      {ok('ingestion')} ✓  /  {fail('ingestion')} ✗",
        f"  Drop-off:  {total_scraped} → {ocr_total} → {cls_total} → {ext_total} → {ing_total}   ({total_lost} lost)",
    ]
    return "\n".join(lines)


def _section_stage_performance(conn, batch_id: str) -> str:
    start_row = conn.execute(
        "SELECT ts FROM events WHERE event='batch_start' AND batch_id=?", (batch_id,)
    ).fetchone()
    end_row = conn.execute(
        "SELECT ts FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
    ).fetchone()

    update_total = update_avg = update_min = update_max = "n/a"
    if start_row and end_row:
        t_start = datetime.fromisoformat(start_row["ts"])
        t_end = datetime.fromisoformat(end_row["ts"])
        update_total = _fmt_duration((t_end - t_start).total_seconds())

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
            return "n/a"
        avg = sum(durations) / len(durations)
        return f"avg {_fmt_duration(avg)}   min {_fmt_duration(min(durations))}   max {_fmt_duration(max(durations))}"

    lines = [
        "STAGE PERFORMANCE",
        f"  Update         total {update_total}   avg {update_avg}/tender   min {update_min}   max {update_max}",
        f"  OCR            {stage_timing('ocr')}",
        f"  Classification {stage_timing('classification')}",
        f"  Extraction     {stage_timing('extraction')}",
        f"  Ingestion      {stage_timing('ingestion')}",
    ]
    return "\n".join(lines)


def _section_data_quality(conn, batch_id: str) -> str:
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

    total_triples = lots_total = shacl_pass = post_pass = ing_count = 0
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

    cls_steps = {"1": 0, "2": 0, "3": 0}
    for row in conn.execute(
        "SELECT detail FROM tender_stage WHERE batch_id=? AND stage='classification' AND status='complete'",
        (batch_id,)
    ).fetchall():
        d = json.loads(row["detail"]) if row["detail"] else {}
        for k, v in (d.get("classification_steps") or {}).items():
            cls_steps[str(k)] = cls_steps.get(str(k), 0) + v

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

    return "ANOMALIES  (" + str(len(items)) + ")\n" + "\n".join(items)


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
