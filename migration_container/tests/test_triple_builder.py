"""
TDD tests for TripleBuilder.

RED phase: these tests define the *exact* triples that must be emitted for
every combination of inputs.  Run against the real TripleBuilder to verify.

Usage:
    pytest migration_container/tests/test_triple_builder.py -v
"""
from __future__ import annotations

import sys
import os
from datetime import datetime
from decimal import Decimal

import pytest
from rdflib import RDF, RDFS, XSD, Literal, Graph, URIRef

# ---------------------------------------------------------------------------
# Path wiring — allow importing from siblings without installing
# ---------------------------------------------------------------------------
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

from migration_container.triple_builder import TripleBuilder           # noqa: E402
from migration_container.sql_reader import TenderRow, BuyerRow         # noqa: E402
from uri_builder import TS, get_tender_uri, get_buyer_uri              # noqa: E402


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture()
def builder() -> TripleBuilder:
    return TripleBuilder()


@pytest.fixture()
def full_buyer() -> BuyerRow:
    return BuyerRow(
        sql_id=1,
        name="Commune Urbaine de Casablanca",
        initials="CUC",
        buyer_type="Collectivité Territoriale",
        location="Casablanca",
    )


@pytest.fixture()
def full_tender(full_buyer: BuyerRow) -> TenderRow:
    return TenderRow(
        sql_id=42,
        reference="AO-2024-12345",
        title="Travaux de voirie et réseaux divers",
        publication_date=datetime(2024, 3, 15, 9, 0, 0),
        deadline=datetime(2024, 4, 10, 16, 0, 0),
        budget=Decimal("5000000.00"),
        lot_count=3,
        status="open",
        buyer=full_buyer,
    )


@pytest.fixture()
def minimal_tender() -> TenderRow:
    """Tender with only the mandatory reference field — all optionals are None."""
    return TenderRow(
        sql_id=99,
        reference="AO-MINIMAL-001",
    )


# ===========================================================================
# Tender class type triple
# ===========================================================================

