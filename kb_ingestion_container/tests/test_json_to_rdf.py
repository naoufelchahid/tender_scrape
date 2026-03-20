import pytest
from rdflib import RDF, RDFS, XSD, Literal
from src.json_to_rdf import JsonToRdfMapper
from src.models import AvisMetadata, ProductChunkMetadata
from src.uri_builder import TS

def test_map_avis():
    mapper = JsonToRdfMapper("AO_TEST_001")
    metadata = AvisMetadata(
        objet="Test Tender Object",
        budget=1000000.50,
        contact="The Big Buyer",
        location="Casablanca"
    )
    
    mapper.map_avis(metadata)
    g = mapper.graph
    
    # Check Tender
    tender = mapper.tender_uri
    assert (tender, RDF.type, TS.Tenders) in g
    assert (tender, TS.Has_Object, Literal("Test Tender Object", datatype=XSD.string)) in g
    assert (tender, TS.Has_Budget, Literal(1000000.50, datatype=XSD.float)) in g
    
    # Check Buyer
    buyer = next(g.objects(tender, TS.Launched_by))
    assert (buyer, RDF.type, TS.Buyers) in g
    assert (buyer, RDFS.label, Literal("The Big Buyer", datatype=XSD.string)) in g

def test_map_products():
    mapper = JsonToRdfMapper("AO_TEST_002")
    products = [
        ProductChunkMetadata(designation="Product A", quantity=10, unit="unit"),
        ProductChunkMetadata(designation="Product B", quantity=5.5, unit="kg")
    ]
    
    mapper.map_products(products)
    g = mapper.graph
    
    # Check Bordereau
    bordereau = next(g.objects(mapper.tender_uri, TS.Has_Bordereau))
    assert (bordereau, RDF.type, TS.Bordereaux) in g
    
    # Check Articles
    articles = list(g.objects(bordereau, TS.Has_Article))
    assert len(articles) == 2
    
    # Verify values for one article
    art_a = [a for a in articles if (a, TS.Has_Designation, Literal("Product A", datatype=XSD.string)) in g][0]
    assert (art_a, TS.Has_quantity, Literal(10.0, datatype=XSD.float)) in g
