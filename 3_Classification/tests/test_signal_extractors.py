import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.signal_extractors import AnchorExtractor, StructuralExtractor, VocabularyExtractor, FingerprintExtractor


def test_anchor_detects_specification_open():
    extractor = AnchorExtractor()
    lines = [
        "Some intro text",
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "Article 1 content here",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert signals[0]["type"] == "specification"
    assert signals[0]["role"] == "open"
    assert signals[0]["strength"] == 1.0


def test_anchor_detects_closing_marker():
    extractor = AnchorExtractor()
    lines = [
        "Some content",
        "Fait à Rabat, le 01/01/2024",
        "More text",
    ]
    signals = extractor.extract(lines)
    # "Fait à" matches closing for specification, administrative, declaration
    assert any(s["role"] == "close" and s["line_idx"] == 1 for s in signals)


def test_anchor_detects_multiple_doc_types():
    extractor = AnchorExtractor()
    lines = [
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "Content of spec",
        "Fait à Rabat, le 01/01/2024",
        "# BORDEREAU DES PRIX",
        "Pricing content",
    ]
    signals = extractor.extract(lines)
    open_signals = [s for s in signals if s["role"] == "open"]
    assert len(open_signals) == 2
    types = {s["type"] for s in open_signals}
    assert "specification" in types
    assert "product" in types


def test_anchor_detects_internal_markers():
    extractor = AnchorExtractor()
    lines = [
        "ARTICLE 3 : DESCRIPTION",
    ]
    signals = extractor.extract(lines)
    internal = [s for s in signals if s["role"] == "internal"]
    assert len(internal) >= 1
    assert internal[0]["type"] == "specification"


def test_anchor_empty_input():
    extractor = AnchorExtractor()
    signals = extractor.extract([])
    assert signals == []


def test_structural_detects_file_header():
    extractor = StructuralExtractor()
    lines = [
        "Some content",
        "# File: document.pdf",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert signals[0]["boundary_signal"] == 1.0


def test_structural_detects_page_break():
    extractor = StructuralExtractor()
    lines = [
        "Content",
        "---",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert 0.3 <= signals[0]["boundary_signal"] <= 0.5


def test_structural_detects_blank_gap():
    extractor = StructuralExtractor()
    lines = ["Content", "", "", "", "More content"]
    signals = extractor.extract(lines)
    assert len(signals) >= 1
    # Signal should be at the start of the gap
    assert signals[0]["boundary_signal"] > 0


def test_structural_detects_h1_reset():
    extractor = StructuralExtractor()
    lines = [
        "paragraph text",
        "more paragraph text",
        "# NEW SECTION TITLE",
        "content after",
    ]
    signals = extractor.extract(lines)
    h1_signals = [s for s in signals if s["line_idx"] == 2]
    assert len(h1_signals) >= 1


def test_structural_detects_page_marker():
    extractor = StructuralExtractor()
    lines = [
        "Content",
        "## Page 5",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert any(s["line_idx"] == 1 for s in signals)


def test_structural_empty_input():
    extractor = StructuralExtractor()
    assert extractor.extract([]) == []


def test_vocab_detects_shift_from_product_to_spec():
    extractor = VocabularyExtractor()
    # Build lines: 60 lines of product vocab, then 60 lines of spec vocab
    product_lines = ["prix unitaire montant total désignation quantité"] * 60
    spec_lines = ["cahier des prescriptions délai d'exécution nantissement clauses techniques"] * 60
    lines = product_lines + spec_lines
    signals = extractor.extract(lines)
    # Should detect a shift around line 60 (or as soon as spec keywords enter the window)
    shift_signals = [s for s in signals if 10 <= s["line_idx"] <= 80]
    assert len(shift_signals) >= 1
    assert shift_signals[0]["vocab_shift"] > 0


def test_vocab_no_shift_uniform_text():
    extractor = VocabularyExtractor()
    lines = ["cahier des prescriptions clauses techniques"] * 100
    signals = extractor.extract(lines)
    # No shift in uniform text
    assert len(signals) == 0


def test_vocab_empty_input():
    extractor = VocabularyExtractor()
    assert extractor.extract([]) == []


def test_vocab_short_input():
    extractor = VocabularyExtractor()
    lines = ["prix unitaire"] * 10
    signals = extractor.extract(lines)
    # Too short for meaningful window comparison
    assert len(signals) == 0


def test_fingerprint_detects_arabic_ratio():
    extractor = FingerprintExtractor()
    lines = ["Hello world"] * 50 + ["إعلان عن طلب عروض فتح الأظرفة"] * 50
    signals = extractor.extract(lines)
    # Should detect shift in Arabic ratio
    assert len(signals) >= 1
    shift = [s for s in signals if 10 <= s["line_idx"] <= 60]
    assert len(shift) >= 1


def test_fingerprint_detects_table_density():
    extractor = FingerprintExtractor()
    lines = ["Regular text paragraph"] * 50 + ["| col1 | col2 | col3 | col4 |"] * 50
    signals = extractor.extract(lines)
    assert len(signals) >= 1


def test_fingerprint_empty_input():
    extractor = FingerprintExtractor()
    assert extractor.extract([]) == []


def test_fingerprint_uniform_input():
    extractor = FingerprintExtractor()
    lines = ["Same text line"] * 100
    signals = extractor.extract(lines)
    assert len(signals) == 0
