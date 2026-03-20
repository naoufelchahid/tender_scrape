"""
TDD tests for MigrationRunner.

Verifies orchestration behaviour: correct batch iteration, dry-run isolation,
progress logging, error handling, and final stats.

Uses mocks so no real SQL or Neptune instance is needed.

Usage:
    pytest migration_container/tests/test_migration_runner.py -v
"""
from __future__ import annotations

import sys
import os
import logging
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "kb_ingestion_container",
        "src",
    ),
)

from migration_container.migration_runner import MigrationRunner, MigrationStats  # noqa: E402
from migration_container.sql_reader import TenderRow, BuyerRow                    # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def make_tender(
    ref: str = "AO-001",
    title: str = "Test Tender",
    pub_date: datetime = datetime(2024, 1, 1),
    deadline: datetime = datetime(2024, 2, 1),
    budget: Decimal = Decimal("1000000"),
    lot_count: int = 1,
) -> TenderRow:
    return TenderRow(
        sql_id=1,
        reference=ref,
        title=title,
        publication_date=pub_date,
        deadline=deadline,
        budget=budget,
        lot_count=lot_count,
        buyer=BuyerRow(sql_id=10, name="Ville de Rabat"),
    )


def _make_runner(dry_run: bool = True) -> MigrationRunner:
    """
    Return a MigrationRunner whose SQL reader, triple builder, and Neptune
    client are all mocked — no external connections needed.

    NeptuneClient is now imported lazily inside MigrationRunner.__init__
    when dry_run=False, so for dry_run=True tests we only need to mock
    SQLReader (which also uses create_engine at import time).
    """
    with patch("migration_container.sql_reader.create_engine"), \
         patch("migration_container.sql_reader.sessionmaker"):
        runner = MigrationRunner(
            database_url="postgresql://mock:mock@localhost/mock",
            neptune_endpoint="mock-endpoint",
            neptune_port=8182,
            batch_size=10,
            dry_run=dry_run,
        )
    # Replace the real SQLReader instance with a clean MagicMock
    runner._reader = MagicMock()
    return runner



# ===========================================================================
# Dry-run mode
# ===========================================================================

class TestDryRun:
    def test_dry_run_does_not_call_neptune_upload(self) -> None:
        """In dry-run mode, _neptune must remain None and upload never called."""
        runner = _make_runner(dry_run=True)
        assert runner._neptune is None, "Neptune client must not be created in dry-run"

    def test_dry_run_processes_batches_without_upload(self) -> None:
        """
        In dry-run mode, run() must iterate all batches and return stats
        without ever calling any Neptune method.
        """
        runner = _make_runner(dry_run=True)

        tender = make_tender()
        runner._reader.count_tenders.return_value = 1
        runner._reader.iter_all_batches.return_value = iter([[tender]])

        stats = runner.run()

        assert stats.migrated == 1
        assert stats.errors == 0

    def test_dry_run_result_is_migration_stats(self) -> None:
        """run() must return a MigrationStats instance."""
        runner = _make_runner(dry_run=True)
        runner._reader.count_tenders.return_value = 0
        runner._reader.iter_all_batches.return_value = iter([])

        result = runner.run()
        assert isinstance(result, MigrationStats)


# ===========================================================================
# Triple count accuracy
# ===========================================================================

