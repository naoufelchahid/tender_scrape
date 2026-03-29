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
    return REGIONS[slugify(region_name)]

def get_category_uri(category_name: str) -> URIRef:
    """
    Map category string to SKOS concept URI.
    Categories: Travaux, Fournitures, Services (French tender categories)
    """
    if not category_name:
        return ACTIVITY["unknown"]
    # Normalize category name
    cat_lower = category_name.lower().strip()
    if "travaux" in cat_lower or "work" in cat_lower:
        return ACTIVITY["travaux"]
    elif "fourniture" in cat_lower or "supply" in cat_lower:
        return ACTIVITY["fournitures"]
    elif "service" in cat_lower:
        return ACTIVITY["services"]
    else:
        return ACTIVITY[slugify(category_name)]

def get_lot_uri(tender_ref: str, lot_index: int) -> URIRef:
    """URI for a lot node: ts:Lot_{slug}_{index}"""
    return TS[f"Lot_{slugify(tender_ref)}_{lot_index}"]

def get_spec_chunk_uri(tender_ref: str, chunk_index: int) -> URIRef:
    """URI for a specification chunk node (TenderSpecifications class)."""
    return TS[f"SpecChunk_{slugify(tender_ref)}_{chunk_index}"]

def get_admin_chunk_uri(tender_ref: str, chunk_index: int) -> URIRef:
    """URI for an administrative chunk node (TenderReglement class)."""
    return TS[f"RCChunk_{slugify(tender_ref)}_{chunk_index}"]
