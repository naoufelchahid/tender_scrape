import pytest
from rdflib import RDF, RDFS, XSD, Literal
from rdf_mapper import ResultRdfMapper
from uri_builder import TS


SAMPLE_EXTRACTED = {
    "lots": [
        {
            "lot_reference": "0",
            "winner": {
                "company_name": "ATLAS SARL",
                "winning_amount": 1234567.89
            },
            "bidders": [
                {
                    "company_name": "BETA SA",
                    "bid_amount": 2345678.90,
                    "status": "admitted",
                    "rejection_reason": None
                },
                {
                    "company_name": "GAMMA SARL AU",
                    "bid_amount": 999999.00,
                    "status": "rejected",
                    "rejection_reason": "Dossier incomplet"
                }
            ]
        }
    ]
}


def test_map_creates_result_node():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    assert len(results) == 1


def test_map_links_tender_to_result():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    from rdflib import URIRef
    tender_uri = URIRef("http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    opened = list(g.objects(tender_uri, TS.Is_Opened))
    assert len(opened) == 1


def test_map_creates_winner_bid():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    result_uri = results[0]
    winner_bids = list(g.objects(result_uri, TS.Is_Winner_Bid))
    assert len(winner_bids) == 1
    # Winner bid has amount
    amount = g.value(winner_bids[0], TS.Has_Bid_Amount)
    assert float(amount) == pytest.approx(1234567.89)


def test_map_creates_other_bids():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    all_bids = list(g.subjects(RDF.type, TS.TenderBids))
    # 1 winner + 2 other bidders = 3 total
    assert len(all_bids) == 3


def test_map_rejected_bid_has_rejected_link():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    result_uri = results[0]
    rejected = list(g.objects(result_uri, TS.Rejected_Bid))
    assert len(rejected) == 1


def test_map_contractor_nodes():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    contractors = list(g.subjects(RDF.type, TS.Contractor))
    assert len(contractors) == 3  # ATLAS, BETA, GAMMA


def test_map_has_pv():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    pv = g.value(results[0], TS.Has_PV)
    assert pv == Literal(True, datatype=XSD.boolean)


def test_get_ntriples():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    nt = mapper.get_ntriples()
    assert "TenderResults" in nt
    assert "TenderBids" in nt
    assert "Contractor" in nt


def test_get_is_result_triple():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    nt = mapper.get_is_result_triple()
    assert "Is_Result" in nt
    assert '"true"' in nt


def test_map_multi_lot():
    data = {
        "lots": [
            {
                "lot_reference": "003_2026_SRMCS_1",
                "winner": {"company_name": "A SARL", "winning_amount": 100.0},
                "bidders": []
            },
            {
                "lot_reference": "003_2026_SRMCS_2",
                "winner": {"company_name": "B SA", "winning_amount": 200.0},
                "bidders": []
            }
        ]
    }
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(data)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    assert len(results) == 2
