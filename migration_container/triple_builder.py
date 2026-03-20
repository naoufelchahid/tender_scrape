"""
RDF triple builder: SQL row → rdflib Graph following tender_structure.owl.

Produces triples for:
  - ts:Tenders individual  (data properties: Has_Object, Has_Budget,
                             Has_Deadline, Has_Multilot)
  - ts:Buyers  individual  (rdfs:label)
  - ts:Launched_by         (ObjectProperty Tender → Buyer)

Only non-null values produce triples; NULL SQL fields are silently skipped.
"""
from __future__ import annotations

import logging
import sys
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD, URIRef

# ---------------------------------------------------------------------------
# Path wiring: reuse shared uri_builder from kb_ingestion_container
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kb_ingestion_container", "src"))
from uri_builder import get_tender_uri, get_buyer_uri, TS  # noqa: E402

from .sql_reader import TenderRow, BuyerRow  # noqa: E402

logger = logging.getLogger(__name__)


class TripleBuilder:
    """
    Build an rdflib.Graph from a single (TenderRow, BuyerRow) pair.

    Design decisions aligned with the OWL ontology
    (tender_structure.owl):
      - Tender URI  → TS.Tender_<slugified_reference>
      - Buyer URI   → TS.Buyer_<slugified_buyer_name>
      - Has_Object  → xsd:string  (tender title)
      - Has_Budget  → xsd:decimal (budget estimation)
      - Has_Deadline→ xsd:dateTime (bid submission deadline)
      - Has_Multilot→ xsd:boolean (True if lot_count > 1)
      - rdfs:label  → xsd:string  on Buyer (official organisational name)
      - Launched_by → ObjectProperty Tender → Buyer
    """

    def build_tender_graph(
        self,
        tender: TenderRow,
        buyer: Optional[BuyerRow] = None,
    ) -> Graph:
        """
        Construct an RDF graph for one Tender and its associated Buyer.

        Args:
            tender: Typed DTO from SQLReader.
            buyer:  Optional; when provided (or accessible via tender.buyer),
                    Buyer triples and the Launched_by edge are emitted.

        Returns:
            rdflib.Graph with all applicable triples.
        """
        g = Graph()
        # Bind namespaces for cleaner Turtle serialisation in logs
        g.bind("ts", TS)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)

        buyer_data: Optional[BuyerRow] = buyer or tender.buyer

        # ----------------------------------------------------------------
        # 1. Tender individual
        # ----------------------------------------------------------------
        tender_uri: URIRef = get_tender_uri(tender.reference)
        g.add((tender_uri, RDF.type, TS.Tenders))
        logger.debug("Building triples for Tender: %s", tender_uri)

        # Has_Object  — tender title / object description
        if tender.title:
            g.add((
                tender_uri,
                TS.Has_Object,
                Literal(tender.title, datatype=XSD.string),
            ))
            logger.debug("  + Has_Object: %s", tender.title[:60])

        # Has_Budget  — decimal budget estimation
        if tender.budget is not None:
            g.add((
                tender_uri,
                TS.Has_Budget,
                Literal(Decimal(str(tender.budget)), datatype=XSD.decimal),
            ))
            logger.debug("  + Has_Budget: %s", tender.budget)

        # Has_Deadline — ISO 8601 datetime for bid submission close
        if tender.deadline is not None:
            iso_deadline = self._to_xsd_datetime(tender.deadline)
            g.add((
                tender_uri,
                TS.Has_Deadline,
                Literal(iso_deadline, datatype=XSD.dateTime),
            ))
            logger.debug("  + Has_Deadline: %s", iso_deadline)

        # Has_Multilot — boolean flag derived from lot_count
        lot_count = tender.lot_count or 0
        g.add((
            tender_uri,
            TS.Has_Multilot,
            Literal(lot_count > 1, datatype=XSD.boolean),
        ))
        logger.debug("  + Has_Multilot: %s (lot_count=%s)", lot_count > 1, lot_count)

        # ----------------------------------------------------------------
        # 2. Buyer individual + Launched_by relationship
        # ----------------------------------------------------------------
        if buyer_data and buyer_data.name:
            buyer_uri: URIRef = get_buyer_uri(buyer_data.name)
            g.add((buyer_uri, RDF.type, TS.Buyers))
            g.add((
                buyer_uri,
                RDFS.label,
                Literal(buyer_data.name, datatype=XSD.string),
            ))
            # ts:Launched_by   Tender → Buyer
            g.add((tender_uri, TS.Launched_by, buyer_uri))
            logger.debug("  + Launched_by → Buyer: %s", buyer_uri)
        else:
            logger.debug(
                "  ~ No buyer info for tender %s — Launched_by skipped",
                tender.reference,
            )

        return g

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_xsd_datetime(dt: datetime) -> str:
        """
        Format a Python datetime as an ISO 8601 / xsd:dateTime string.
        Neptune requires timezone-aware datetimes; we add +00:00 when
        the datetime is naive (most DB timestamps lack tz info).
        """
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        return dt.isoformat()
