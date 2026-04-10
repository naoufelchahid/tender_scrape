"""Map structured extraction JSON to RDF triples following the ontology."""
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Any

from rdflib import Graph, Literal, RDF, RDFS, XSD, URIRef
from uri_builder import (
    TS, slugify,
    get_result_uri, get_winner_bid_uri, get_bid_uri,
    get_contractor_uri, get_tender_uri,
)

logger = logging.getLogger(__name__)


def _parse_amount(value) -> Decimal:
    """Parse a numeric amount to Decimal."""
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        logger.warning(f"Could not parse amount '{value}', defaulting to 0")
        return Decimal(0)


class ResultRdfMapper:
    def __init__(self, tender_ref: str, tender_iri: str):
        """
        Args:
            tender_ref: Composite tender reference (e.g. '003_2026_SRMCS').
            tender_iri: Full IRI of the existing tender node in Jena.
        """
        self.tender_ref = tender_ref
        self.tender_uri = URIRef(tender_iri)
        self.graph = Graph()
        self.graph.bind("ts", TS)

    def map_results(self, extracted_data: Dict[str, Any]) -> None:
        """Map extracted lot/bidder JSON into RDF triples."""
        lots = extracted_data.get("lots", [])
        for lot_idx, lot in enumerate(lots):
            self._map_lot(lot, lot_idx)

    def _map_lot(self, lot: dict, lot_idx: int) -> None:
        g = self.graph
        result_uri = get_result_uri(self.tender_ref, lot_idx)

        # TenderResults node
        g.add((result_uri, RDF.type, TS.TenderResults))
        g.add((self.tender_uri, TS.Is_Opened, result_uri))
        g.add((result_uri, TS.Is_Proces_Verbal_of, self.tender_uri))
        g.add((result_uri, TS.Has_PV, Literal(True, datatype=XSD.boolean)))

        # Winner
        winner = lot.get("winner")
        if winner and winner.get("company_name"):
            winner_bid_uri = get_winner_bid_uri(self.tender_ref, lot_idx)
            winner_contractor_uri = get_contractor_uri(winner["company_name"])

            g.add((winner_bid_uri, RDF.type, TS.TenderBids))
            g.add((result_uri, TS.Is_Winner_Bid, winner_bid_uri))
            g.add((result_uri, TS.Has_Bid, winner_bid_uri))
            g.add((winner_bid_uri, TS.Is_Bid_in, result_uri))

            amount = _parse_amount(winner.get("winning_amount"))
            g.add((winner_bid_uri, TS.Has_Bid_Amount,
                   Literal(amount, datatype=XSD.decimal)))

            g.add((winner_contractor_uri, RDF.type, TS.Contractor))
            g.add((winner_contractor_uri, RDFS.label,
                   Literal(winner["company_name"], datatype=XSD.string)))
            g.add((winner_bid_uri, TS.Is_Bid_of, winner_contractor_uri))
            g.add((winner_contractor_uri, TS.Formulate_Bid, winner_bid_uri))

        # Other bidders
        for bid_idx, bidder in enumerate(lot.get("bidders", [])):
            bid_uri = get_bid_uri(self.tender_ref, lot_idx, bid_idx)
            contractor_uri = get_contractor_uri(bidder["company_name"])

            g.add((bid_uri, RDF.type, TS.TenderBids))
            g.add((result_uri, TS.Has_Bid, bid_uri))
            g.add((bid_uri, TS.Is_Bid_in, result_uri))

            amount = _parse_amount(bidder.get("bid_amount"))
            g.add((bid_uri, TS.Has_Bid_Amount,
                   Literal(amount, datatype=XSD.decimal)))

            g.add((contractor_uri, RDF.type, TS.Contractor))
            g.add((contractor_uri, RDFS.label,
                   Literal(bidder["company_name"], datatype=XSD.string)))
            g.add((bid_uri, TS.Is_Bid_of, contractor_uri))
            g.add((contractor_uri, TS.Formulate_Bid, bid_uri))

            # Rejected bid
            status = (bidder.get("status") or "").lower()
            if status in ("excluded", "rejected", "disqualified"):
                g.add((result_uri, TS.Rejected_Bid, bid_uri))

    def get_ntriples(self) -> str:
        """Serialize graph as N-Triples for SPARQL INSERT DATA."""
        return self.graph.serialize(format="nt")

    def get_is_result_triple(self) -> str:
        """Return the N-Triple that sets ts:Is_Result=true on the tender."""
        g = Graph()
        g.add((self.tender_uri, TS.Is_Result,
               Literal(True, datatype=XSD.boolean)))
        return g.serialize(format="nt")
