import re
from rdflib import Namespace, URIRef

TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
REGIONS = Namespace("http://www.tenderintelligence.io/ontology/regions#")
ACTIVITY = Namespace("http://www.tenderintelligence.io/ontology/activity-domains#")

def slugify(text: str) -> str:
    """Create a URL-safe slug from text."""
    if not text:
        return "unknown"
    # Replace non-alphanumeric with underscore
    s = re.sub(r'[^a-zA-Z0-9]', '_', text)
    # Remove duplicate underscores
    s = re.sub(r'_+', '_', s)
    return s.strip('_')

def get_tender_uri(tender_ref: str) -> URIRef:
    return TS[f"Tender_{slugify(tender_ref)}"]

def get_buyer_uri(buyer_name: str) -> URIRef:
    return TS[f"Buyer_{slugify(buyer_name)}"]

def get_bordereau_uri(tender_ref: str) -> URIRef:
    return TS[f"Bordereau_{slugify(tender_ref)}"]

def get_article_uri(tender_ref: str, index: int) -> URIRef:
    return TS[f"Article_{slugify(tender_ref)}_{index}"]

def get_specification_uri(tender_ref: str) -> URIRef:
    return TS[f"Spec_{slugify(tender_ref)}"]

def get_reglement_uri(tender_ref: str) -> URIRef:
    return TS[f"RC_{slugify(tender_ref)}"]

def get_region_uri(region_name: str) -> URIRef:
    # This might need a mapping dictionary later
    return REGIONS[slugify(region_name)]
