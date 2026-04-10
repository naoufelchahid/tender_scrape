#!/usr/bin/env python3
"""
Real-time anomaly monitor for e2e test.
Polls pipeline.db every 5 seconds and reports new anomalies, failures, and queue depths.
"""
import sqlite3
import json
import time
import os
from datetime import datetime
from pathlib import Path

DB_PATH = "pipeline.db"
CHECK_INTERVAL = 5  # seconds
LAST_ANOMALY_ID = 0
LAST_FAILURE_ID = 0

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def print_header():
    print(f"\n{'='*80}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ANOMALY MONITOR")
    print(f"{'='*80}")

def check_anomalies():
    global LAST_ANOMALY_ID
    if not os.path.exists(DB_PATH):
        return
    
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, batch_id, tender_ref, stage, detail FROM events WHERE event='anomaly' ORDER BY id"
        ).fetchall()
        
        new_count = 0
        for row in rows:
            if row["id"] > LAST_ANOMALY_ID:
                if new_count == 0:
                    print_header()
                flags = json.loads(row["detail"]).get("flags", [])
                print(f"\n🚨 ANOMALY [{row['stage']}] {row['tender_ref']}")
                for flag in flags:
                    print(f"   └─ {flag}")
                LAST_ANOMALY_ID = row["id"]
                new_count += 1
        
        conn.close()
    except Exception as e:
        pass

def check_failures():
    global LAST_FAILURE_ID
    if not os.path.exists(DB_PATH):
        return
    
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, batch_id, tender_ref, stage, detail FROM events WHERE event='failed' ORDER BY id"
        ).fetchall()
        
        new_count = 0
        for row in rows:
            if row["id"] > LAST_FAILURE_ID:
                if new_count == 0:
                    print_header()
                detail = json.loads(row["detail"]) if row["detail"] else {}
                error = detail.get("error", "unknown")
                print(f"\n❌ FAILED [{row['stage']}] {row['tender_ref']}")
                print(f"   └─ {error[:100]}")
                LAST_FAILURE_ID = row["id"]
                new_count += 1
        
        conn.close()
    except Exception as e:
        pass

def check_progress():
    if not os.path.exists(DB_PATH):
        return
    
    try:
        conn = get_db()
        
        # Get pending batches
        batch = conn.execute(
            "SELECT DISTINCT batch_id FROM events WHERE event='batch_end' ORDER BY batch_id DESC LIMIT 1"
        ).fetchone()
        
        if not batch:
            return
        
        batch_id = batch[0]
        
        # Get summary
        end_row = conn.execute(
            "SELECT detail FROM events WHERE event='batch_end' AND batch_id=?", (batch_id,)
        ).fetchone()
        
        if not end_row:
            return
        
        total = json.loads(end_row["detail"]).get("total_scraped", 0)
        
        # Count by status
        summary = {}
        for stage in ("ocr", "classification", "extraction", "ingestion"):
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tender_stage WHERE batch_id=? AND stage=? GROUP BY status",
                (batch_id, stage)
            ).fetchall()
            summary[stage] = {r["status"]: r["cnt"] for r in rows}
        
        print(f"\n📊 PROGRESS [{batch_id}]  Total: {total}")
        for stage, counts in summary.items():
            ok = counts.get("complete", 0)
            fail = counts.get("failed", 0)
            running = counts.get("running", 0)
            status = f"{ok}✓ {fail}✗"
            if running:
                status += f" ({running}→)"
            print(f"   {stage:15} {status}")
        
        conn.close()
    except Exception as e:
        pass

def main():
    print("Starting anomaly monitor (Ctrl+C to stop)...")
    print("Watching pipeline.db for anomalies, failures, and progress...")
    
    while True:
        try:
            check_anomalies()
            check_failures()
            check_progress()
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("\n\nMonitor stopped.")
            break
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
