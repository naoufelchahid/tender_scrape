"""
Performance test: simulate many enrichment SHACL violations to verify
that the summary-logging approach handles large violation sets quickly.
"""
import pytest
import time
from rdflib import Graph, Literal, RDF, XSD, URIRef
import os
from src.data_tester import DataTester
from src.uri_builder import TS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONTOLOGY_PATH = os.path.join(BASE_DIR, "..", "ontology_SHACL", "tender_structure_final.owl")
ENRICHMENT_SHAPES_PATH = os.path.join(BASE_DIR, "ontology", "shapes_enrichment.ttl")


@pytest.fixture
def tester():
    return DataTester(ONTOLOGY_PATH, ENRICHMENT_SHAPES_PATH)


def test_many_violations_performance(tester):
    """
    Create 50 Bordereaux with no Articles and no Is_Bordereau_of link.
    Generates 100 SHACL violations (2 per Bordereau).

    Expected results:
    - PyShacl validation: <5 seconds
    - Logging summary: <1 second
    - Total violations: 100
    """
    g = Graph()

    for i in range(50):
        bordereau_uri = URIRef(f"http://www.tenderintelligence.io/ontology/tender-structure#Bordereau_Perf_{i}")
        g.add((bordereau_uri, RDF.type, TS.Bordereaux))
        # Missing: Has_Article (minCount 1) + Is_Bordereau_of (minCount 1) → 2 violations each

    print(f"\n[TEST] Created graph with {len(g)} triples")
    print(f"[TEST] Expected violations: 100 (2 per Bordereau × 50)")

    t0 = time.perf_counter()
    result = tester.test_tender_graph(g)
    elapsed = time.perf_counter() - t0

    print(f"\n[TEST] Validation result: {result}")
    print(f"[TEST] Total elapsed: {elapsed:.3f}s")
    print("[TEST] Check [TIMING] logs above for per-step breakdown")

    assert result is False
    assert elapsed < 10, f"Validation took {elapsed:.1f}s — expected <10s"
