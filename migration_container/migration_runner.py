"""
Migration orchestrator: SQL → Neptune for Tender & Buyer triples.

Processes records in publication_date ASC order (tender timeline), in
configurable batches, with optional dry-run mode for safe validation.

Usage
-----
    # Dry-run (prints triples, no Neptune writes)
    DRY_RUN=true DATABASE_URL="..." python -m migration_container.migration_runner

    # Live migration
    DATABASE_URL="..." NEPTUNE_ENDPOINT="<host>" python -m migration_container.migration_runner
"""
from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from rdflib import Graph

# ---------------------------------------------------------------------------
# Path setup — allows running as a module from the project root
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "kb_ingestion_container", "src"),
)

from migration_container.config import settings          # noqa: E402
from migration_container.sql_reader import SQLReader, TenderRow   # noqa: E402
from migration_container.triple_builder import TripleBuilder      # noqa: E402
# NeptuneClient is imported lazily inside __init__ so tests can patch it
# without requiring requests_aws4auth to be installed.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("migration_runner")


# ---------------------------------------------------------------------------
# Stats container
# ---------------------------------------------------------------------------

@dataclass
class MigrationStats:
    total_tenders: int = 0
    migrated: int = 0
    skipped: int = 0
    errors: int = 0
    start_time: float = field(default_factory=time.monotonic)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def summary(self) -> str:
        return (
            f"Migration complete — "
            f"migrated={self.migrated} | "
            f"skipped={self.skipped} | "
            f"errors={self.errors} | "
            f"total={self.total_tenders} | "
            f"duration={self.elapsed_seconds:.1f}s"
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class MigrationRunner:
    """
    Orchestrates the full SQL → Neptune migration for Tender + Buyer triples.

    Steps per batch
    ---------------
    1. Fetch a page of TenderRows from SQL (ordered by publication_date ASC)
    2. Build RDF graphs via TripleBuilder
    3. Upload merged batch graph to Neptune (or log in dry-run mode)
    4. Log progress and stats
    """

    def __init__(
        self,
        database_url: str,
        neptune_endpoint: str,
        neptune_port: int,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.dry_run = dry_run

        logger.info(
            "Initialising MigrationRunner │ batch_size=%d │ dry_run=%s",
            batch_size,
            dry_run,
        )

        self._reader = SQLReader(database_url)
        self._builder = TripleBuilder()

        if not dry_run:
            # Lazy import so tests never need requests_aws4auth installed
            sys.path.insert(
                0,
                os.path.join(os.path.dirname(__file__), "..", "kb_ingestion_container"),
            )
            from src.neptune_client import NeptuneClient  # type: ignore[import]

            os.environ["NEPTUNE_ENDPOINT"] = neptune_endpoint
            os.environ["NEPTUNE_PORT"] = str(neptune_port)
            self._neptune = NeptuneClient()
        else:
            self._neptune = None  # type: ignore[assignment]
            logger.info("DRY-RUN mode: no triples will be written to Neptune")


    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> MigrationStats:
        """
        Execute the full migration and return final statistics.
        """
        stats = MigrationStats()

        # ── Step 0: count for progress reporting ──────────────────────
        try:
            stats.total_tenders = self._reader.count_tenders()
        except Exception as exc:
            logger.error("Cannot count tenders: %s", exc)
            stats.total_tenders = -1  # unknown

        logger.info(
            "Starting migration │ total_tenders=%s │ batch_size=%d",
            stats.total_tenders if stats.total_tenders >= 0 else "unknown",
            self.batch_size,
        )

        # ── Step 1-N: iterate batches ──────────────────────────────────
        batch_num = 0
        for batch in self._reader.iter_all_batches(batch_size=self.batch_size):
            batch_num += 1
            self._process_batch(batch, batch_num, stats)

        # ── Final summary ──────────────────────────────────────────────
        logger.info(stats.summary())
        self._reader.close()
        return stats

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _process_batch(
        self,
        batch: List[TenderRow],
        batch_num: int,
        stats: MigrationStats,
    ) -> None:
        """
        Process one batch:
          - Build one RDF graph per Tender
          - Merge all into a batch-level graph
          - Upload to Neptune (or log in dry-run)
        """
        batch_graph = Graph()
        dates: List[datetime] = [
            t.publication_date for t in batch if t.publication_date
        ]
        earliest = min(dates).date() if dates else "?"
        latest   = max(dates).date() if dates else "?"

        logger.info(
            "── Batch %d ──  records=%d  timeline=[%s → %s]",
            batch_num,
            len(batch),
            earliest,
            latest,
        )

        batch_migrated = 0
        batch_skipped  = 0
        batch_errors   = 0

        for tender_row in batch:
            try:
                graph = self._builder.build_tender_graph(tender_row)

                if len(graph) == 0:
                    logger.warning(
                        "  SKIP %s — empty graph (no usable data)",
                        tender_row.reference,
                    )
                    batch_skipped += 1
                    continue

                # Merge into batch graph for bulk upload
                batch_graph += graph
                batch_migrated += 1
                logger.debug(
                    "  OK   %s — %d triples",
                    tender_row.reference,
                    len(graph),
                )

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "  ERR  %s — %s: %s",
                    tender_row.reference,
                    type(exc).__name__,
                    exc,
                )
                batch_errors += 1

        # ── Upload or dry-log ──────────────────────────────────────────
        if len(batch_graph) > 0:
            self._upload_batch(batch_graph, batch_num)
        else:
            logger.warning("Batch %d produced zero triples — nothing uploaded", batch_num)

        logger.info(
            "  Batch %d done  migrated=%d  skipped=%d  errors=%d  triples=%d",
            batch_num,
            batch_migrated,
            batch_skipped,
            batch_errors,
            len(batch_graph),
        )

        stats.migrated  += batch_migrated
        stats.skipped   += batch_skipped
        stats.errors    += batch_errors

    def _upload_batch(self, graph: Graph, batch_num: int) -> None:
        """Send a batch graph to Neptune, or log it in dry-run mode."""
        triple_count = len(graph)

        if self.dry_run:
            # Serialise to N-Triples for review
            logger.info(
                "[DRY-RUN] Batch %d — would upload %d triples",
                batch_num,
                triple_count,
            )
            sample = graph.serialize(format="ntriples").splitlines()[:5]
            for line in sample:
                logger.info("  [DRY-RUN] %s", line)
            if triple_count > 5:
                logger.info(
                    "  [DRY-RUN] ... (%d more triples not shown)",
                    triple_count - 5,
                )
            return

        try:
            self._neptune.upload_graph(graph)
            logger.info(
                "  ✔ Batch %d uploaded to Neptune (%d triples)",
                batch_num,
                triple_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "  ✗ Batch %d Neptune upload failed: %s",
                batch_num,
                exc,
            )
            raise


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    runner = MigrationRunner(
        database_url=settings.DATABASE_URL,
        neptune_endpoint=settings.NEPTUNE_ENDPOINT,
        neptune_port=settings.NEPTUNE_PORT,
        batch_size=settings.BATCH_SIZE,
        dry_run=settings.DRY_RUN,
    )
    final_stats = runner.run()
    # Exit with error code if there were any errors
    sys.exit(1 if final_stats.errors > 0 else 0)
