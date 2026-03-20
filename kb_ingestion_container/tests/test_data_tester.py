import pytest
import os
from rdflib import Graph, Literal, RDF, XSD
from src.data_tester import DataTester
from src.uri_builder import TS

# Dynamic paths to the bundled ontology files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONTOLOGY_PATH = os.path.join(BASE_DIR, "ontology", "tender_structure.ttl")
SHACL_PATH = os.path.join(BASE_DIR, "ontology", "shapes.ttl")

@pytest.fixture
def tester():
    return DataTester(ONTOLOGY_PATH, SHACL_PATH)

def test_passed_validation(tester):
    g = Graph()
    tender = TS.Tender_A
    g.add((tender, RDF.type, TS.Tenders))
    g.add((tender, TS.Has_Object, Literal("Valid Project", datatype=XSD.string)))
    g.add((tender, TS.Has_Budget, Literal(100.0, datatype=XSD.float)))
    
    buyer = TS.Buyer_A
    g.add((buyer, RDF.type, TS.Buyers))
    g.add((tender, TS.Launched_by, buyer))
    
    assert tester.test_tender_graph(g) is True

def test_failed_logic_negative_budget(tester):
    g = Graph()
    tender = TS.Tender_B
    g.add((tender, RDF.type, TS.Tenders))
    g.add((tender, TS.Has_Object, Literal("Invalid Project", datatype=XSD.string)))
    g.add((tender, TS.Has_Budget, Literal(-10.0, datatype=XSD.float))) # Negative!
    
    buyer = TS.Buyer_B
    g.add((buyer, RDF.type, TS.Buyers))
    g.add((tender, TS.Launched_by, buyer))
    
    # tester.test_tender_graph should return False due to negative budget check
    assert tester.test_tender_graph(g) is False

def test_failed_logic_missing_buyer(tester):
    g = Graph()
    tender = TS.Tender_C
    g.add((tender, RDF.type, TS.Tenders))
    g.add((tender, TS.Has_Object, Literal("Missing Buyer", datatype=XSD.string)))
    g.add((tender, TS.Has_Budget, Literal(100.0, datatype=XSD.float)))
    
    # Missing Launched_by link
    assert tester.test_tender_graph(g) is False
