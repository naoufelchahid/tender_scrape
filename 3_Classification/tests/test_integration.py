"""Integration tests for the full segmentation pipeline as used by main.py."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.segmentation_engine import SegmentationEngine, Segment
from src.classifier import DocumentClassifier


def _build_mixed_tender():
    """Build a realistic mixed tender markdown."""
    parts = []
    # Avis section
    parts.append("# AVIS D'APPEL D'OFFRES OUVERT")
    parts.extend(["Il sera procédé le 15/03/2026 à l'ouverture des plis"] * 5)
    parts.append("Fait à Rabat, le 01/03/2026")
    parts.append("")
    parts.append("---")
    parts.append("")
    # CPS section
    parts.append("# CAHIER DES PRESCRIPTIONS SPECIALES")
    parts.extend([
        "ARTICLE 1 : OBJET DU MARCHE",
        "Le présent cahier des prescriptions spéciales a pour objet...",
        "clauses techniques applicables nantissement délai d'exécution",
    ] * 20)
    parts.append("Fait à Casablanca, le 10/03/2026")
    parts.append("")
    parts.append("---")
    parts.append("")
    # BDP section
    parts.append("# BORDEREAU DES PRIX - DETAIL ESTIMATIF")
    parts.extend(["| désignation | unité | quantité | prix unitaire | montant |"] * 25)
    parts.append("Arrêté le présent bordereau")
    return "\n".join(parts)


def test_full_pipeline_mixed_tender():
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = _build_mixed_tender()
    segments = engine.segment_and_classify(text, classifier)

    types = {s.doc_type for s in segments}
    # Should find at least 2 of the 3 document types
    expected = {"avis_fr", "specification", "product"}
    assert len(types & expected) >= 2, f"Found types: {types}"


def test_single_document_tender():
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = "\n".join([
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "clauses techniques nantissement délai d'exécution",
    ] * 50)
    segments = engine.segment_and_classify(text, classifier)
    assert len(segments) == 1
    assert segments[0].doc_type == "specification"


def test_file_header_format():
    """Backward compat: # File: headers should still work."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = (
        "# File: cps.pdf\n"
        + "cahier des prescriptions nantissement clauses techniques délai d'exécution\n" * 40
        + "\n---\n"
        + "# File: bdp.pdf\n"
        + "| désignation | unité | quantité | prix unitaire | montant |\n" * 40
    )
    segments = engine.segment_and_classify(text, classifier)
    assert len(segments) >= 2


def test_segments_to_logical_docs():
    """Verify segments can replace LogicalDocument for downstream use."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = _build_mixed_tender()
    segments = engine.segment_and_classify(text, classifier)

    for seg in segments:
        assert isinstance(seg.content, str)
        assert len(seg.content) > 0
        assert seg.doc_type != ""
        assert seg.start_line >= 0
        assert seg.end_line > seg.start_line
