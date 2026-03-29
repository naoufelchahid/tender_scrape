
from src.missing_doc_detector import extract_balised_documents
import logging

logging.basicConfig(level=logging.INFO)

def test_nested_extraction():
    content = """Start of File.

<!-- MISSING_DOC_START: administrative -->
# Regulation
Here is the regulation text.
Section 1.
<!-- MISSING_DOC_START: product -->
# Price List
Item 1: 100
Item 2: 200
<!-- MISSING_DOC_END: product -->
Section 2.
<!-- MISSING_DOC_END: administrative -->

End of File."""

    print("--- INPUT ---")
    print(content)
    print("-------------------")
    
    cleaned, docs = extract_balised_documents(content)
    
    print("\n--- EXTRACTED DOCS ---")
    for doc in docs:
        print(f"\nType: {doc.doc_type} | Filename: {doc.original_filename}")
        print("Content:")
        print(doc.content)
        print("-" * 20)
        
    print("\n--- CLEANED MARKDOWN ---")
    print(cleaned)
    
    # Assertions
    types = [d.doc_type for d in docs]
    if "product" in types and "administrative" in types:
        print("\nPASS: Both types extracted.")
    else:
        print(f"\nFAIL: Missing types. Found: {types}")
        
    # Check parent content
    admin_doc = next((d for d in docs if d.doc_type == "administrative"), None)
    if admin_doc and "# Price List" in admin_doc.content:
        print("PASS: Administrative doc contains nested Product content.")
    else:
        print("FAIL: Administrative doc missing nested content.")

    # Check cleaned markdown
    if "<!--" in cleaned:
        print("FAIL: Balises remaining in cleaned markdown.")
    else:
        print("PASS: Cleaned markdown has no balises.")

if __name__ == "__main__":
    test_nested_extraction()
