import sys
import os

# Add local directory to path to find src module
sys.path.append(os.getcwd())

from src.bdp_extractor import identify_and_tag_french_boq

def test_bdp_tagging():
    print("Testing BDP tagging...")
    
    markdown_sample = """
# Some generic table

| Name | Age | City |
|------|-----|------|
| Alice| 30  | Paris|
| Bob  | 25  | Lyon |

# Bill of Quantities

| N° | Désignation              | Unité | Quantité | Prix Unitaire | Montant |
|----|--------------------------|-------|----------|---------------|---------|
| 1  | Excavation               | m3    | 100      | 50            | 5000    |
| 2  | Beton                    | m3    | 20       | 800           | 16000   |

# Another section
Text here.
"""

    tagged_output = identify_and_tag_french_boq(markdown_sample)
    
    print("\n--- Original ---")
    print(markdown_sample)
    print("\n--- Tagged Output ---")
    print(tagged_output)
    
    # Assertions
    if "<!-- BDP_START -->" in tagged_output and "<!-- BDP_END -->" in tagged_output:
        print("\n✅ Verification PASSED: BDP tags found.")
    else:
        print("\n❌ Verification FAILED: BDP tags NOT found.")

    if "| Name |" in tagged_output and "<!-- BDP_START -->| Name |" in tagged_output.replace("\n", ""):
         print("❌ Verification FAILED: Generic table incorrectly tagged.")
    else:
         print("✅ Verification PASSED: Generic table not tagged.")

if __name__ == "__main__":
    try:
        import markdown_it
        test_bdp_tagging()
    except ImportError:
        print("❌ markdown-it-py not installed. Cannot run verification.")
        print("Please run: pip install markdown-it-py")
