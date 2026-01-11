"""
Centralized Prompt Definitions for Nova Extraction Container.

This module contains universal prompts that handle ALL tender document types,
eliminating the need for document-type-specific branching logic.

Stage: Extraction Container (Nova)
"""

# ============================================================================
# UNIVERSAL EXTRACTION PROMPT
# Used by nova_extractor.py for structured data extraction
# ============================================================================

UNIVERSAL_EXTRACTION_PROMPT = """You are an expert analyst specializing in Moroccan public tender documents.

Your task is to analyze the provided tender document and extract ALL relevant structured data.
The document could be ANY of the following types:
- **Avis d'Appel d'Offres** (Tender Notice/Announcement)
- **RC** (Règlement de Consultation - Administrative Regulations)
- **CPS/CCTP** (Cahier des Prescriptions Spéciales/Techniques - Technical Specifications)
- **BDP** (Bordereau des Prix - Bill of Quantities/Pricing Table)
- **Décompte** (Quantity Breakdown)
- **Administrative Documents** (CCAP, CCAG, etc.)
- **Mixed or Unknown Documents**

Your job is to intelligently determine what type of content exists and extract accordingly.

---

## LANGUAGE PRIORITY RULES

1. **PREFER FRENCH**: Always extract values in French if available in the document
2. **Arabic Fallback**: Only use Arabic if NO French text exists for that specific field
3. **Arabic Text Handling**: If you must extract Arabic, ensure it is written in correct logical order (Right-to-Left safe). Do NOT output disjointed or reversed characters

---

## EXTRACTION RULES BY CONTENT TYPE

### A. TENDER METADATA (Extract if present)

Look for general tender information:
- **tender_reference**: Format XX_YYYY_ACRONYM_ORGANIZATION (will be set externally, use placeholder if not visible)
- **buyer**: Full organization name - **MANDATORY** (e.g., "Ministère des Habous et des Affaires Islamiques")
- **location**: Execution location - City/Region/Province (e.g., "Provinces d'Al Haouz et de Marrakech")
- **global_budget**: Total estimated budget (look in CPS, RC, or Avis documents)
- **nbre_lots**: Total number of lots (if mentioned)
- **passation_mode**: Mode of procurement (e.g., "Appel d'offres ouvert au rabais ou majoration")
- **type**: Type/domain of tender (e.g., "REHABILITATION DES LIEUX D'EXERCICE DE CULTE MUSULMAN")
- **agrements**: List of required certifications (D-codes like ["D1", "D2", "D13"])
- **caution**: Caution amount (look in RC documents)
- **budget**: Estimated budget for the hole tender (look in CPS, RC, or Avis documents)

**CRITICAL RULES**:
- **buyer** field is MANDATORY - extract from any section that mentions the contracting authority
- agrements should be empty list [] if none found
- include: deadline, publication_date, buyer_initials, buyer_address, buyer_phone, buyer_email, buyer_contact, status

---

### B. LOTS (Extract if present)

**DETECTION**: Look for phrases like "Lot n°1", "LOT 1:", "Le marché est divisé en lots", etc.

For each lot found:
- **lot_number**: Use "0" for single/no lot tenders, otherwise "1", "2", etc.
- **lot_reference**: Combine {tender_ref} + lot_number (e.g., "REF_1", "REF_2")
- **title**: Full description of the lot (can be multi-line)
- **budget_lot**: Estimated budget for this specific lot

**CRITICAL LOT RULES**:
- **Ghost Lot 0**: If you find SPECIFIC lots (Lot 1, Lot 2...), DO NOT create a "Lot 0"
- **Lot 0** is ONLY for tenders with NO distinct lots (single-lot or undivided tenders)
- For single/no lot tenders: nbre_lots: 0, lot_number: "0", lot_reference: "{tender_ref}_0"
- For multi-lot tenders: nbre_lots: N, lot_number: "1", "2", ..., "N"

---

### C. PRODUCTS (Extract if present)

**DETECTION**: Look for pricing tables, "Bordereau des Prix", "Sous-détail des Prix", columns like "Désignation", "Quantité", "Unité", "Prix"

For each product/service row in the pricing table:
- **designation**: FULL, EXACT text of the product/service description (do NOT summarize)
- **unit**: Measurement unit (m2, kg, u, Ens, Forfait, etc.)
- **quantity**: Required quantity (number)
- **estimated_price**: Unit price if available
- **lot_number**: Which lot this belongs to (use "0" if single lot)

**CRITICAL PRODUCT RULES**:
- **ONE ROW = ONE PRODUCT**: Create a separate product object for EVERY meaningful table row
- **DO NOT MERGE** multiple distinct items into one product
- **DO NOT SPLIT** a single item's multi-line description into separate products
- **PRESERVE EXACT TEXT**: Include all technical specs, dimensions, references, norms
- **IGNORE**: Page numbers, headers/footers, subtotal/total rows
- **MANDATORY**: You MUST extract at least one product if a pricing table exists

---

### D. TECHNICAL SPECIFICATIONS (Note for reference)

If the document contains technical specifications (CPS/CCTP articles), note that these will be handled separately by the chunking system. Focus on metadata and products here.

---

## OUTPUT FORMAT

Return ONLY valid JSON matching this EXACT structure:

```json
{
  "tender_info": {
    "tender_reference": "01_2026_EXAMPLE_ORG",
    "location": "City/Province or null",
    "global_budget": 1000000.0 or null,
    "nbre_lots": 0,
    "buyer": "Organization Name",
    "passation_mode": "Appel d'offres ouvert" or null,
    "type": "Project Type" or null,
    "agrements": []
    "caution": 100000.0 or null,
    "budget": 1000000.0 or null,
  },
  "lots": [
    {
      "lot_number": "0",
      "lot_reference": "REF_0",
      "title": "Description",
      "budget_lot": 500000.0 or null
    }
  ],
  "products": [
    {
      "designation": "Full product description...",
      "unit": "m2",
      "quantity": 100.0,
      "estimated_price": 50.0 or null,
      "lot_number": "0"
    }
  ]
}
```

**IMPORTANT**:
- If a field is not found, use `null` (except `agrements` which should be `[]`)
- Return ONLY JSON, no explanations or markdown
- Ensure all text fields are in FRENCH unless only Arabic is available
- buyer field MUST have a value (cannot be null)
- If no lots exist, include one lot with lot_number="0"

"""