class TestTripleCount:
    def test_migrated_count_matches_valid_tenders(self) -> None:
        """
        stats.migrated must equal the number of tenders that produce
        a non-empty graph.
        """
        runner = _make_runner(dry_run=True)
        tenders = [make_tender(ref=f"AO-{i:03d}") for i in range(5)]

        runner._reader.count_tenders.return_value = 5
        runner._reader.iter_all_batches.return_value = iter([tenders])

        stats = runner.run()
        assert stats.migrated == 5

    def test_empty_graph_tender_is_counted_as_skipped(self) -> None:
        """
        A tender that produces zero triples (e.g. corrupt data) should be
        counted as skipped, not migrated.
        """
        runner = _make_runner(dry_run=True)

        # Replace the real builder with a mock that returns an empty Graph
        from rdflib import Graph
        runner._builder = MagicMock()
        runner._builder.build_tender_graph.return_value = Graph()  # zero triples

        bare_tender = TenderRow(sql_id=999, reference="AO-EMPTY")
        runner._reader.count_tenders.return_value = 1
        runner._reader.iter_all_batches.return_value = iter([[bare_tender]])

        stats = runner.run()
        assert stats.skipped == 1
        assert stats.migrated == 0

    def test_error_tender_is_counted_as_error(self) -> None:
        """
        If build_tender_graph raises, the tender must be counted as an error,
        not as a migration failure that halts the whole run.
        """
        runner = _make_runner(dry_run=True)

        runner._builder = MagicMock()
        runner._builder.build_tender_graph.side_effect = ValueError("Malformed data")

        bad_tender = make_tender(ref="AO-BAD")
        runner._reader.count_tenders.return_value = 1
        runner._reader.iter_all_batches.return_value = iter([[bad_tender]])

        stats = runner.run()
        assert stats.errors == 1
        assert stats.migrated == 0


# ===========================================================================
# Progress logging
# ===========================================================================

class TestProgressLogging:
    def test_batch_header_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """
        MigrationRunner must log a batch header containing the batch number
        and the tender count.
        """
        runner = _make_runner(dry_run=True)
        tender = make_tender()

        runner._reader.count_tenders.return_value = 1
        runner._reader.iter_all_batches.return_value = iter([[tender]])

        with caplog.at_level(logging.INFO, logger="migration_runner"):
            runner.run()

        # At least one log line should mention "Batch 1"
        assert any("Batch 1" in r.message for r in caplog.records), (
            "Expected 'Batch 1' in log output"
        )

    def test_summary_logged_after_run(self, caplog: pytest.LogCaptureFixture) -> None:
        """
        After run() completes the summary line must mention 'migrated' count.
        """
        runner = _make_runner(dry_run=True)
        runner._reader.count_tenders.return_value = 0
        runner._reader.iter_all_batches.return_value = iter([])

        with caplog.at_level(logging.INFO, logger="migration_runner"):
            runner.run()

        assert any("migrated=" in r.message for r in caplog.records), (
            "Expected summary line containing 'migrated=' in logs"
        )


# ===========================================================================
# Live mode
# ===========================================================================

class TestLiveMode:
    def test_live_mode_calls_neptune_upload(self) -> None:
        """
        In live mode, upload_graph must be called once per batch.
        We inject a mock NeptuneClient into sys.modules so the lazy
        import inside MigrationRunner.__init__ picks it up.
        """
        import types
        import sys

        mock_neptune_instance = MagicMock()
        mock_neptune_cls = MagicMock(return_value=mock_neptune_instance)

        # Create a fake neptune_client module
        fake_module = types.ModuleType("neptune_client")
        fake_module.NeptuneClient = mock_neptune_cls  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"neptune_client": fake_module}):
            with patch("migration_container.sql_reader.create_engine"), \
                 patch("migration_container.sql_reader.sessionmaker"):
                runner = MigrationRunner(
                    database_url="postgresql://mock:mock@localhost/mock",
                    neptune_endpoint="mock-endpoint",
                    neptune_port=8182,
                    batch_size=10,
                    dry_run=False,                 # triggers Neptune construction
                )
        # Replace the real SQLReader with a mock
        runner._reader = MagicMock()

        tender = make_tender()
        runner._reader.count_tenders.return_value = 1
        runner._reader.iter_all_batches.return_value = iter([[tender]])

        runner.run()

        mock_neptune_instance.upload_graph.assert_called_once()


    def test_stats_elapsed_is_positive(self) -> None:
        """MigrationStats.elapsed_seconds must be a positive float."""
        runner = _make_runner(dry_run=True)
        runner._reader.count_tenders.return_value = 0
        runner._reader.iter_all_batches.return_value = iter([])

        stats = runner.run()
        assert stats.elapsed_seconds >= 0.0
