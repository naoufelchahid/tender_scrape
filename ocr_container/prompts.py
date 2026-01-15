"""
Detailed OCR prompts for OpenRouter and Bedrock APIs.
Ensures high-quality transcription and table preservation.
"""

OCR_SYSTEM_PROMPT = """You are an expert OCR system specializing in French and Arabic tender documents from Morocco.
Your task is to transcribe ALL visible text from images with PERFECT accuracy.

CRITICAL REQUIREMENTS:

1. PRESERVE TABLE INTEGRITY:
   - Convert all tables to markdown format with proper column alignment
   - Use pipe syntax: | Column 1 | Column 2 | Column 3 |
   - Include header separator: |----------|----------|----------|
   - Never split table rows across pages
   - Preserve all numeric values exactly as shown

2. MAINTAIN STRUCTURE:
   - Use # for main headings, ## for subheadings, ### for sub-sections
   - Preserve bullet points with - or *
   - Preserve numbered lists with 1., 2., 3.
   - Maintain paragraph breaks and spacing
   - Keep page numbers and footers

3. COMPLETE TRANSCRIPTION:
   - Do NOT skip any text, numbers, or symbols
   - Include headers, footers, page numbers, watermarks
   - Transcribe all visible content even if partially obscured
   - Preserve all special characters: €, %, deg, etc.

4. FORMATTING:
   - Use **bold** for emphasized text
   - Use *italic* for secondary emphasis
   - Preserve underlined text as __underlined__
   - Maintain indentation for hierarchical content

5. NUMBERS AND DATES:
   - Preserve all numeric formatting (123.456,78 or 123,456.78)
   - Keep currency symbols and units (DH, MAD, €)
   - Maintain date formats as displayed (JJ/MM/AAAA or DD/MM/YYYY)
   - Preserve percentages with % symbol

6. SPECIAL CONTENT:
   - For logos or images, write: [IMAGE: brief description]
   - For signatures, write: [SIGNATURE]
   - For stamps, write: [STAMP: text if readable]
   - For checkboxes: [☑] for checked, [☐] for unchecked

OUTPUT FORMAT: Pure markdown text only. No preamble, no comments, no additional explanation."""

OCR_USER_PROMPT_TEMPLATE = """Please transcribe this {document_type} document image to markdown format.

Document Type: {document_type}
Page: {page_number} of {total_pages}

Follow all instructions in the system prompt strictly. Ensure perfect table preservation and complete transcription."""

TABLE_ENHANCEMENT_PROMPT = """Review the following extracted table and ensure:

1. All columns are properly aligned with pipe separators
2. Header row is clearly identified with separator line
3. Numeric values are correctly formatted and aligned
4. No data is missing or truncated  
5. Markdown syntax is valid (proper pipe usage)
6. Table is complete (all rows present)

Original table:
{table_content}

Return ONLY the corrected markdown table, nothing else."""

TABLE_ENHANCEMENT_PROMPT_MAVERICK = TABLE_ENHANCEMENT_PROMPT

ARABIC_DOCUMENT_PROMPT = """This is an Arabic tender document that may be scanned or handwritten.
Please:
1. Transcribe all Arabic text accurately (right-to-left)
2. Preserve table structures using markdown pipes
3. Include any French or English text present
4. Maintain document hierarchy and formatting
5. Convert all visible content to structured markdown

OUTPUT: Pure markdown text with proper RTL consideration."""

BATCH_DOCUMENT_PROMPT = """This document appears to be a batch specification (Bordereau de Prix or similar).
Special requirements:
1. Preserve ALL table rows - these contain critical product/service specifications
2. Maintain exact numeric values (quantities, unit prices, total prices)
3. Keep column headers clear and aligned
4. Include item numbers/references
5. Preserve units of measurement (m2, kg, unité, etc.)
6. Format currency values consistently

This is critical procurement data - 100% accuracy required."""

CPS_DOCUMENT_PROMPT = """This document appears to be a CPS (Cahier des Prescriptions Spéciales).
Special requirements:
1. Preserve article and chapter structure (Article 1, Article 2, etc.)
2. Maintain hierarchical organization of clauses
3. Keep legal language exact and complete
4. Preserve all numbered/lettered lists (a), b), c))
5. Include all references to regulations and norms
6. Maintain any tables with technical specifications

This is a legal document - exact transcription is critical."""

RC_DOCUMENT_PROMPT = """This document appears to be an RC (Règlement de Consultation).
Special requirements:
1. Preserve administrative requirements structure
2. Maintain criteria lists and scoring systems
3. Keep all deadlines and dates exact
4. Preserve bid submission requirements
5. Include all evaluation criteria
6. Maintain any tables with scoring grids

This defines the tender process - complete accuracy required."""


def get_prompt_for_document_type(doc_type: str) -> str:
    """
    Get specialized prompt based on document type.
    
    Args:
        doc_type: Document type (CPS, BDP, RC, or generic)
        
    Returns:
        Specialized prompt string
    """
    doc_type_upper = doc_type.upper()
    
    if 'CPS' in doc_type_upper or 'CAHIER' in doc_type_upper:
        return CPS_DOCUMENT_PROMPT
    elif 'BDP' in doc_type_upper or 'BORDEREAU' in doc_type_upper or 'PRIX' in doc_type_upper:
        return BATCH_DOCUMENT_PROMPT
    elif 'RC' in doc_type_upper or 'REGLEMENT' in doc_type_upper:
        return RC_DOCUMENT_PROMPT
    else:
        return ""  # Use default system prompt only


def create_ocr_messages(image_base64: str, document_type: str = "tender", 
                        page_number: int = 1, total_pages: int = 1,
                        is_arabic: bool = False) -> list:
    """
    Create message array for OCR API call.
    
    Args:
        image_base64: Base64-encoded image
        document_type: Type of document being processed
        page_number: Current page number
        total_pages: Total number of pages
        is_arabic: Whether document is in Arabic
        
    Returns:
        List of message dicts for API call
    """
    # Add document-type specific guidance
    specific_prompt = get_prompt_for_document_type(document_type)
    
    # Add Arabic-specific guidance if needed
    if is_arabic:
        specific_prompt += "\n\n" + ARABIC_DOCUMENT_PROMPT
    
    user_content = OCR_USER_PROMPT_TEMPLATE.format(
        document_type=document_type,
        page_number=page_number,
        total_pages=total_pages
    )
    
    if specific_prompt:
        user_content = specific_prompt + "\n\n" + user_content
    
    messages = [
        {
            "role": "system",
            "content": OCR_SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_content
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        }
    ]
    
    return messages
