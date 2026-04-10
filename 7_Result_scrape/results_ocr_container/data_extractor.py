"""
Structured data extraction for tender results.
Extracts bidder information, amounts, and reasons into JSON format.

Stage: Extraction Container - Data Extraction
"""
from typing import Dict, List, Any, Optional
import json
from groq import Groq

from config import Config
from logger import logger


# Structured extraction prompt template
STRUCTURED_EXTRACTION_PROMPT_TEMPLATE = """Extract ALL bidder information from this tender results document into a structured JSON format.

CRITICAL INSTRUCTIONS:
1. Extract EVERY bidder/company mentioned in the document
2. For EACH bidder, extract:
   - Company name (exact as written, including Moroccan extensions like SARL, SA, SARL AU, etc.)
   - Bid amount in MAD (monetary amount proposed with TTC or HT)
   - Status (admitted/excluded/rejected/disqualified)
   - Rejection reason (if excluded - extract the EXACT reason mentioned)

3. Identify the WINNER clearly and put them in the "winner" field.
4. IMPORTANT: Do NOT include the winner in the "bidders" list. The "bidders" list should ONLY contain non-winning bidders (both admitted and excluded).
5. Extract lot reference if multiple lots exist.
6. MANDATORY Lot Reference Generation:
   - If there is only one lot or no explicit lot mentioned: Use "0"
   - If there are multiple explicit lots: Use "{tender_ref}_1", "{tender_ref}_2", etc. for each lot respectively.

OUTPUT FORMAT (strict JSON):
```json
{{
  "lots": [
    {{
      "lot_reference": "string",
      "winner": {{
        "company_name": "exact company name",
        "winning_amount": numeric_value_only
      }},
      "bidders": [
        {{
          "company_name": "exact company name",
          "bid_amount": numeric_value_only,
          "status": "admitted|excluded|rejected|disqualified",
          "rejection_reason": "exact reason if excluded, otherwise null"
        }}
      ]
    }}
  ]
}}
```

EXTRACTION RULES:
- Extract ONLY numeric values for amounts (remove currency symbols, spaces, commas)
- If amount is "1 234 567,89" extract as 1234567.89
- If status is "excluded" or "rejected", MUST extract rejection reason
- Company names should be EXACT as written.
- If document has multiple lots, create separate entries for each.

Extract from the entire document and return ONLY valid JSON."""


class DataExtractor:
    """Structured data extractor using Groq API."""
    
    def __init__(self):
        """Initialize data extractor."""
        self.groq_client = Groq(api_key=Config.GROQ_API_KEY)
        logger.info("Initialized DataExtractor with Groq API")
    
    def extract_structured_data(self, markdown_text: str, tender_ref: str) -> Optional[Dict[str, Any]]:
        """
        Extract structured bidder data from markdown text.
        
        Args:
            markdown_text: Markdown text from OCR/extraction
            tender_ref: Tender reference for prompt personalization
            
        Returns:
            Dictionary with structured data or None if extraction fails
        """
        try:
            logger.info(f"Extracting structured data from markdown for {tender_ref}...")
            
            # Format prompt with tender_ref
            extraction_prompt = STRUCTURED_EXTRACTION_PROMPT_TEMPLATE.format(tender_ref=tender_ref)
            
            # Call Groq API with Maverick (reasoning model) for better extraction
            response = self.groq_client.chat.completions.create(
                model=Config.FALLBACK_MODEL,  # Maverick for reasoning
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data extraction expert. Extract information exactly as requested and return only valid JSON."
                    },
                    {
                        "role": "user",
                        "content": f"{extraction_prompt}\n\nDOCUMENT:\n{markdown_text}"
                    }
                ],
                max_tokens=4000,
                temperature=0.1
            )
            
            extracted_text = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if extracted_text.startswith("```json"):
                extracted_text = extracted_text[7:]
            if extracted_text.startswith("```"):
                extracted_text = extracted_text[3:]
            if extracted_text.endswith("```"):
                extracted_text = extracted_text[:-3]
            
            extracted_text = extracted_text.strip()
            
            # Parse JSON
            data = json.loads(extracted_text)
            
            logger.info(f"✅ Successfully extracted structured data: {len(data.get('lots', []))} lot(s)")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from extraction: {e}")
            logger.error(f"Raw output: {extracted_text[:500]}")
            return None
        except Exception as e:
            logger.error(f"Error during structured extraction: {e}")
            return None
    
    def format_for_database(self, structured_data: Dict[str, Any], tender_ref: str) -> List[Dict[str, Any]]:
        """
        Format extracted data for database insertion.
        
        Args:
            structured_data: Extracted structured data
            tender_ref: Tender reference
            
        Returns:
            List of records ready for database insertion
        """
        records = []
        
        try:
            lots = structured_data.get('lots', [])
            
            for lot in lots:
                record = {
                    'lot_reference': lot.get('lot_reference'),
                    'tender_reference': tender_ref,
                    'winner_company_name': None,
                    'win_bid': None,
                }
                
                # Extract winner
                winner = lot.get('winner', {})
                if winner:
                    record['winner_company_name'] = winner.get('company_name')
                    record['win_bid'] = winner.get('winning_amount')  # Changed to winning_amount
                
                # Extract bidders (up to 15 non-winners)
                bidders = lot.get('bidders', [])
                # Ensure we don't have the winner here if LLM made a mistake
                winner_name = record.get('winner_company_name', '').lower().strip()
                
                filtered_bidders = []
                for b in bidders:
                    b_name = b.get('company_name', '').lower().strip()
                    if winner_name and b_name == winner_name:
                        continue
                    filtered_bidders.append(b)
                
                for idx, bidder in enumerate(filtered_bidders[:15], 1):
                    record[f'bidder{idx}_company_name'] = bidder.get('company_name')
                    record[f'bid{idx}'] = bidder.get('bid_amount')
                    record[f'remarque{idx}'] = bidder.get('rejection_reason')
                
                records.append(record)
            
            logger.info(f"Formatted {len(records)} record(s) for database")
            return records
            
        except Exception as e:
            logger.error(f"Error formatting data for database: {e}")
            return []
