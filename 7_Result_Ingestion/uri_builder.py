"""URI generation for result, bid, and contractor RDF nodes."""
import re
import unicodedata
from rdflib import Namespace, URIRef

TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")


def slugify(text: str) -> str:
    """Create a URL-safe slug from text.

    Mirrors the logic in 1_Update/kg_builder.py and 5_Ingestion/src/uri_builder.py:
    strip accents, replace non-alphanumeric with _, collapse runs, uppercase.
    """
    if not text:
        return "unknown"
    nfkd = unicodedata.normalize('NFKD', text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', without_accents)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip('_').upper()


def get_tender_uri(tender_ref: str) -> URIRef:
    return TS[f"Tender_{slugify(tender_ref)}"]


def get_result_uri(tender_ref: str, lot_index: int) -> URIRef:
    return TS[f"Result_{slugify(tender_ref)}_{lot_index}"]


def get_winner_bid_uri(tender_ref: str, lot_index: int) -> URIRef:
    return TS[f"Bid_Winner_{slugify(tender_ref)}_{lot_index}"]


def get_bid_uri(tender_ref: str, lot_index: int, bid_index: int) -> URIRef:
    return TS[f"Bid_{slugify(tender_ref)}_{lot_index}_{bid_index}"]


def get_contractor_uri(company_name: str) -> URIRef:
    return TS[f"Contractor_{slugify(company_name)}"]
