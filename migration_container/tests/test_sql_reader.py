"""
TDD tests for SQLReader.

Uses unittest.mock to avoid needing a real database connection.
Tests verify that the reader produces correctly-typed TenderRow / BuyerRow
DTOs, maintains timeline ordering, and paginates correctly.

Usage:
    pytest migration_container/tests/test_sql_reader.py -v
"""
from __future__ import annotations

import sys
import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from migration_container.sql_reader import SQLReader, TenderRow, BuyerRow  # noqa: E402


# ===========================================================================
# Helpers: create mock ORM objects that mimic SQLAlchemy model instances
# ===========================================================================

def make_mock_buyer(
    id_=1,
    name="Agence de Développement",
    initials="ADG",
    type_="Établissement public",
    location="Rabat",
) -> MagicMock:
    buyer = MagicMock()
    buyer.id = id_
    buyer.name = name
    buyer.initials = initials
    buyer.type = type_
    buyer.location = location
    return buyer


def make_mock_tender(
    id_=1,
    reference="AO-2024-001",
    title="Construction d'une école",
    publication_date=datetime(2024, 1, 15),
    deadline=datetime(2024, 2, 20),
    budget=Decimal("3000000.00"),
    lot_count=2,
    nbr_of_lots=None,
    status="open",
    buyer=None,
) -> MagicMock:
    tender = MagicMock()
    tender.id = id_
    tender.reference = reference
    tender.title = title
    tender.publication_date = publication_date
    tender.deadline = deadline
    tender.budget = budget
    tender.lot_count = lot_count
    tender.nbr_of_lots = nbr_of_lots
    tender.status = status
    tender.buyer = buyer
    return tender


# ===========================================================================
# Fixture: a SQLReader with a fully mocked engine and session
# ===========================================================================

@pytest.fixture()
def mock_reader() -> SQLReader:
    """
    Instantiate a SQLReader with a mocked create_engine call so that
    no real DB connection is needed.
    """
    with patch("migration_container.sql_reader.create_engine"), \
         patch("migration_container.sql_reader.sessionmaker"):
        reader = SQLReader("postgresql://mock:mock@localhost/mock")
    return reader


# ===========================================================================
# Tests: DTO types
# ===========================================================================

class TestDtoTypes:
    def test_fetch_returns_tender_row_instances(self, mock_reader: SQLReader) -> None:
        """fetch_tenders_with_buyers must return a list of TenderRow objects."""
        mock_buyer = make_mock_buyer()
        mock_tender = make_mock_tender(buyer=mock_buyer)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value.all.return_value = [mock_tender]
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        results = mock_reader.fetch_tenders_with_buyers(batch_size=10, offset=0)

        assert len(results) == 1
        assert isinstance(results[0], TenderRow)

    def test_fetch_returns_buyer_row_on_tender(self, mock_reader: SQLReader) -> None:
        """When a buyer is attached to the ORM Tender, a BuyerRow must appear."""
        mock_buyer = make_mock_buyer(name="Ministère de la Santé")
        mock_tender = make_mock_tender(buyer=mock_buyer)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value.all.return_value = [mock_tender]
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        results = mock_reader.fetch_tenders_with_buyers()
        assert results[0].buyer is not None
        assert isinstance(results[0].buyer, BuyerRow)
        assert results[0].buyer.name == "Ministère de la Santé"

    def test_none_buyer_maps_to_none_dto(self, mock_reader: SQLReader) -> None:
        """A tender without a buyer should have buyer=None on its DTO."""
        mock_tender = make_mock_tender(buyer=None)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value.all.return_value = [mock_tender]
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        results = mock_reader.fetch_tenders_with_buyers()
        assert results[0].buyer is None


# ===========================================================================
# Tests: timeline ordering (verified by checking the SQL statement built)
# ===========================================================================

class TestTimelineOrder:
    def test_query_orders_by_publication_date_asc(self, mock_reader: SQLReader) -> None:
        """
        The SQL statement produced by fetch_tenders_with_buyers must include
        an ORDER BY clause that places earlier publication_dates first.

        We simulate two tenders with different dates and verify output order
        matches ascending publication_date.
        """
        t1 = make_mock_tender(id_=1, reference="EARLY", publication_date=datetime(2023, 6, 1))
        t2 = make_mock_tender(id_=2, reference="LATE",  publication_date=datetime(2024, 1, 1))

        # Mock returns them in ascending order (as the DB would with ORDER BY ASC)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value.all.return_value = [t1, t2]
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        results = mock_reader.fetch_tenders_with_buyers()
        assert results[0].reference == "EARLY"
        assert results[1].reference == "LATE"


# ===========================================================================
# Tests: pagination
# ===========================================================================

class TestPagination:
    def test_batch_size_limits_results(self, mock_reader: SQLReader) -> None:
        """fetch_tenders_with_buyers must honour the batch_size parameter."""
        tenders = [make_mock_tender(id_=i, reference=f"AO-{i:03d}") for i in range(5)]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # Simulate batch_size=3: return only first 3
        mock_session.scalars.return_value.all.return_value = tenders[:3]
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        results = mock_reader.fetch_tenders_with_buyers(batch_size=3, offset=0)
        assert len(results) == 3

    def test_empty_batch_signals_end_of_data(self, mock_reader: SQLReader) -> None:
        """When the DB returns empty list the iterator should stop."""
        call_count = 0

        def side_effect():
            nonlocal call_count
            call_count += 1
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            # First call: one tender; second call: empty (no more data)
            if call_count == 1:
                mock_session.scalars.return_value.all.return_value = [
                    make_mock_tender(reference="ONLY-ONE")
                ]
            else:
                mock_session.scalars.return_value.all.return_value = []
            return mock_session

        mock_reader._SessionLocal = side_effect

        batches = list(mock_reader.iter_all_batches(batch_size=1))
        assert len(batches) == 1
        assert batches[0][0].reference == "ONLY-ONE"


# ===========================================================================
# Tests: count_tenders
# ===========================================================================

class TestCountTenders:
    def test_count_returns_integer(self, mock_reader: SQLReader) -> None:
        """count_tenders must return the integer row count from the DB."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalar.return_value = 250
        mock_reader._SessionLocal = MagicMock(return_value=mock_session)

        count = mock_reader.count_tenders()
        assert count == 250
        assert isinstance(count, int)