class TestTenderType:
    def test_tender_triple_has_correct_rdf_type(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """MUST emit rdf:type ts:Tenders for every tender."""
        g = builder.build_tender_graph(full_tender)
        tender_uri = get_tender_uri(full_tender.reference)
        assert (tender_uri, RDF.type, TS.Tenders) in g, (
            f"Missing rdf:type ts:Tenders for {tender_uri}"
        )


# ===========================================================================
# Tender data properties
# ===========================================================================

class TestTenderDataProperties:
    def test_has_object_string_literal(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """Has_Object must carry the title as xsd:string."""
        g = builder.build_tender_graph(full_tender)
        tender_uri = get_tender_uri(full_tender.reference)
        expected = Literal("Travaux de voirie et réseaux divers", datatype=XSD.string)
        assert (tender_uri, TS.Has_Object, expected) in g

    def test_has_budget_decimal(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """Has_Budget must carry the budget as xsd:decimal."""
        g = builder.build_tender_graph(full_tender)
        tender_uri = get_tender_uri(full_tender.reference)
        expected = Literal(Decimal("5000000.00"), datatype=XSD.decimal)
        assert (tender_uri, TS.Has_Budget, expected) in g

    def test_has_deadline_datetime(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """Has_Deadline must be emitted as xsd:dateTime."""
        g = builder.build_tender_graph(full_tender)
        tender_uri = get_tender_uri(full_tender.reference)
        # Collect all Has_Deadline values and verify we have exactly one
        values = list(g.objects(tender_uri, TS.Has_Deadline))
        assert len(values) == 1, f"Expected 1 Has_Deadline triple, got {len(values)}"
        assert values[0].datatype == XSD.dateTime, (
            f"Has_Deadline datatype should be xsd:dateTime, got {values[0].datatype}"
        )
        # Verify the value contains the expected date
        assert "2024-04-10" in str(values[0])

    def test_has_multilot_true_when_lots_gt_1(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """Has_Multilot must be True when lot_count > 1."""
        g = builder.build_tender_graph(full_tender)
        tender_uri = get_tender_uri(full_tender.reference)
        expected = Literal(True, datatype=XSD.boolean)
        assert (tender_uri, TS.Has_Multilot, expected) in g

    def test_has_multilot_false_when_single_lot(
        self, builder: TripleBuilder
    ) -> None:
        """Has_Multilot must be False when lot_count == 1."""
        tender = TenderRow(sql_id=10, reference="AO-SINGLE", lot_count=1)
        g = builder.build_tender_graph(tender)
        tender_uri = get_tender_uri(tender.reference)
        expected = Literal(False, datatype=XSD.boolean)
        assert (tender_uri, TS.Has_Multilot, expected) in g

    def test_has_multilot_false_when_no_lot_count(
        self, builder: TripleBuilder, minimal_tender: TenderRow
    ) -> None:
        """Has_Multilot must be False when lot_count is None."""
        g = builder.build_tender_graph(minimal_tender)
        tender_uri = get_tender_uri(minimal_tender.reference)
        expected = Literal(False, datatype=XSD.boolean)
        assert (tender_uri, TS.Has_Multilot, expected) in g


# ===========================================================================
# Null / missing value handling
# ===========================================================================

class TestNullValueHandling:
    def test_null_budget_emits_no_triple(
        self, builder: TripleBuilder, minimal_tender: TenderRow
    ) -> None:
        """No Has_Budget triple when budget is None."""
        g = builder.build_tender_graph(minimal_tender)
        tender_uri = get_tender_uri(minimal_tender.reference)
        budgets = list(g.objects(tender_uri, TS.Has_Budget))
        assert budgets == [], f"Expected no Has_Budget triple, got: {budgets}"

    def test_null_title_emits_no_has_object_triple(
        self, builder: TripleBuilder, minimal_tender: TenderRow
    ) -> None:
        """No Has_Object triple when title is None."""
        g = builder.build_tender_graph(minimal_tender)
        tender_uri = get_tender_uri(minimal_tender.reference)
        objects = list(g.objects(tender_uri, TS.Has_Object))
        assert objects == [], f"Expected no Has_Object triple, got: {objects}"

    def test_null_deadline_emits_no_triple(
        self, builder: TripleBuilder, minimal_tender: TenderRow
    ) -> None:
        """No Has_Deadline triple when deadline is None."""
        g = builder.build_tender_graph(minimal_tender)
        tender_uri = get_tender_uri(minimal_tender.reference)
        deadlines = list(g.objects(tender_uri, TS.Has_Deadline))
        assert deadlines == [], f"Expected no Has_Deadline triple, got: {deadlines}"


# ===========================================================================
# Buyer triples
# ===========================================================================

class TestBuyerTriples:
    def test_buyer_has_correct_rdf_type(
        self, builder: TripleBuilder, full_tender: TenderRow, full_buyer: BuyerRow
    ) -> None:
        """Buyer individual must have rdf:type ts:Buyers."""
        g = builder.build_tender_graph(full_tender, full_buyer)
        buyer_uri = get_buyer_uri(full_buyer.name)
        assert (buyer_uri, RDF.type, TS.Buyers) in g

    def test_buyer_has_rdfs_label(
        self, builder: TripleBuilder, full_tender: TenderRow, full_buyer: BuyerRow
    ) -> None:
        """Buyer must have rdfs:label with its name as xsd:string."""
        g = builder.build_tender_graph(full_tender, full_buyer)
        buyer_uri = get_buyer_uri(full_buyer.name)
        expected = Literal("Commune Urbaine de Casablanca", datatype=XSD.string)
        assert (buyer_uri, RDFS.label, expected) in g

    def test_launched_by_links_tender_to_buyer(
        self, builder: TripleBuilder, full_tender: TenderRow, full_buyer: BuyerRow
    ) -> None:
        """ts:Launched_by must connect the Tender IRI to the Buyer IRI."""
        g = builder.build_tender_graph(full_tender, full_buyer)
        tender_uri = get_tender_uri(full_tender.reference)
        buyer_uri  = get_buyer_uri(full_buyer.name)
        assert (tender_uri, TS.Launched_by, buyer_uri) in g

    def test_no_buyer_skips_launched_by(
        self, builder: TripleBuilder, minimal_tender: TenderRow
    ) -> None:
        """No Launched_by triple when there is no buyer information."""
        g = builder.build_tender_graph(minimal_tender)
        tender_uri = get_tender_uri(minimal_tender.reference)
        linked_buyers = list(g.objects(tender_uri, TS.Launched_by))
        assert linked_buyers == [], f"Did not expect Launched_by, got: {linked_buyers}"

    def test_buyer_on_tender_row_used_by_default(
        self, builder: TripleBuilder, full_tender: TenderRow
    ) -> None:
        """Buyer embedded in TenderRow.buyer is used when no explicit buyer arg given."""
        g = builder.build_tender_graph(full_tender)  # no explicit buyer arg
        tender_uri = get_tender_uri(full_tender.reference)
        linked_buyers = list(g.objects(tender_uri, TS.Launched_by))
        assert len(linked_buyers) == 1


# ===========================================================================
# Datetime formatting
# ===========================================================================

class TestDatetimeFormatting:
    def test_naive_datetime_gets_utc_suffix(self, builder: TripleBuilder) -> None:
        """Naive datetimes must be serialised with +00:00 suffix."""
        naive = datetime(2024, 6, 1, 10, 30, 0)
        result = TripleBuilder._to_xsd_datetime(naive)
        assert result.endswith("+00:00"), f"Expected +00:00 suffix, got: {result}"
        assert "2024-06-01T10:30:00" in result

    def test_aware_datetime_uses_isoformat(self, builder: TripleBuilder) -> None:
        """Timezone-aware datetimes use Python's isoformat directly."""
        from datetime import timezone
        aware = datetime(2024, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        result = TripleBuilder._to_xsd_datetime(aware)
        assert "2024-06-01" in result
