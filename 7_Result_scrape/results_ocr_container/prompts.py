"""
Specialized prompts for tender results OCR extraction.
Adapted from lambda_remote_ocr.py

Stage: Extraction Container - OCR Processing
"""

# Primary OCR prompt for tender results documents
TENDER_RESULTS_PROMPT = """Transcribe ALL data from this document into well-structured markdown format.

IMPORTANT INSTRUCTIONS:
1. Extract EVERY piece of information visible in the document
2. Preserve all tables in markdown table format
3. Clearly identify and label these sections:
   - Tender Reference/Number (Référence, Numéro AO, etc.)
   - Tender Object/Description (Objet)
   - Client/Organization (Maître d'ouvrage, Organisme)
   - All Bidders/Competitors (Concurrents, Soumissionnaires) with their:
     * Company name
     * Proposed amount (Montant proposé)
     * Status (admitted/excluded/disqualified)
   - Winner (Concurrent retenu, Attributaire) with:
     * Company name
     * Final amount (Montant)
   - Any excluded bidders with reasons
   - Dates (submission, opening, decision)

4. Use clear headers (##, ###) for different sections
5. For tables with bidders, use this format:
   | Company Name | Proposed Amount | Status | Notes |
   |--------------|----------------|--------|-------|
   
6. Highlight the winner clearly with a dedicated section
7. Include ALL monetary amounts with their currency
8. Preserve any official stamps, signatures mentions, or validation information

Output everything in French if the document is in French, or in the document's original language.
Maintain the exact structure and formatting of tables."""


def create_ocr_messages(image_base64: str, page_number: int, total_pages: int) -> list:
    """
    Create messages for Groq API OCR request.
    
    Args:
        image_base64: Base64-encoded image
        page_number: Current page number
        total_pages: Total number of pages
        
    Returns:
        List of messages for Groq API
    """
    page_context = f"\n\nThis is page {page_number} of {total_pages}."
    
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": TENDER_RESULTS_PROMPT + page_context
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


def create_openrouter_messages(image_base64: str, page_number: int, total_pages: int) -> list:
    """
    Create messages for OpenRouter API (fallback).
    
    Args:
        image_base64: Base64-encoded image
        page_number: Current page number
        total_pages: Total number of pages
        
    Returns:
        List of messages for OpenRouter API
    """
    page_context = f"\n\nThis is page {page_number} of {total_pages}."
    
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": TENDER_RESULTS_PROMPT + page_context},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        }
    ]
