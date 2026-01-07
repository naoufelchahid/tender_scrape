    def _create_metadata_prompt(self, doc_type: str) -> str:
        """Create prompt for metadata extraction."""
        return f"""Analyze the tender document images/text and extract structured metadata.

Document Type: {doc_type}

Extract the following information:

1. **Tender Info**:
   - tender_reference: Format as XX_YYYY_ACRONYM_ORGANIZATION (e.g., "01_2026_DAMPS_MDT_DELM_DIRAPPMEDPROSAN")
   - buyer: Full organization name - MANDATORY (e.g., "Ministère des Habous et des Affaires Islamiques")
   - location: Execution location - City/Region/Province (e.g., "Provinces d'Al Haouz et de Marrakech")
   - global_budget: Total estimated budget (look in CPS or RC documents)
   - nbre_lots: Total number of lots (if mentioned)
   - passation_mode: Mode of procurement (e.g., "Appel d'offres ouvert au rabais ou majoration")
   - type: Type/domain of tender (e.g., "REHABILITATION DES LIEUX D'EXERCICE DE CULTE MUSULMAN")
   - agrements: List of required certifications (D-codes like ["D1", "D2", "D13"])

2. **Lots** (if multiple lots exist):
   - lot_number: Use "UNIQUE" or "0" for single lot, otherwise "1", "2", etc.
   - lot_reference: Combine tender_ref + lot_number (e.g., "MOD-HABOUS-2025-210_unique")
   - title: Full description of the lot (can be multi-line)
   - budget_lot: Estimated budget for this specific lot

CRITICAL RULES:
- DO NOT include: deadline, publication_date, buyer_initials, buyer_address, buyer_phone, buyer_email, buyer_contact, status
- For single lot tenders, use lot_number: "UNIQUE" or "0"
- tender_reference MUST follow format: XX_YYYY_ACRONYM_ORGANIZATION
- buyer field is MANDATORY
- agrements should be empty list [] if none found

Return ONLY valid JSON matching this exact structure:
{{
  "tender_info": {{
    "tender_reference": "01_2026_EXAMPLE_ORGANIZATION",
    "location": "City/Province",
    "global_budget": 1000000.0,
    "nbre_lots": 1,
    "buyer": "Organization Name",
    "passation_mode": "Appel d'offres ouvert",
    "type": "Project Type",
    "agrements": []
  }},
  "lots": [
    {{"lot_number": "UNIQUE", "lot_reference": "REF_unique", "title": "Description", "budget_lot": 500000.0}}
  ],
  "products": []
}}

Return ONLY JSON, no explanations. If a field is not found, use null (except agrements which should be []).
"""
    def _create_products_prompt(self, doc_type: str) -> str:
        """Create prompt for product extraction."""
        return f"""Analyze the tender document (Bordereau des Prix / BDP) and extract all product line items.

Document Type: {doc_type}

For each row in the price table, extract:
- designation (product/service description)
- unit (measurement unit: m2, kg, u, etc.)
- quantity (required quantity)
- estimated_price (unit price if available)
- lot_number (which lot this belongs to)

Return ONLY valid JSON in this structure:
{{
  "products": [
    {{
      "designation": "...",
      "unit": "...",
      "quantity": 100.0,
      "estimated_price": 50.0,
      "lot_number": "1"
    }},
    ...
  ]
}}

CRITICAL RULES:
- Create ONE JSON object per table row
- Do NOT calculate or estimate any values
- If a value is missing, use null
- Ignore headers, subtotals, and summary rows
- Return ONLY JSON, no explanations
"""
