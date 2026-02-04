BASE_CONTEXT = """You are a STRICT TEXT SEGMENTATION ENGINE.
TENDER REF: {tender_ref}
DOC TYPE: {doc_type}
FILENAME: {filename}

CRITICAL RULES:
1. **NO LOSS**: The "content" field in your output JSON must contain the EXACT, VERBATIM text from the source.
2. **NO SUMMARIZATION**: Do not summarize, paraphrase or truncate the text.
3. **NO MODIFICATION**: Do not modify the text in any way.
4. **NO ADDITION**: Do not add any text that is not present in the source.
5. **NO REMOVAL**: Do not remove any text that is present in the source.  

"""

AVIS_INSTRUCTION = """TASK:
Return the document as ONE single chunk. Content must be STRICTLY IDENTICAL to input.
Extract metadata fields from the text. if there is other tenders informations in the document, ignore them, extract only the informations of the tender we are processing. 

- `lot_number`: return a number if there is a lot number in the document, else return "0".

METADATA TO EXTRACT:
- `budget`: Total budget (number).
- `location`: Execution location.
- `deadline`: Submission deadline.
- `caution`: Caution amount (number).
- `lot_number`: return a number if there is a lot number in the document, else return "0".
"""

AVIS_PROMPT = """{base_context}
CONTENT:
{content}

{instruction}

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "FULL VERBATIM CONTENT HERE...",
      "metadata": {{
        "type": "avis",
        "budget": 120000.00,
        "location": "Rabat",
        "deadline": "2024-01-01",
        "caution": 5000.00,
        "lot_number": "0"
      }}
    }}
  ]
}}
"""

PRODUCT_INSTRUCTION = """TASK:
Extract structured data from the PRICING TABLE embedded in the text.
Create **ONE SINGLE CHUNK** containing the raw content.
In the metadata, create a dictionary of ALL products found.

METADATA TO EXTRACT:
- `type`: "product"
- `product_1`, `product_2`, ...: keys for each item found.
  - `designation`: Verbatim product designation.
  - `quantity`: Quantity.
  - `unit`: Unit.
  - `product_header`: Any header describing the product grouping (if exists, else null)."""

PRODUCT_EXAMPLE = """ "metadata": {
    "type": "product",
    "product_1": {"designation": "Item 1", "quantity": 10, "unit": "m", "product_header": "Gros Oeuvres"},
    "product_2": {"designation": "Item 2", "quantity": 5, "unit": "u", "product_header": null}
  }"""

PRODUCT_PROMPT = """{base_context}
CONTENT:
{content}

{instruction}

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "FULL RAW CONTENT...",
      {example}
    }}
  ]
}}
"""
