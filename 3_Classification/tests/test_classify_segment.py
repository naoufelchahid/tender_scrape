import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.classifier import DocumentClassifier, ClassificationResult


def test_classify_segment_hint_agrees_with_step1():
    """When hint and Step 1 agree, skip LLM, return high confidence."""
    classifier = DocumentClassifier()
    # Content must be > 3000 chars to hit Specification check in Step 2 if filename doesn't match
    content = "cahier des prescriptions spéciales clauses techniques nantissement délai d'exécution " * 100
    result = classifier.classify_segment(content, hint_type="specification", hint_strength=0.9)
    assert result.doc_type == "specification"
    assert result.step in (1, 2)


def test_classify_segment_strong_hint_overrides_unknown():
    """Strong hint should be used when Steps 1-2 return unknown."""
    classifier = DocumentClassifier()
    # Content with no clear patterns
    content = "Lorem ipsum dolor sit amet " * 20
    result = classifier.classify_segment(content, hint_type="administrative", hint_strength=0.9)
    assert result.doc_type == "administrative"
    assert result.confidence == "hint"


def test_classify_segment_no_hint():
    """Without hint, behaves like standard classify."""
    classifier = DocumentClassifier()
    content = "bordereau des prix détail estimatif désignation prix unitaire montant quantité"
    result = classifier.classify_segment(content, hint_type=None, hint_strength=0.0)
    assert result.doc_type == "product"


def test_classify_segment_weak_hint_defers_to_classifier():
    """Weak hint should not override classifier result."""
    classifier = DocumentClassifier()
    content = "bordereau des prix détail estimatif désignation prix unitaire montant quantité"
    result = classifier.classify_segment(content, hint_type="specification", hint_strength=0.3)
    # Classifier should find "product" from content, overriding weak hint
    assert result.doc_type == "product"


def test_classify_segment_smart_sampling_with_anchor():
    """When anchor_offset is provided, sampling starts from there."""
    classifier = DocumentClassifier()
    # Junk for first 6000 chars, then spec content
    junk = "x " * 3000
    spec_content = "cahier des prescriptions spéciales nantissement clauses techniques délai d'exécution"
    content = junk + spec_content
    # Without anchor_offset, Step 2 samples first 5000 chars (all junk)
    result_no_offset = classifier.classify_segment(content, hint_type=None, hint_strength=0.0)
    # With anchor_offset pointing to spec content
    result_with_offset = classifier.classify_segment(
        content, hint_type="specification", hint_strength=0.5, anchor_offset=6000
    )
    # The offset version should find specification
    assert result_with_offset.doc_type == "specification"
