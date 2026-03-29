BASE_CONTEXT = """You are a accurate data extractor engine.
TENDER REF: {tender_ref}
DOC TYPE: {doc_type}
FILENAME: {filename}
"""

AVIS_INSTRUCTION = """TASK:
L'objectif est d'extraire le contenu textuel complet de l'avis de l'appel d'offres.
- Conservez le texte original en FRANÇAIS.
- Si le texte est uniquement en ARABE, traduisez-le intégralement en FRANÇAIS.
- Retirez systématiquement tout texte en ARABE s'il est accompagné d'une version française.
- Ne résumez pas, conservez le style administratif et technique.

METADATA TO EXTRACT:
- `objet`: return the object of the tender.
- `mode de soumission`: return "en ligne" if the tender is submitted online, else return "type of submission description".
- `mode de passation`: return "public" if the tender is public, else return "type of passation description".
- `qualifications`: return type and code of qualification required for the tender.
- `budget`: Total budget of tender or per lot (number).
- `location`: Execution location.
- `deadline`: Submission deadline or date of opening offers.
- `caution`: Caution amount (number).
- `lot_number`: return a number if there is a lot number in the document, else return "0".
- `contact`: Contact email.
- `phone`: Contact phone.
"""

AVIS_PROMPT = """{base_context}
CONTENT:
{content}

{instruction}

STRICT FORMATTING:
- Your response MUST be a valid JSON object.
- Each item in the "chunks" list MUST be an object with two keys: "content" (string) and "metadata" (object).
- NEVER include stray strings or extra commentary inside the "chunks" array.

OUTPUT JSON:
{{
  "chunks": [
    {{
      "content": "verbatim text related to these metadata",
      "metadata": {{
        "type": "avis",
        "objet": "the object of the tender",
        "mode de soumission": "en ligne",
        "mode de passation": "public",
        "qualifications": "C1",
        "budget": 120000.00,
        "location": "Rabat",
        "deadline": "2024-01-01",
        "caution": 5000.00,
        "contact": "contact@contact.com",
        "phone": "12345678",
        "lot_number": "0"
      }}
    }}
  ]
}}
"""

PRODUCT_INSTRUCTION = """TASK:
L'objectif est d'extraire la liste structurée des produits, fournitures ou services demandés.
- Identifiez chaque article avec sa désignation, quantité et unité.
- Retournez les données sous forme de dictionnaire dans le champ "metadata".
- Utilisez des clés incrémentales comme "product_1", "product_2", etc., pour chaque article trouvé.
- Incluez également 'type': 'product' dans le dictionnaire "metadata".

METADATA TO EXTRACT:
- `type`: "product"
- `product_1`, `product_2`, ...: keys for each item found.
  - `designation`: Verbatim product designation.
  - `quantity`: Quantity.
  - `unit`: Unit (e.g. unit, ml, piece, forfait, m3, m2, etc.).
  - `product header`: Any header/line describing the segment or grouping (if exists, else null)."""

PRODUCT_EXAMPLE = """
      "content": "verbatim text of the pricing table",
      "metadata": {
        "type": "product",
        "product_1": {"designation": "Item 1", "quantity": 10, "unit": "m", "product header": "Gros Oeuvres"},
        "product_2": {"designation": "Item 2", "quantity": 5, "unit": "u", "product header": null}
      }"""

PRODUCT_PROMPT = """{base_context}
CONTENT:
{content}

{instruction}

STRICT FORMATTING:
- Your response MUST be a valid JSON object.
- Each item in the "chunks" list MUST be an object with two keys: "content" (string) and "metadata" (object).
- NEVER include stray strings or extra commentary inside or outside the JSON.

OUTPUT JSON:
{{
  "chunks": [
    {{
      {example}
    }}
  ]
}}
"""
