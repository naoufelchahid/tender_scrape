"""Ollama API client for structured data extraction from result markdown."""
import json
import re
import logging
from typing import Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract ALL bidder information from this tender results document into a structured JSON format.

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


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks that deepseek-r1 prepends."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON."""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class OllamaClient:
    def __init__(self, base_url: str = "http://ollama:11434",
                 model: str = "deepseek-r1:1.5b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def extract_structured_data(self, markdown_text: str,
                                tender_ref: str) -> Optional[Dict[str, Any]]:
        """Call Ollama to extract structured bid data from OCR markdown.

        Returns parsed JSON dict on success, None on failure.
        """
        prompt = EXTRACTION_PROMPT.format(tender_ref=tender_ref)
        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a precise data extraction expert. "
                                       "Extract information exactly as requested "
                                       "and return only valid JSON."
                        },
                        {
                            "role": "user",
                            "content": f"{prompt}\n\nDOCUMENT:\n{markdown_text}"
                        }
                    ],
                    "temperature": 0.1,
                },
                timeout=120,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            cleaned = _strip_think_tags(raw)
            cleaned = _strip_code_fences(cleaned)
            data = json.loads(cleaned)
            logger.info(f"Extracted {len(data.get('lots', []))} lot(s) for {tender_ref}")
            return data
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from Ollama for {tender_ref}")
            return None
        except Exception as e:
            logger.error(f"Ollama extraction failed for {tender_ref}: {e}")
            return None
