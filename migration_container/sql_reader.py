"""
SQL data access layer for the migration.

Reads Tender + Buyer rows from the relational database in READ-ONLY mode,
ordered by publication_date ASC (tender timeline order), with batch pagination.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Generator, List, Optional

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session

# Import the production SQLAlchemy models (shared package)
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database.models import Tender, Buyer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transfer-object models
# ---------------------------------------------------------------------------

@dataclass
class BuyerRow:
    """
    Typed transfer object for a Buyer record.
    Using Pydantic-free dataclass for zero external dependencies.
    """
    sql_id: int
    name: str
    initials: Optional[str] = None
    buyer_type: Optional[str] = None
    location: Optional[str] = None


@dataclass
class TenderRow:
    """
    Typed transfer object for a Tender record with its associated buyer.
    Only the fields needed for Tender & Buyer triple creation are included.
    """
    sql_id: int
    reference: str
    title: Optional[str] = None
    publication_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    budget: Optional[Decimal] = None
    lot_count: Optional[int] = None   # → Has_Multilot = lot_count > 1
    status: Optional[str] = None
    buyer: Optional[BuyerRow] = None


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

class SQLReader:
    """
    Read-only SQL reader that yields TenderRows ordered by publication_date.
    """

    def __init__(self, database_url: str) -> None:
        """
        Args:
            database_url: SQLAlchemy-compatible connection string, e.g.
                          'postgresql://user:pw@host/dbname'
        """
        self._engine = create_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
        )
        self._SessionLocal = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
        )
        logger.info("SQLReader initialised (read-only connection)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def count_tenders(self) -> int:
        """Return the total number of tenders in the database."""
        with self._session() as session:
            total: int = session.scalar(select(func.count(Tender.id)))  # type: ignore[arg-type]
            logger.debug("Total tenders in DB: %d", total)
            return total

    def fetch_tenders_with_buyers(
        self, batch_size: int = 100, offset: int = 0
    ) -> List[TenderRow]:
        """
        Fetch a page of Tender+Buyer rows, ordered by publication_date ASC
        (tender timeline order).

        Args:
            batch_size: Maximum rows to return.
            offset:     Number of rows to skip (for pagination).

        Returns:
            List of TenderRow transfer objects.
        """
        with self._session() as session:
            stmt = (
                select(Tender)
                .outerjoin(Buyer, Tender.buyer_id == Buyer.id)
                .order_by(Tender.publication_date.asc().nulls_last())
                .offset(offset)
                .limit(batch_size)
            )
            rows = session.scalars(stmt).all()
            logger.debug(
                "Fetched %d tenders (offset=%d, batch_size=%d)",
                len(rows),
                offset,
                batch_size,
            )
            return [self._to_tender_row(t) for t in rows]

    def iter_all_batches(
        self, batch_size: int = 100
    ) -> Generator[List[TenderRow], None, None]:
        """
        Generator that yields successive batches from the full dataset,
        ordered by publication_date ASC.

        Usage::

            for batch in reader.iter_all_batches(batch_size=50):
                for tender_row in batch:
                    ...
        """
        offset = 0
        while True:
            batch = self.fetch_tenders_with_buyers(
                batch_size=batch_size, offset=offset
            )
            if not batch:
                logger.info("No more batches after offset=%d — done.", offset)
                break
            yield batch
            offset += batch_size

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _session(self) -> Session:
        """Return a new SQLAlchemy session as a context manager."""
        return self._SessionLocal()  # type: ignore[return-value]

    def _to_tender_row(self, tender: Tender) -> TenderRow:
        """Map a SQLAlchemy Tender ORM object to a TenderRow DTO."""
        buyer_row: Optional[BuyerRow] = None
        if tender.buyer is not None:
            b = tender.buyer
            buyer_row = BuyerRow(
                sql_id=b.id,
                name=b.name or "",
                initials=b.initials,
                buyer_type=b.type,
                location=b.location,
            )
        return TenderRow(
            sql_id=tender.id,
            reference=tender.reference,
            title=tender.title,
            publication_date=tender.publication_date,
            deadline=tender.deadline,
            budget=tender.budget,
            lot_count=tender.lot_count or tender.nbr_of_lots,
            status=tender.status,
            buyer=buyer_row,
        )

    def close(self) -> None:
        """Dispose the engine connection pool."""
        self._engine.dispose()
        logger.info("SQLReader connection pool disposed")
