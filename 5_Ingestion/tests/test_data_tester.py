import pytest
import os
from rdflib import Graph, Literal, RDF, XSD, URIRef
from src.data_tester import DataTester
from src.uri_builder import TS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONTOLOGY_PATH = os.path.join(BASE_DIR, "..", "ontology_SHACL", "tender_structure_final.owl")
ENRICHMENT_SHAPES_PATH = os.path.join(BASE_DIR, "ontology", "shapes_enrichment.ttl")


@pytest.fixture
def tester():
    return DataTester(ONTOLOGY_PATH, ENRICHMENT_SHAPES_PATH)


def _make_valid_bordereau(g: Graph, tender: URIRef, bordereau: URIRef, article: URIRef):
    """Helper: build a minimal valid enrichment subgraph."""
    g.add((bordereau, RDF.type, TS.Bordereaux))
    g.add((bordereau, TS.Is_Bordereau_of, tender))
    g.add((bordereau, TS.Has_Article, article))
    g.add((article, RDF.type, TS.Articles))
    g.add((article, TS.Has_Designation, Literal("Test Article", datatype=XSD.string)))
    g.add((article, TS.Is_Article_of, bordereau))


def test_valid_enrichment_graph(tester):
    """A bordereau with articles and proper designations passes all checks."""
    g = Graph()
    tender = TS.Tender_A
    bordereau = TS.Bordereau_A
    article = TS.Article_A
    _make_valid_bordereau(g, tender, bordereau, article)
    assert tester.test_tender_graph(g) is True


def test_bordereau_missing_articles_shacl(tester):
    """A Bordereaux node with no Has_Article fails SHACL."""
    g = Graph()
    bordereau = TS.Bordereau_Empty
    g.add((bordereau, RDF.type, TS.Bordereaux))
    g.add((bordereau, TS.Is_Bordereau_of, TS.Tender_X))
    assert tester.test_tender_graph(g) is False


def test_article_missing_designation_shacl(tester):
    """An Articles node without Has_Designation fails SHACL."""
    g = Graph()
    tender = TS.Tender_B
    bordereau = TS.Bordereau_B
    article = TS.Article_NoDesig
    g.add((bordereau, RDF.type, TS.Bordereaux))
    g.add((bordereau, TS.Is_Bordereau_of, tender))
    g.add((bordereau, TS.Has_Article, article))
    g.add((article, RDF.type, TS.Articles))
    g.add((article, TS.Is_Article_of, bordereau))
    # No Has_Designation
    assert tester.test_tender_graph(g) is False


def test_bordereau_missing_articles_logical(tester):
    """Logical consistency check also catches a Bordereau with no Articles."""
    g = Graph()
    bordereau = TS.Bordereau_NoArticles
    g.add((bordereau, RDF.type, TS.Bordereaux))
    g.add((bordereau, TS.Is_Bordereau_of, TS.Tender_Y))
    assert tester.test_tender_graph(g) is False


def test_empty_enrichment_graph_passes(tester):
    """An empty enrichment graph (avis-only, no bordereau) passes — nothing to validate."""
    g = Graph()
    # e.g. only supplemental tender properties, no Bordereaux/Articles present
    g.add((TS.Tender_Z, TS.Has_Budget, Literal(50000.0, datatype=XSD.float)))
    assert tester.test_tender_graph(g) is True
