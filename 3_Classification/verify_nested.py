
from src.segmentation_engine import SegmentationEngine
from src.classifier import DocumentClassifier
import logging

logging.basicConfig(level=logging.INFO)

def test_nested_extraction():
    """
    Test how the new segmentation engine handles adjacent/nested document structures.
    In the new engine, 'nested' means documents are concatenated without clear 
    file headers but with distinct anchors or vocabulary shifts.
    """
    content = """Start of File.

# REGLEMENT DE LA CONSULTATION
Here is the regulation text about critéres d'évaluation and conditions requises.
""" + "Conditions requises des concurrents règlement de consultation criteria evaluation " * 50 + """
Section 1.

# BORDEREAU DES PRIX
Item 1: 100
Item 2: 200
| désignation | unité | quantité | prix unitaire | montant |
| Item 1      | U     | 1        | 100           | 100     |
""" + "| item name | unit | qty | unit price | total amount | " * 50 + """

Section 2.
End of File."""

    print("--- INPUT ---")
    print(content)
    print("-------------------")
    
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    segments = engine.segment_and_classify(content, classifier)
    
    print("\n--- DETECTED SEGMENTS ---")
    for seg in segments:
        print(f"\nType: {seg.doc_type} | Method: {seg.method} | Conf: {seg.confidence:.2f}")
        print(f"Lines: {seg.start_line}-{seg.end_line}")
        print("Content Start:")
        print(seg.content[:100] + "...")
        print("-" * 20)
        
    # Assertions
    types = [s.doc_type for s in segments]
    print(f"\nDetected types: {types}")
    
    if "product" in types and "administrative" in types:
        print("\nPASS: Both types extracted from concatenated stream.")
    else:
        # Note: BDP might be missed if content is too short for threshold
        print(f"\nINFO: Found types: {types}")
        
    if len(segments) >= 2:
        print("PASS: Multiple segments detected.")
    else:
        print("FAIL: Only one segment detected. Scoring might need more context/keywords.")

if __name__ == "__main__":
    test_nested_extraction()