# ============================================================================
# UNIVERSAL CHUNKING PROMPT
# Used by llm_chunker.py for intelligent document segmentation
# ============================================================================

def get_universal_chunking_prompt(content: str) -> str:
    """
    Generate universal chunking prompt for any tender document type.
    
    Args:
        content: Document content to chunk
        
    Returns:
        Complete prompt string with instructions
    """
    return f"""You are an expert document analyst specializing in Moroccan public tender documents.

Your task is to intelligently segment the provided document into semantically meaningful chunks with proper metadata.

The document could be ANY of these types:
- **BDP** (Bordereau des Prix - Pricing Table)
- **CPS/CCTP** (Technical Specifications)
- **RC/CCAP** (Administrative Regulations)
- **Avis** (Tender Notice)
- **Mixed or Unknown Documents**

Analyze the content and apply the appropriate segmentation strategy based on what you find.

---

## DOCUMENT CONTENT

{content}

---

## SEGMENTATION STRATEGIES BY CONTENT TYPE

### STRATEGY 1: PRICING TABLES (BDP, Décompte)

**DETECTION**: Look for tables with columns like Désignation, Quantité, Unité, Prix

**RULES**:
- **ONE ITEM = ONE CHUNK**: Create a separate chunk for EVERY meaningful row in the pricing table
- **DO NOT MERGE** multiple distinct items
- **DO NOT SPLIT** a single item's multi-line description
- **PRESERVE EXACT TEXT**: Include all technical specs, dimensions, references, norms
- **EXTRACT ATTRIBUTES**:
  - `lot`: Lot number this item belongs to (look for headers like "LOT n°1")
  - `item_number`: Item number in table
  - `designation`: Short description (for metadata)
  - `quantity`: Quantity value
  - `unit`: Unit of measurement

**OUTPUT FORMAT**:
```
<!-- CHUNK:products:item_ID lot="LOT_NUM" designation="SHORT_DESC" quantity="QTY" unit="UNIT" -->
[FULL ORIGINAL ROW CONTENT / DESCRIPTION]
<!-- /CHUNK -->
```

**EXAMPLE**:
```
<!-- CHUNK:products:1.2_server lot="1" designation="Serveur Rackable" quantity="2" unit="U" -->
Item 1.2: Serveur de base de données
Proc: 2x Intel Xeon Gold, 64GB RAM, 2x 480GB SSD RAID 1.
Alimentation redondante. Garantie 3 ans sur site.
<!-- /CHUNK -->
```

---

### STRATEGY 2: TECHNICAL SPECIFICATIONS (CPS, CCTP)

**DETECTION**: Look for articles, sections describing technical requirements, norms, methodologies

**RULES**:
- **Article-Level Chunking**: Treat each "ARTICLE" or major "SECTION" as ONE chunk
- **NEVER MERGE** distinct articles
- **NEVER SPLIT** a single logical article (unless >2000 words)
- **PRESERVE FULL TEXT**: Do not summarize

**CLASSIFICATION** (use metadata `type`):
- `products_specs`: Sections describing SPECIFIC technical requirements for materials/equipment (e.g., "Spécifications du Béton", "Caractéristiques des PC")
- `general_technical_specs`: Sections describing execution norms, standards, methodology, quality control, site organization
- `products`: If you find an EMBEDDED PRICING TABLE within the text, extract rows like Strategy 1

**OUTPUT FORMAT**:
```
<!-- CHUNK:TYPE:Article_ID type="TYPE" title="ARTICLE_TITLE" -->
[FULL TEXT OF THE ARTICLE]
<!-- /CHUNK -->
```

**EXAMPLE**:
```
<!-- CHUNK:products_specs:art_5 type="products_specs" title="Article 5: Menuiserie Aluminium" -->
ARTICLE 5 : MENUISERIE ALUMINIUM
L'aluminium sera de type 6063 T5, classe A selon NF P 24-351...
[Rest of text]
<!-- /CHUNK -->
```

---

### STRATEGY 3: ADMINISTRATIVE DOCUMENTS (RC, CCAP, CCAG)

**DETECTION**: Look for administrative clauses, eligibility criteria, guarantees, legal requirements

**RULES**:
- **Article-Level Chunking**: One Article/Clause = One Chunk
- **Type**: Always use `administrativ_specs`
- **Key Sections to Isolate**:
  - Objet de l'appel d'offres
  - Cautionnement / Garanties (Provisoire, Définitive)
  - Critères d'admissibilité / Jugement
  - Modèle de déclaration / Engagement

**OUTPUT FORMAT**:
```
<!-- CHUNK:administrativ_specs:Article_ID type="administrativ_specs" title="ARTICLE_TITLE" -->
[FULL TEXT OF THE CLAUSE]
<!-- /CHUNK -->
```

**EXAMPLE**:
```
<!-- CHUNK:administrativ_specs:caution type="administrativ_specs" title="Cautionnement Provisoire" -->
ARTICLE 4 : CAUTIONNEMENT PROVISOIRE
Le montant du cautionnement provisoire est fixé à 2% du montant estimé...
<!-- /CHUNK -->
```

---

### STRATEGY 4: TENDER NOTICES (Avis)

**DETECTION**: Look for tender announcement, summary information, dates, submission details

**RULES**:
- Create a SINGLE comprehensive chunk containing the full notice
- Capture key info: Client, Budget, Cautionnement, Deadline, Submission address

**OUTPUT FORMAT**:
```
<!-- CHUNK:general_technical_specs:summary type="general_technical_specs" title="Avis Summary" -->
[FULL TEXT OF THE NOTICE]
<!-- /CHUNK -->
```

---

### STRATEGY 5: UNKNOWN / MIXED DOCUMENTS

**DETECTION**: If the document doesn't clearly fit the above categories

**RULES**:
- Segment into logical sections (Chapters/Articles)
- Use `general_technical_specs` as type
- Preserve semantic coherence

**OUTPUT FORMAT**:
```
<!-- CHUNK:general_technical_specs:Section_ID type="general_technical_specs" title="SECTION_TITLE" -->
[SECTION CONTENT]
<!-- /CHUNK -->
```

---

## GENERAL RULES

1. **LANGUAGE**: Extract descriptions in FRENCH if available. Use Arabic only if no French exists.
2. **IGNORE**: Page numbers, running headers/footers, table of contents
3. **CONTENT PRESERVATION**: Copy exact text, do NOT summarize or paraphrase
4. **MINIMUM CHUNK SIZE**: Skip chunks with <10 characters
5. **LOT HANDLING**: 
   - Extract lot numbers from headers/context
   - Use lot="0" for single-lot items
   - Use lot="1", lot="2", etc. for multi-lot items

---

## OUTPUT REQUIREMENTS

- Wrap EVERY chunk with `<!-- CHUNK:...:... -->` and `<!-- /CHUNK -->`
- Include appropriate metadata attributes
- Return ALL chunks in the response
- No explanations or additional text outside chunk markers
"""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_extraction_prompt() -> str:
    """
    Get the universal extraction prompt for nova_extractor.py
    
    Returns:
        Complete extraction prompt
    """
    return UNIVERSAL_EXTRACTION_PROMPT


def get_chunking_prompt(content: str) -> str:
    """
    Get the universal chunking prompt for llm_chunker.py
    
    Args:
        content: Document content to chunk
        
    Returns:
        Complete chunking prompt with content embedded
    """
    return get_universal_chunking_prompt(content)
