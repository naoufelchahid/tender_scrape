
import logging
import sys
from unittest.mock import MagicMock
from src.classifier import DocumentClassifier, ClassificationResult
from src.segmentation_engine import SegmentationEngine, Segment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_classifier_refactoring():
    """Verify that the refactored classifier still correctly identifies document types."""
    classifier = DocumentClassifier()
    
    # Test cases: (filename, content, expected_type)
    test_cases = [
        ("CPS_Project_X.pdf", "Cahier des prescriptions spéciales pour le projet X", "specification"),
        ("RC_Tender.pdf", "Règlement de consultation pour l'appel d'offres", "administrative"),
        ("BDP_Estimatif.xlsx", "Bordereau des prix et détail estimatif", "product"),
        ("Acte_engagement.pdf", "Acte d'engagement pour la prestation", "acte_engagement"),
        ("Declaration_honneur.pdf", "Déclaration sur l'honneur du concurrent", "declaration"),
    ]
    
    for filename, content, expected_type in test_cases:
        result = classifier.classify(filename, content)
        logger.info(f"Test: {filename} -> {result.doc_type} (expected: {expected_type})")
        assert result.doc_type == expected_type, f"Failed for {filename}: expected {expected_type}, got {result.doc_type}"

def test_segmentation_engine_smoke():
    """Verify that the segmentation engine can split a mixed text."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    
    text = (
        "# CAHIER DES PRESCRIPTIONS SPECIALES\n"
        + "Article 1: Objet\n"
        + "Cahier des prescriptions spéciales pour le projet X clauses techniques nantissement\n" * 50
        + "\n---\n"
        + "# BORDEREAU DES PRIX\n"
        + "| désignation | unité | quantité | prix unitaire | montant |\n" * 50
    )
    
    segments = engine.segment_and_classify(text, classifier)
    
    logger.info(f"Segmentation smoke test: produced {len(segments)} segments")
    for seg in segments:
        logger.info(f"  Segment: {seg.doc_type} (conf={seg.confidence:.2f}, method={seg.method})")
    
    assert len(segments) >= 2
    types = {s.doc_type for s in segments}
    assert "specification" in types
    assert "product" in types

def test_decompose_integration():
    """Verify that decompose is called and its output is used."""
    # Create a mock function that simulates decompose_text
    mock_decompose_func = MagicMock()
    # It must return a dict with a 'units' list, each unit has 'text'
    mock_decompose_func.return_value = {
        "units": [
            {"text": "Cahier des charges"},
            {"text": "spéciales pour le projet"}
        ],
        "meta": {"total_units": 2}
    }
    
    # Initialize classifier with our mock function
    classifier = DocumentClassifier(decomposer_func=mock_decompose_func)
    
    filename = "CPS_Document.pdf"
    content = "Raw noisy content with headers and footers"
    
    result = classifier.classify(filename, content)
    
    # Verify decompose function was called with content
    mock_decompose_func.assert_called_once()
    
    # Verify that the classification succeeded using the "cleaned" content
    # "Cahier des charges" should trigger Step 1 Specification
    logger.info(f"Decompose Result: {result.doc_type} (confidence: {result.confidence})")
    assert result.doc_type == "specification", f"Decompose integration failed: expected specification, got {result.doc_type}"
    assert result.step == 1, f"Expected classification at step 1, got step {result.step}"
    
    logger.info("Decompose integration test passed: decomposer was called and result was correct.")

if __name__ == "__main__":
    try:
        logger.info("Running smoke tests...")
        test_classifier_refactoring()
        test_segmentation_engine_smoke()
        test_decompose_integration()
        logger.info("All smoke tests passed!")
    except Exception as e:
        logger.error(f"Smoke tests failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
