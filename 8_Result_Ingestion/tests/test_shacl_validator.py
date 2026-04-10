import pytest
from rdflib import Graph, RDF, RDFS, Literal, XSD
from uri_builder import TS
from rdf_mapper import ResultRdfMapper
from shacl_validator import ShaclValidator

VALID_DATA = {
    "lots": [{
        "lot_reference": "0",
        "winner": {"company_name": "ATLAS SARL", "winning_amount": 100.0},
        "bidders": [
            {"company_name": "BETA SA", "bid_amount": 200.0, "status": "admitted", "rejection_reason": None}
        ]
    }]
}

TENDER_IRI = "http://www.tenderintelligence.io/ontology/tender-structure#Tender_TEST_001"


@pytest.fixture
def validator():
    return ShaclValidator(
        shapes_path="ontology/shapes_results.ttl",
    )


def test_valid_graph_passes(validator):
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(VALID_DATA)
    assert validator.validate(mapper.graph) is True


def test_missing_bid_fails(validator):
    """A TenderResults with no Has_Bid should fail SHACL."""
    g = Graph()
    g.bind("ts", TS)
    from rdflib import URIRef
    result_uri = URIRef(f"{TS}Result_TEST_001_0")
    tender_uri = URIRef(TENDER_IRI)
    g.add((result_uri, RDF.type, TS.TenderResults))
    g.add((result_uri, TS.Is_Proces_Verbal_of, tender_uri))
    # No Has_Bid — should fail
    assert validator.validate(g) is False


def test_missing_is_bid_of_fails(validator):
    """A TenderBids with no Is_Bid_of should fail SHACL."""
    g = Graph()
    g.bind("ts", TS)
    from rdflib import URIRef
    result_uri = URIRef(f"{TS}Result_TEST_001_0")
    tender_uri = URIRef(TENDER_IRI)
    bid_uri = URIRef(f"{TS}Bid_TEST_001_0_0")
    g.add((result_uri, RDF.type, TS.TenderResults))
    g.add((result_uri, TS.Is_Proces_Verbal_of, tender_uri))
    g.add((result_uri, TS.Has_Bid, bid_uri))
    g.add((bid_uri, RDF.type, TS.TenderBids))
    g.add((bid_uri, TS.Is_Bid_in, result_uri))
    # No Is_Bid_of — should fail
    assert validator.validate(g) is False


def test_logical_winner_must_have_positive_amount(validator):
    """Logical assertion: winner bid amount > 0."""
    data = {
        "lots": [{
            "lot_reference": "0",
            "winner": {"company_name": "ATLAS SARL", "winning_amount": 0},
            "bidders": []
        }]
    }
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(data)
    assert validator.validate(mapper.graph) is False


def test_logical_must_have_winner(validator):
    """Logical assertion: at least one Is_Winner_Bid per TenderResults."""
    data = {
        "lots": [{
            "lot_reference": "0",
            "winner": {},
            "bidders": [
                {"company_name": "BETA SA", "bid_amount": 200.0, "status": "admitted", "rejection_reason": None}
            ]
        }]
    }
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(data)
    assert validator.validate(mapper.graph) is False
