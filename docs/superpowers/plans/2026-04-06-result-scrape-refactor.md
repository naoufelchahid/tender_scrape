# Result Scrape Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Result_scrape/` with `6_Result_Update/` (Fuseki-based scraping) and `7_Result_Ingestion/` (Ollama extraction + RDF + SHACL + Jena), plus modify `2_Ocr/` for dual-queue polling.

**Architecture:** Three components — `6_Result_Update` queries Fuseki for tenders past deadline without results, scrapes marchespublics.gov.ma, uploads PDFs to S3 and sends to `RESULTS_OCR_QUEUE`. The existing `2_Ocr` container polls both `OCR_QUEUE` and `RESULTS_OCR_QUEUE`, routing results output to `RESULTS_INGESTION_QUEUE`. `7_Result_Ingestion` polls that queue, calls local Ollama for structured extraction, maps to RDF (TenderResults/TenderBids/Contractor), validates with SHACL, and inserts into Jena.

**Tech Stack:** Python 3.12, rdflib, pyshacl, playwright, boto3, requests (Fuseki + Ollama), Docker

**Design Spec:** `docs/superpowers/specs/2026-04-06-result-scrape-refactor-design.md`

---

## Task 1: Add `ts:Is_Result` data property to ontology

**Files:**
- Modify: `1_Update/tender_structure_final.owl`
- Modify: `5_Ingestion/ontology/tender_structure_final.owl`

- [ ] **Step 1: Add Is_Result data property to 1_Update ontology**

In `1_Update/tender_structure_final.owl`, find the data properties section (near other `DatatypeProperty` declarations like `ts:Has_PV` around line 1478) and add this OWL declaration before the closing `</rdf:RDF>`:

```xml
    <!-- http://www.tenderintelligence.io/ontology/tender-structure#Is_Result -->

    <owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Is_Result">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#boolean"/>
        <skos:prefLabel xml:lang="fr">A des résultats</skos:prefLabel>
        <skos:definition xml:lang="fr">Indique si les résultats de l'appel d'offres ont été trouvés et ingérés.</skos:definition>
        <skos:inScheme rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#TenderStructureScheme"/>
    </owl:DatatypeProperty>
```

- [ ] **Step 2: Copy updated ontology to 5_Ingestion**

```bash
cp 1_Update/tender_structure_final.owl 5_Ingestion/ontology/tender_structure_final.owl
```

- [ ] **Step 3: Commit**

```bash
git add 1_Update/tender_structure_final.owl 5_Ingestion/ontology/tender_structure_final.owl
git commit -m "feat(ontology): add ts:Is_Result data property to Tenders class"
```

---

## Task 2: Create `7_Result_Ingestion/uri_builder.py`

**Files:**
- Create: `7_Result_Ingestion/uri_builder.py`
- Test: `7_Result_Ingestion/tests/test_uri_builder.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p 7_Result_Ingestion/tests
mkdir -p 7_Result_Ingestion/ontology
touch 7_Result_Ingestion/__init__.py
touch 7_Result_Ingestion/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `7_Result_Ingestion/tests/test_uri_builder.py`:

```python
import pytest
from uri_builder import (
    slugify, TS,
    get_result_uri, get_winner_bid_uri, get_bid_uri, get_contractor_uri,
    get_tender_uri,
)


def test_slugify_basic():
    assert slugify("003/2026_SRMCS") == "003_2026_SRMCS"


def test_slugify_accents():
    assert slugify("Société Générale") == "Societe_Generale"


def test_slugify_empty():
    assert slugify("") == "unknown"


def test_get_result_uri_single_lot():
    uri = get_result_uri("003_2026_SRMCS", 0)
    assert str(uri) == f"{TS}Result_003_2026_SRMCS_0"


def test_get_result_uri_multi_lot():
    uri = get_result_uri("003_2026_SRMCS", 2)
    assert str(uri) == f"{TS}Result_003_2026_SRMCS_2"


def test_get_winner_bid_uri():
    uri = get_winner_bid_uri("003_2026_SRMCS", 0)
    assert str(uri) == f"{TS}Bid_Winner_003_2026_SRMCS_0"


def test_get_bid_uri():
    uri = get_bid_uri("003_2026_SRMCS", 0, 3)
    assert str(uri) == f"{TS}Bid_003_2026_SRMCS_0_3"


def test_get_contractor_uri():
    uri = get_contractor_uri("ENTREPRISE ATLAS SARL")
    assert "Contractor_" in str(uri)
    assert "ENTREPRISE_ATLAS_SARL" in str(uri)


def test_get_tender_uri():
    uri = get_tender_uri("003_2026_SRMCS")
    assert str(uri) == f"{TS}Tender_003_2026_SRMCS"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_uri_builder.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'uri_builder'`

- [ ] **Step 4: Write implementation**

Create `7_Result_Ingestion/uri_builder.py`:

```python
"""URI generation for result, bid, and contractor RDF nodes."""
import re
import unicodedata
from rdflib import Namespace, URIRef

TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")


def slugify(text: str) -> str:
    """Create a URL-safe slug from text.

    Mirrors the logic in 1_Update/kg_builder.py and 5_Ingestion/src/uri_builder.py:
    strip accents, replace non-alphanumeric with _, collapse runs, uppercase.
    """
    if not text:
        return "unknown"
    nfkd = unicodedata.normalize('NFKD', text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', without_accents)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip('_').upper()


def get_tender_uri(tender_ref: str) -> URIRef:
    return TS[f"Tender_{slugify(tender_ref)}"]


def get_result_uri(tender_ref: str, lot_index: int) -> URIRef:
    return TS[f"Result_{slugify(tender_ref)}_{lot_index}"]


def get_winner_bid_uri(tender_ref: str, lot_index: int) -> URIRef:
    return TS[f"Bid_Winner_{slugify(tender_ref)}_{lot_index}"]


def get_bid_uri(tender_ref: str, lot_index: int, bid_index: int) -> URIRef:
    return TS[f"Bid_{slugify(tender_ref)}_{lot_index}_{bid_index}"]


def get_contractor_uri(company_name: str) -> URIRef:
    return TS[f"Contractor_{slugify(company_name)}"]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_uri_builder.py -v
```

Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add 7_Result_Ingestion/
git commit -m "feat(7_Result_Ingestion): add uri_builder with slugify and URI generators"
```

---

## Task 3: Create `7_Result_Ingestion/ollama_client.py`

**Files:**
- Create: `7_Result_Ingestion/ollama_client.py`
- Test: `7_Result_Ingestion/tests/test_ollama_client.py`

- [ ] **Step 1: Write the failing test**

Create `7_Result_Ingestion/tests/test_ollama_client.py`:

```python
import pytest
import json
from unittest.mock import patch, MagicMock
from ollama_client import OllamaClient


SAMPLE_MARKDOWN = """
# PV d'ouverture des plis

Référence: 003/2026

## Résultats

| Concurrent | Montant TTC |
|------------|-------------|
| ATLAS SARL | 1 234 567,89 |
| BETA SA    | 2 345 678,90 |

Attributaire: ATLAS SARL
"""

EXPECTED_LLM_RESPONSE = {
    "lots": [
        {
            "lot_reference": "0",
            "winner": {
                "company_name": "ATLAS SARL",
                "winning_amount": 1234567.89
            },
            "bidders": [
                {
                    "company_name": "BETA SA",
                    "bid_amount": 2345678.90,
                    "status": "admitted",
                    "rejection_reason": None
                }
            ]
        }
    ]
}


def _mock_response(content: str):
    """Build a mock response matching OpenAI chat completions format."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock.raise_for_status = MagicMock()
    return mock


@patch("ollama_client.requests.post")
def test_extract_structured_data_success(mock_post):
    mock_post.return_value = _mock_response(json.dumps(EXPECTED_LLM_RESPONSE))
    client = OllamaClient(base_url="http://localhost:11434", model="deepseek-r1:1.5b")
    result = client.extract_structured_data(SAMPLE_MARKDOWN, "003_2026_SRMCS")
    assert result is not None
    assert len(result["lots"]) == 1
    assert result["lots"][0]["winner"]["company_name"] == "ATLAS SARL"


@patch("ollama_client.requests.post")
def test_extract_structured_data_json_in_code_block(mock_post):
    wrapped = f"```json\n{json.dumps(EXPECTED_LLM_RESPONSE)}\n```"
    mock_post.return_value = _mock_response(wrapped)
    client = OllamaClient(base_url="http://localhost:11434", model="deepseek-r1:1.5b")
    result = client.extract_structured_data(SAMPLE_MARKDOWN, "003_2026_SRMCS")
    assert result is not None
    assert result["lots"][0]["winner"]["winning_amount"] == 1234567.89


@patch("ollama_client.requests.post")
def test_extract_structured_data_invalid_json(mock_post):
    mock_post.return_value = _mock_response("not valid json at all")
    client = OllamaClient(base_url="http://localhost:11434", model="deepseek-r1:1.5b")
    result = client.extract_structured_data(SAMPLE_MARKDOWN, "003_2026_SRMCS")
    assert result is None


@patch("ollama_client.requests.post")
def test_extract_structured_data_with_think_tags(mock_post):
    """deepseek-r1 wraps output in <think>...</think> tags before the JSON."""
    content = f"<think>Let me analyze...</think>\n{json.dumps(EXPECTED_LLM_RESPONSE)}"
    mock_post.return_value = _mock_response(content)
    client = OllamaClient(base_url="http://localhost:11434", model="deepseek-r1:1.5b")
    result = client.extract_structured_data(SAMPLE_MARKDOWN, "003_2026_SRMCS")
    assert result is not None
    assert result["lots"][0]["winner"]["company_name"] == "ATLAS SARL"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_ollama_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `7_Result_Ingestion/ollama_client.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_ollama_client.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 7_Result_Ingestion/ollama_client.py 7_Result_Ingestion/tests/test_ollama_client.py
git commit -m "feat(7_Result_Ingestion): add ollama_client for structured extraction"
```

---

## Task 4: Create `7_Result_Ingestion/rdf_mapper.py`

**Files:**
- Create: `7_Result_Ingestion/rdf_mapper.py`
- Test: `7_Result_Ingestion/tests/test_rdf_mapper.py`

- [ ] **Step 1: Write the failing test**

Create `7_Result_Ingestion/tests/test_rdf_mapper.py`:

```python
import pytest
from rdflib import RDF, RDFS, XSD, Literal
from rdf_mapper import ResultRdfMapper
from uri_builder import TS


SAMPLE_EXTRACTED = {
    "lots": [
        {
            "lot_reference": "0",
            "winner": {
                "company_name": "ATLAS SARL",
                "winning_amount": 1234567.89
            },
            "bidders": [
                {
                    "company_name": "BETA SA",
                    "bid_amount": 2345678.90,
                    "status": "admitted",
                    "rejection_reason": None
                },
                {
                    "company_name": "GAMMA SARL AU",
                    "bid_amount": 999999.00,
                    "status": "rejected",
                    "rejection_reason": "Dossier incomplet"
                }
            ]
        }
    ]
}


def test_map_creates_result_node():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    assert len(results) == 1


def test_map_links_tender_to_result():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    from rdflib import URIRef
    tender_uri = URIRef("http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    opened = list(g.objects(tender_uri, TS.Is_Opened))
    assert len(opened) == 1


def test_map_creates_winner_bid():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    result_uri = results[0]
    winner_bids = list(g.objects(result_uri, TS.Is_Winner_Bid))
    assert len(winner_bids) == 1
    # Winner bid has amount
    amount = g.value(winner_bids[0], TS.Has_Bid_Amount)
    assert float(amount) == pytest.approx(1234567.89)


def test_map_creates_other_bids():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    all_bids = list(g.subjects(RDF.type, TS.TenderBids))
    # 1 winner + 2 other bidders = 3 total
    assert len(all_bids) == 3


def test_map_rejected_bid_has_rejected_link():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    result_uri = results[0]
    rejected = list(g.objects(result_uri, TS.Rejected_Bid))
    assert len(rejected) == 1


def test_map_contractor_nodes():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    contractors = list(g.subjects(RDF.type, TS.Contractor))
    assert len(contractors) == 3  # ATLAS, BETA, GAMMA


def test_map_has_pv():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    pv = g.value(results[0], TS.Has_PV)
    assert pv == Literal(True, datatype=XSD.boolean)


def test_get_ntriples():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(SAMPLE_EXTRACTED)
    nt = mapper.get_ntriples()
    assert "TenderResults" in nt
    assert "TenderBids" in nt
    assert "Contractor" in nt


def test_get_is_result_triple():
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    nt = mapper.get_is_result_triple()
    assert "Is_Result" in nt
    assert '"true"' in nt


def test_map_multi_lot():
    data = {
        "lots": [
            {
                "lot_reference": "003_2026_SRMCS_1",
                "winner": {"company_name": "A SARL", "winning_amount": 100.0},
                "bidders": []
            },
            {
                "lot_reference": "003_2026_SRMCS_2",
                "winner": {"company_name": "B SA", "winning_amount": 200.0},
                "bidders": []
            }
        ]
    }
    mapper = ResultRdfMapper("003_2026_SRMCS", "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS")
    mapper.map_results(data)
    g = mapper.graph
    results = list(g.subjects(RDF.type, TS.TenderResults))
    assert len(results) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_rdf_mapper.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `7_Result_Ingestion/rdf_mapper.py`:

```python
"""Map structured extraction JSON to RDF triples following the ontology."""
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Any

from rdflib import Graph, Literal, RDF, RDFS, XSD, URIRef
from uri_builder import (
    TS, slugify,
    get_result_uri, get_winner_bid_uri, get_bid_uri,
    get_contractor_uri, get_tender_uri,
)

logger = logging.getLogger(__name__)


def _parse_amount(value) -> Decimal:
    """Parse a numeric amount to Decimal."""
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        logger.warning(f"Could not parse amount '{value}', defaulting to 0")
        return Decimal(0)


class ResultRdfMapper:
    def __init__(self, tender_ref: str, tender_iri: str):
        """
        Args:
            tender_ref: Composite tender reference (e.g. '003_2026_SRMCS').
            tender_iri: Full IRI of the existing tender node in Jena.
        """
        self.tender_ref = tender_ref
        self.tender_uri = URIRef(tender_iri)
        self.graph = Graph()
        self.graph.bind("ts", TS)

    def map_results(self, extracted_data: Dict[str, Any]) -> None:
        """Map extracted lot/bidder JSON into RDF triples."""
        lots = extracted_data.get("lots", [])
        for lot_idx, lot in enumerate(lots):
            self._map_lot(lot, lot_idx)

    def _map_lot(self, lot: dict, lot_idx: int) -> None:
        g = self.graph
        result_uri = get_result_uri(self.tender_ref, lot_idx)

        # TenderResults node
        g.add((result_uri, RDF.type, TS.TenderResults))
        g.add((self.tender_uri, TS.Is_Opened, result_uri))
        g.add((result_uri, TS.Is_Proces_Verbal_of, self.tender_uri))
        g.add((result_uri, TS.Has_PV, Literal(True, datatype=XSD.boolean)))

        # Winner
        winner = lot.get("winner")
        if winner and winner.get("company_name"):
            winner_bid_uri = get_winner_bid_uri(self.tender_ref, lot_idx)
            winner_contractor_uri = get_contractor_uri(winner["company_name"])

            g.add((winner_bid_uri, RDF.type, TS.TenderBids))
            g.add((result_uri, TS.Is_Winner_Bid, winner_bid_uri))
            g.add((result_uri, TS.Has_Bid, winner_bid_uri))
            g.add((winner_bid_uri, TS.Is_Bid_in, result_uri))

            amount = _parse_amount(winner.get("winning_amount"))
            g.add((winner_bid_uri, TS.Has_Bid_Amount,
                   Literal(amount, datatype=XSD.decimal)))

            g.add((winner_contractor_uri, RDF.type, TS.Contractor))
            g.add((winner_contractor_uri, RDFS.label,
                   Literal(winner["company_name"], datatype=XSD.string)))
            g.add((winner_bid_uri, TS.Is_Bid_of, winner_contractor_uri))
            g.add((winner_contractor_uri, TS.Formulate_Bid, winner_bid_uri))

        # Other bidders
        for bid_idx, bidder in enumerate(lot.get("bidders", [])):
            bid_uri = get_bid_uri(self.tender_ref, lot_idx, bid_idx)
            contractor_uri = get_contractor_uri(bidder["company_name"])

            g.add((bid_uri, RDF.type, TS.TenderBids))
            g.add((result_uri, TS.Has_Bid, bid_uri))
            g.add((bid_uri, TS.Is_Bid_in, result_uri))

            amount = _parse_amount(bidder.get("bid_amount"))
            g.add((bid_uri, TS.Has_Bid_Amount,
                   Literal(amount, datatype=XSD.decimal)))

            g.add((contractor_uri, RDF.type, TS.Contractor))
            g.add((contractor_uri, RDFS.label,
                   Literal(bidder["company_name"], datatype=XSD.string)))
            g.add((bid_uri, TS.Is_Bid_of, contractor_uri))
            g.add((contractor_uri, TS.Formulate_Bid, bid_uri))

            # Rejected bid
            status = (bidder.get("status") or "").lower()
            if status in ("excluded", "rejected", "disqualified"):
                g.add((result_uri, TS.Rejected_Bid, bid_uri))

    def get_ntriples(self) -> str:
        """Serialize graph as N-Triples for SPARQL INSERT DATA."""
        return self.graph.serialize(format="nt")

    def get_is_result_triple(self) -> str:
        """Return the N-Triple that sets ts:Is_Result=true on the tender."""
        g = Graph()
        g.add((self.tender_uri, TS.Is_Result,
               Literal(True, datatype=XSD.boolean)))
        return g.serialize(format="nt")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_rdf_mapper.py -v
```

Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 7_Result_Ingestion/rdf_mapper.py 7_Result_Ingestion/tests/test_rdf_mapper.py
git commit -m "feat(7_Result_Ingestion): add rdf_mapper for TenderResults/Bids/Contractor"
```

---

## Task 5: Create SHACL shapes and `7_Result_Ingestion/shacl_validator.py`

**Files:**
- Create: `7_Result_Ingestion/ontology/shapes_results.ttl`
- Create: `7_Result_Ingestion/shacl_validator.py`
- Copy: `7_Result_Ingestion/ontology/tender_structure_final.owl` (from `1_Update/`)
- Test: `7_Result_Ingestion/tests/test_shacl_validator.py`

- [ ] **Step 1: Copy ontology and create SHACL shapes**

```bash
cp 1_Update/tender_structure_final.owl 7_Result_Ingestion/ontology/tender_structure_final.owl
```

Create `7_Result_Ingestion/ontology/shapes_results.ttl`:

```turtle
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix ts:  <http://www.tenderintelligence.io/ontology/tender-structure#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# ---------------------------------------------------------------------------
# Results SHACL Shapes
#
# Validates what 7_Result_Ingestion produces:
#   - TenderResults nodes (PV)
#   - TenderBids nodes (winner + other bidders)
# ---------------------------------------------------------------------------

ts:TenderResultsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderResults ;
    sh:property [
        sh:path ts:Is_Proces_Verbal_of ;
        sh:minCount 1 ;
        sh:message "A TenderResults must link to a Tender via ts:Is_Proces_Verbal_of." ;
    ] ;
    sh:property [
        sh:path ts:Has_Bid ;
        sh:minCount 1 ;
        sh:message "A TenderResults must have at least one Bid (ts:Has_Bid)." ;
    ] .

ts:TenderBidsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderBids ;
    sh:property [
        sh:path ts:Is_Bid_of ;
        sh:minCount 1 ;
        sh:message "A TenderBids must link to a Contractor via ts:Is_Bid_of." ;
    ] ;
    sh:property [
        sh:path ts:Is_Bid_in ;
        sh:minCount 1 ;
        sh:message "A TenderBids must link to a TenderResults via ts:Is_Bid_in." ;
    ] .
```

- [ ] **Step 2: Write the failing test**

Create `7_Result_Ingestion/tests/test_shacl_validator.py`:

```python
import pytest
from rdflib import Graph, RDF, RDFS, Literal, XSD
from uri_builder import TS
from rdf_mapper import ResultRdfMapper
from shacl_validator import ShaclValidator

VALID_DATA = {
    "lots": [{
        "lot_reference": "0",
        "winner": {"company_name": "ATLAS SARL", "winning_amount": 100.0},
        "bidders": [
            {"company_name": "BETA SA", "bid_amount": 200.0, "status": "admitted", "rejection_reason": None}
        ]
    }]
}

TENDER_IRI = "http://www.tenderintelligence.io/ontology/tender-structure#Tender_TEST_001"


@pytest.fixture
def validator():
    return ShaclValidator(
        shapes_path="ontology/shapes_results.ttl",
    )


def test_valid_graph_passes(validator):
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(VALID_DATA)
    assert validator.validate(mapper.graph) is True


def test_missing_bid_fails(validator):
    """A TenderResults with no Has_Bid should fail SHACL."""
    g = Graph()
    g.bind("ts", TS)
    from rdflib import URIRef
    result_uri = URIRef(f"{TS}Result_TEST_001_0")
    tender_uri = URIRef(TENDER_IRI)
    g.add((result_uri, RDF.type, TS.TenderResults))
    g.add((result_uri, TS.Is_Proces_Verbal_of, tender_uri))
    # No Has_Bid — should fail
    assert validator.validate(g) is False


def test_missing_is_bid_of_fails(validator):
    """A TenderBids with no Is_Bid_of should fail SHACL."""
    g = Graph()
    g.bind("ts", TS)
    from rdflib import URIRef
    result_uri = URIRef(f"{TS}Result_TEST_001_0")
    tender_uri = URIRef(TENDER_IRI)
    bid_uri = URIRef(f"{TS}Bid_TEST_001_0_0")
    g.add((result_uri, RDF.type, TS.TenderResults))
    g.add((result_uri, TS.Is_Proces_Verbal_of, tender_uri))
    g.add((result_uri, TS.Has_Bid, bid_uri))
    g.add((bid_uri, RDF.type, TS.TenderBids))
    g.add((bid_uri, TS.Is_Bid_in, result_uri))
    # No Is_Bid_of — should fail
    assert validator.validate(g) is False


def test_logical_winner_must_have_positive_amount(validator):
    """Logical assertion: winner bid amount > 0."""
    data = {
        "lots": [{
            "lot_reference": "0",
            "winner": {"company_name": "ATLAS SARL", "winning_amount": 0},
            "bidders": []
        }]
    }
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(data)
    assert validator.validate(mapper.graph) is False


def test_logical_must_have_winner(validator):
    """Logical assertion: at least one Is_Winner_Bid per TenderResults."""
    data = {
        "lots": [{
            "lot_reference": "0",
            "winner": {},
            "bidders": [
                {"company_name": "BETA SA", "bid_amount": 200.0, "status": "admitted", "rejection_reason": None}
            ]
        }]
    }
    mapper = ResultRdfMapper("TEST_001", TENDER_IRI)
    mapper.map_results(data)
    assert validator.validate(mapper.graph) is False
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_shacl_validator.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write implementation**

Create `7_Result_Ingestion/shacl_validator.py`:

```python
"""SHACL validation and logical assertions for result RDF graphs."""
import logging
from pathlib import Path

from rdflib import Graph, RDF
from pyshacl import validate

from uri_builder import TS

logger = logging.getLogger(__name__)


class ShaclValidator:
    def __init__(self, shapes_path: str):
        self._shapes_path = shapes_path
        self._shapes_graph = None

    @property
    def shapes_graph(self) -> Graph:
        if self._shapes_graph is None:
            logger.info(f"Loading SHACL shapes from {self._shapes_path}")
            self._shapes_graph = Graph().parse(self._shapes_path, format="turtle")
        return self._shapes_graph

    def validate(self, data_graph: Graph) -> bool:
        """Run SHACL + logical assertions. Returns True if all pass."""
        ok = True

        # 1. SHACL validation
        conforms, _, v_text = validate(
            data_graph=data_graph,
            shacl_graph=self.shapes_graph,
            inference='none',
        )
        if not conforms and "sh:Violation" in v_text:
            logger.error(f"SHACL validation failed:\n{v_text[:500]}")
            ok = False

        # 2. Logical assertions
        try:
            self._assert_logical_consistency(data_graph)
        except AssertionError as e:
            logger.error(f"Logical consistency failed: {e}")
            ok = False

        return ok

    def _assert_logical_consistency(self, g: Graph) -> None:
        """Custom logical assertions for result graphs."""
        for result_uri in g.subjects(RDF.type, TS.TenderResults):
            # Must have at least one Is_Winner_Bid
            winners = list(g.objects(result_uri, TS.Is_Winner_Bid))
            if not winners:
                raise AssertionError(
                    f"TenderResults {result_uri} has no Is_Winner_Bid"
                )

            # Winner bid amount must be > 0
            for winner_bid in winners:
                amount = g.value(winner_bid, TS.Has_Bid_Amount)
                if amount is not None and float(amount) <= 0:
                    raise AssertionError(
                        f"Winner bid {winner_bid} has amount <= 0: {amount}"
                    )

                # Winner bid must have a contractor
                contractor = g.value(winner_bid, TS.Is_Bid_of)
                if contractor is None:
                    raise AssertionError(
                        f"Winner bid {winner_bid} has no Is_Bid_of contractor"
                    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_shacl_validator.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add 7_Result_Ingestion/ontology/ 7_Result_Ingestion/shacl_validator.py 7_Result_Ingestion/tests/test_shacl_validator.py
git commit -m "feat(7_Result_Ingestion): add SHACL shapes and validator with logical assertions"
```

---

## Task 6: Create `7_Result_Ingestion/jena_client.py`

**Files:**
- Create: `7_Result_Ingestion/jena_client.py`
- Test: `7_Result_Ingestion/tests/test_jena_client.py`

- [ ] **Step 1: Write the failing test**

Create `7_Result_Ingestion/tests/test_jena_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from jena_client import JenaClient


@pytest.fixture
def client():
    return JenaClient(
        endpoint="http://fuseki:3030",
        dataset="tenders",
        username="admin",
        password="admin",
    )


@patch("jena_client.requests.post")
def test_find_tender_found(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"boolean": True}),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    iri = client.find_tender_iri("003_2026_SRMCS")
    assert iri is not None
    assert "Tender_003_2026_SRMCS" in iri


@patch("jena_client.requests.post")
def test_find_tender_not_found(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"boolean": False}),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    iri = client.find_tender_iri("NONEXISTENT")
    assert iri is None


@patch("jena_client.requests.post")
def test_insert_triples(mock_post, client):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status = MagicMock()
    result = client.insert_triples('<s> <p> <o> .\n')
    assert result is True


@patch("jena_client.requests.post")
def test_ask_has_result(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"boolean": True}),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    result = client.check_tender_has_result("http://example.org/Tender_1")
    assert result is True


@patch("jena_client.requests.post")
def test_check_result_has_bids(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"boolean": True}),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    result = client.check_result_has_bids("http://example.org/Tender_1")
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_jena_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `7_Result_Ingestion/jena_client.py`:

```python
"""Jena Fuseki client for SPARQL queries and updates."""
import logging
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from uri_builder import TS, slugify

logger = logging.getLogger(__name__)

PREFIXES = """
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
""".strip()

TIMEOUT = 30


class JenaClient:
    def __init__(self, endpoint: str, dataset: str,
                 username: str = "", password: str = ""):
        self.endpoint = endpoint.rstrip("/")
        self.dataset = dataset
        self.auth = HTTPBasicAuth(username, password) if username else None

    @property
    def _query_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/sparql"

    @property
    def _update_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/update"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def find_tender_iri(self, tender_ref: str) -> Optional[str]:
        """Return full IRI of tender if it exists, else None."""
        safe = slugify(tender_ref)
        uri = f"{TS}Tender_{safe}"
        query = f"""{PREFIXES}
ASK {{ <{uri}> a ts:Tenders . }}"""
        result = self._ask(query)
        if result:
            logger.info(f"Found tender: {uri}")
            return uri
        logger.warning(f"Tender '{tender_ref}' not found in Jena KB")
        return None

    def insert_triples(self, ntriples_data: str) -> bool:
        """INSERT DATA with N-Triples payload."""
        update = f"""{PREFIXES}
INSERT DATA {{
{ntriples_data}
}}"""
        return self._update(update)

    def check_tender_has_result(self, tender_iri: str) -> bool:
        query = f"""{PREFIXES}
ASK {{ <{tender_iri}> ts:Is_Opened ?r . }}"""
        return self._ask(query)

    def check_result_has_bids(self, tender_iri: str) -> bool:
        query = f"""{PREFIXES}
ASK {{
  <{tender_iri}> ts:Is_Opened ?r .
  ?r ts:Has_Bid ?b .
}}"""
        return self._ask(query)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _ask(self, query: str) -> bool:
        try:
            resp = requests.post(
                self._query_url,
                data={"query": query},
                auth=self.auth,
                headers={"Accept": "application/sparql-results+json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("boolean", False)
        except Exception as e:
            logger.error(f"SPARQL ASK failed: {e}")
            return False

    def _update(self, update: str) -> bool:
        try:
            resp = requests.post(
                self._update_url,
                data={"update": update},
                auth=self.auth,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"SPARQL UPDATE failed: {e}")
            return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd 7_Result_Ingestion && python -m pytest tests/test_jena_client.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 7_Result_Ingestion/jena_client.py 7_Result_Ingestion/tests/test_jena_client.py
git commit -m "feat(7_Result_Ingestion): add jena_client for SPARQL query/update"
```

---

## Task 7: Create `7_Result_Ingestion/result_ingestor.py` (main entry point)

**Files:**
- Create: `7_Result_Ingestion/result_ingestor.py`
- Create: `7_Result_Ingestion/requirements.txt`
- Create: `7_Result_Ingestion/.env.template`
- Create: `7_Result_Ingestion/Dockerfile`
- Create: `7_Result_Ingestion/docker-compose.yml`

- [ ] **Step 1: Create requirements.txt**

Create `7_Result_Ingestion/requirements.txt`:

```
boto3>=1.34
rdflib>=7.0
pyshacl>=0.25
requests>=2.31
python-dotenv>=1.0
```

- [ ] **Step 2: Create .env.template**

Create `7_Result_Ingestion/.env.template`:

```bash
# Jena Fuseki
JENA_ENDPOINT=http://fuseki:3030
JENA_DATASET=tenders
JENA_USERNAME=admin
JENA_PASSWORD=admin

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=deepseek-r1:1.5b

# AWS
AWS_REGION=eu-west-3
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET_NAME=tender-scrape-data

# SQS
RESULTS_INGESTION_QUEUE_URL=
```

- [ ] **Step 3: Write result_ingestor.py**

Create `7_Result_Ingestion/result_ingestor.py`:

```python
"""
Result Ingestion Service.
Polls RESULTS_INGESTION_QUEUE, fetches OCR markdown from S3,
extracts structured data via Ollama, maps to RDF, validates with SHACL,
and inserts into Jena Fuseki.
"""
import os
import json
import logging
import time
from typing import Optional

import boto3
from dotenv import load_dotenv

from ollama_client import OllamaClient
from rdf_mapper import ResultRdfMapper
from shacl_validator import ShaclValidator
from jena_client import JenaClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ResultIngestor:
    def __init__(self):
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.queue_url = os.getenv("RESULTS_INGESTION_QUEUE_URL")
        self.bucket = os.getenv("S3_BUCKET_NAME")

        self.ollama = OllamaClient(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            model=os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b"),
        )
        self.validator = ShaclValidator(
            shapes_path=os.path.join(os.path.dirname(__file__), "ontology", "shapes_results.ttl"),
        )
        self.jena = JenaClient(
            endpoint=os.getenv("JENA_ENDPOINT", "http://fuseki:3030"),
            dataset=os.getenv("JENA_DATASET", "tenders"),
            username=os.getenv("JENA_USERNAME", ""),
            password=os.getenv("JENA_PASSWORD", ""),
        )

        if not self.queue_url:
            raise ValueError("RESULTS_INGESTION_QUEUE_URL is required")
        logger.info("ResultIngestor initialized")

    def _fetch_markdown(self, s3_key: str) -> Optional[str]:
        """Download markdown content from S3."""
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
            return resp["Body"].read().decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to fetch {s3_key}: {e}")
            return None

    def process_message(self, message: dict) -> bool:
        """Process one SQS message end-to-end."""
        body = json.loads(message["Body"])
        tender_ref = body.get("tender_ref")
        markdown_key = body.get("markdown_s3_key")

        if not tender_ref or not markdown_key:
            logger.error(f"Invalid message: {body}")
            return False

        logger.info(f"Processing result for {tender_ref}")

        # 1. Verify tender exists in Jena
        tender_iri = self.jena.find_tender_iri(tender_ref)
        if not tender_iri:
            logger.error(f"Tender {tender_ref} not found in Jena — deleting message")
            self._delete_message(message)
            return False

        # 2. Fetch markdown from S3
        markdown = self._fetch_markdown(markdown_key)
        if not markdown:
            return False

        # 3. Extract structured data via Ollama
        extracted = self.ollama.extract_structured_data(markdown, tender_ref)
        if not extracted or not extracted.get("lots"):
            logger.error(f"Extraction failed for {tender_ref}")
            return False

        # 4. Map to RDF
        mapper = ResultRdfMapper(tender_ref, tender_iri)
        mapper.map_results(extracted)

        # 5. SHACL + logical validation
        if not self.validator.validate(mapper.graph):
            logger.error(f"Validation failed for {tender_ref} — skipping ingestion")
            return False

        # 6. Insert result triples into Jena
        ntriples = mapper.get_ntriples()
        if not self.jena.insert_triples(ntriples):
            logger.error(f"Failed to insert triples for {tender_ref}")
            return False

        # 7. Set ts:Is_Result = true on the tender node
        is_result_nt = mapper.get_is_result_triple()
        if not self.jena.insert_triples(is_result_nt):
            logger.warning(f"Failed to set Is_Result for {tender_ref}")

        # 8. Post-ingestion quality gates
        has_result = self.jena.check_tender_has_result(tender_iri)
        has_bids = self.jena.check_result_has_bids(tender_iri)
        if not has_result or not has_bids:
            logger.warning(f"Post-ingestion check failed for {tender_ref}")

        # 9. Delete SQS message
        self._delete_message(message)
        logger.info(f"Successfully ingested results for {tender_ref}")
        return True

    def _delete_message(self, message: dict) -> None:
        self.sqs.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )

    def run(self):
        """Main polling loop."""
        logger.info("Starting Result Ingestion service...")
        while True:
            try:
                resp = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                )
                for msg in resp.get("Messages", []):
                    self.process_message(msg)
            except KeyboardInterrupt:
                logger.info("Shutting down")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(5)


if __name__ == "__main__":
    ResultIngestor().run()
```

- [ ] **Step 4: Create Dockerfile**

Create `7_Result_Ingestion/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "result_ingestor.py"]
```

- [ ] **Step 5: Create docker-compose.yml**

Create `7_Result_Ingestion/docker-compose.yml`:

```yaml
version: '3.8'

services:
  result-ingestion:
    build: .
    container_name: result-ingestion
    env_file:
      - .env
    volumes:
      - ./ontology:/app/ontology
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 6: Commit**

```bash
git add 7_Result_Ingestion/result_ingestor.py 7_Result_Ingestion/requirements.txt \
       7_Result_Ingestion/.env.template 7_Result_Ingestion/Dockerfile \
       7_Result_Ingestion/docker-compose.yml
git commit -m "feat(7_Result_Ingestion): add result_ingestor main service with Docker setup"
```

---

## Task 8: Create `6_Result_Update/fuseki_client.py`

**Files:**
- Create: `6_Result_Update/fuseki_client.py`
- Test: `6_Result_Update/tests/test_fuseki_client.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p 6_Result_Update/tests
touch 6_Result_Update/__init__.py
touch 6_Result_Update/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `6_Result_Update/tests/test_fuseki_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from fuseki_client import FusekiClient


SPARQL_RESPONSE = {
    "results": {
        "bindings": [
            {
                "tender": {"value": "http://example.org/Tender_003_2026_SRMCS"},
                "ref": {"value": "003_2026_SRMCS"},
                "originalRef": {"value": "003/2026"},
                "buyer": {"value": "SOCIETE REGIONALE MULTISERVICES CASABLANCA-SETTAT"},
            },
            {
                "tender": {"value": "http://example.org/Tender_010_2026_DPMS"},
                "ref": {"value": "010_2026_DPMS"},
            },
        ]
    }
}


@pytest.fixture
def client():
    return FusekiClient(
        endpoint="http://fuseki:3030",
        dataset="tenders",
        username="admin",
        password="admin",
    )


@patch("fuseki_client.requests.post")
def test_get_pending_tenders(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value=SPARQL_RESPONSE),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    tenders = client.get_pending_tenders()
    assert len(tenders) == 2
    assert tenders[0]["ref"] == "003_2026_SRMCS"
    assert tenders[0]["original_ref"] == "003/2026"
    assert tenders[0]["buyer"] == "SOCIETE REGIONALE MULTISERVICES CASABLANCA-SETTAT"


@patch("fuseki_client.requests.post")
def test_pending_tender_missing_optional_fields(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value=SPARQL_RESPONSE),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    tenders = client.get_pending_tenders()
    # Second tender has no originalRef or buyer
    assert tenders[1]["original_ref"] is None
    assert tenders[1]["buyer"] is None


@patch("fuseki_client.requests.post")
def test_derive_original_ref_fallback(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value=SPARQL_RESPONSE),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    tenders = client.get_pending_tenders()
    # Second tender: ref=010_2026_DPMS, no originalRef → derive "010_2026"
    assert tenders[1]["search_ref"] == "010_2026"


@patch("fuseki_client.requests.post")
def test_get_pending_tenders_empty(mock_post, client):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"results": {"bindings": []}}),
    )
    mock_post.return_value.raise_for_status = MagicMock()
    tenders = client.get_pending_tenders()
    assert tenders == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd 6_Result_Update && python -m pytest tests/test_fuseki_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write implementation**

Create `6_Result_Update/fuseki_client.py`:

```python
"""Fuseki SPARQL client for querying tenders pending results."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

PREFIXES = """
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
""".strip()

TIMEOUT = 30


class FusekiClient:
    def __init__(self, endpoint: str, dataset: str,
                 username: str = "", password: str = ""):
        self.endpoint = endpoint.rstrip("/")
        self.dataset = dataset
        self.auth = HTTPBasicAuth(username, password) if username else None

    @property
    def _query_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/sparql"

    def get_pending_tenders(self) -> List[Dict[str, Optional[str]]]:
        """Query Fuseki for tenders past deadline without results.

        Returns list of dicts with keys: ref, original_ref, buyer, search_ref.
        search_ref is the reference to use in marchespublics.gov.ma search.
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

        query = f"""{PREFIXES}
SELECT ?tender ?ref ?originalRef ?buyer WHERE {{
  ?tender a ts:Tenders ;
          ts:Ref ?ref .
  ?tender ts:Has_Deadline ?deadline .
  FILTER(?deadline < "{yesterday}"^^xsd:dateTime)
  FILTER NOT EXISTS {{ ?tender ts:Is_Result "true"^^xsd:boolean }}
  OPTIONAL {{ ?tender ts:Has_Original_Reference ?originalRef }}
  OPTIONAL {{ ?tender ts:Launched_by ?buyerNode .
             ?buyerNode rdfs:label ?buyer }}
}}"""

        try:
            resp = requests.post(
                self._query_url,
                data={"query": query},
                auth=self.auth,
                headers={"Accept": "application/sparql-results+json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
        except Exception as e:
            logger.error(f"SPARQL query failed: {e}")
            return []

        tenders = []
        for b in bindings:
            ref = b["ref"]["value"]
            original_ref = b.get("originalRef", {}).get("value")
            buyer = b.get("buyer", {}).get("value")

            # Derive search_ref: prefer originalRef, fallback to stripping initials
            if original_ref:
                search_ref = original_ref
            elif "_" in ref:
                search_ref = ref.rsplit("_", 1)[0]
            else:
                search_ref = ref

            tenders.append({
                "ref": ref,
                "original_ref": original_ref,
                "buyer": buyer,
                "search_ref": search_ref,
            })

        logger.info(f"Found {len(tenders)} tenders pending results")
        return tenders
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd 6_Result_Update && python -m pytest tests/test_fuseki_client.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add 6_Result_Update/
git commit -m "feat(6_Result_Update): add fuseki_client for SPARQL pending-results query"
```

---

## Task 9: Create `6_Result_Update/scraper.py`

**Files:**
- Create: `6_Result_Update/scraper.py`

This is adapted from `Result_scrape/Result_update/results_scraper.py` with key changes:
- No RDS dependency — receives tender data from Fuseki query results
- Match by tuple `(original_ref, buyer)` instead of initials-based composite ref
- Simpler structure: one function per concern

- [ ] **Step 1: Write implementation**

Create `6_Result_Update/scraper.py`:

```python
"""Playwright scraper for tender result documents on marchespublics.gov.ma."""
import asyncio
import logging
import os
import re
import unicodedata
import random
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AllAnn"


def normalize_name(name: str) -> str:
    """Normalize a name for comparison: strip accents, lowercase, collapse whitespace."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(without_accents.lower().split())


async def _human_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


class ResultScraper:
    def __init__(self, downloads_dir: str = "download_results"):
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)

    async def search_and_download(
        self, page: Page, search_ref: str, buyer_name: Optional[str], tender_ref: str
    ) -> Optional[str]:
        """Search marchespublics.gov.ma for PV document and download it.

        Args:
            page: Playwright page instance.
            search_ref: Original reference to search for.
            buyer_name: Buyer name from Fuseki for tuple matching.
            tender_ref: Composite tender ref (used for filename).

        Returns:
            Local file path of downloaded PDF, or None.
        """
        logger.info(f"Searching for results: ref={search_ref}, buyer={buyer_name}")
        try:
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
            await _human_delay(1, 2)

            # Fill reference field
            ref_input = await page.query_selector(
                "input#ctl0_CONTENU_PAGE_AdvancedSearch_reference"
            )
            if not ref_input:
                logger.error("Reference input field not found")
                return None

            await ref_input.fill(search_ref)

            # Select "Annonce d'extrait de PV" (value=5)
            await page.wait_for_selector(
                "select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType"
            )
            await page.select_option(
                "select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType", "5"
            )

            # Submit search
            await page.click(
                "input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche"
            )
            await page.wait_for_load_state("networkidle")
            await _human_delay(2, 3)

            # Set page size to 500
            page_size = await page.query_selector(
                "select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop"
            )
            if page_size:
                await page.select_option(
                    "select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop", "500"
                )
                await page.wait_for_load_state("networkidle")
                await _human_delay(2, 3)

            # Parse results and match by (ref, buyer) tuple
            return await self._find_and_download(page, search_ref, buyer_name, tender_ref)

        except Exception as e:
            logger.error(f"Scraping error for {tender_ref}: {e}")
            return None

    async def _find_and_download(
        self, page: Page, search_ref: str, buyer_name: Optional[str], tender_ref: str
    ) -> Optional[str]:
        """Paginate through results, match by buyer name, download PDF."""
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        total_pages = 1
        page_count_el = soup.find(
            "span", id="ctl0_CONTENU_PAGE_resultSearch_nombrePageTop"
        )
        if page_count_el:
            try:
                total_pages = int(page_count_el.get_text(strip=True))
            except ValueError:
                pass

        normalized_buyer = normalize_name(buyer_name) if buyer_name else None

        for current_page in range(1, total_pages + 1):
            logger.info(f"Searching page {current_page}/{total_pages}")
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            buyer_divs = soup.find_all(
                "div", id=lambda x: x and "panelBlocDenomination" in x
            )
            tender_links = await page.query_selector_all(
                'a[href*="EntrepriseDetailConsultation"]'
            )

            for idx, buyer_div in enumerate(buyer_divs):
                if idx >= len(tender_links):
                    break

                page_buyer = buyer_div.get_text(strip=True)
                page_buyer = re.sub(
                    r"^Acheteur public\s*:\s*", "", page_buyer, flags=re.IGNORECASE
                )
                page_buyer = " ".join(page_buyer.split())

                # Match by tuple: buyer name comparison
                if normalized_buyer and normalize_name(page_buyer) != normalized_buyer:
                    continue

                # If no buyer from Fuseki, skip matching (take first result)
                logger.info(f"Matched tender row by buyer: {page_buyer}")

                await tender_links[idx].click()
                await page.wait_for_load_state("networkidle")
                await _human_delay(2, 3)

                # Find download link
                download_link = await page.query_selector(
                    'a:has-text("Fichier joint"), a[href*="EntrepriseDownloadAvisJAL"]'
                )
                if download_link:
                    async with page.expect_download() as dl_info:
                        await download_link.click()
                    download = await dl_info.value

                    ext = Path(download.suggested_filename).suffix or ".pdf"
                    safe_ref = tender_ref.replace("/", "_")
                    filename = f"{safe_ref}_result{ext}"
                    filepath = self.downloads_dir / filename
                    await download.save_as(str(filepath))
                    logger.info(f"Downloaded: {filepath}")
                    return str(filepath)

                logger.warning("No download link on detail page")
                await page.go_back()
                await page.wait_for_load_state("networkidle")
                return None

            # Navigate to next page
            if current_page < total_pages:
                next_link = await page.query_selector(
                    f'a[href*="numPageEnCours={current_page + 1}"]'
                )
                if next_link:
                    await next_link.click()
                    await page.wait_for_load_state("networkidle")
                    await _human_delay(2, 3)
                else:
                    break

        logger.info(f"No results found for {tender_ref}")
        return None
```

- [ ] **Step 2: Commit**

```bash
git add 6_Result_Update/scraper.py
git commit -m "feat(6_Result_Update): add scraper for marchespublics.gov.ma result PDFs"
```

---

## Task 10: Create `6_Result_Update/result_updater.py` (main entry point)

**Files:**
- Create: `6_Result_Update/result_updater.py`
- Create: `6_Result_Update/requirements.txt`
- Create: `6_Result_Update/.env.template`
- Create: `6_Result_Update/Dockerfile`
- Create: `6_Result_Update/docker-compose.yml`
- Create: `6_Result_Update/run_result_update.sh`

- [ ] **Step 1: Create requirements.txt**

Create `6_Result_Update/requirements.txt`:

```
boto3>=1.34
requests>=2.31
playwright>=1.40
playwright-stealth>=1.0
beautifulsoup4>=4.12
python-dotenv>=1.0
```

- [ ] **Step 2: Create .env.template**

Create `6_Result_Update/.env.template`:

```bash
# Jena Fuseki
JENA_ENDPOINT=http://fuseki:3030
JENA_DATASET=tenders
JENA_USERNAME=admin
JENA_PASSWORD=admin

# AWS
AWS_REGION=eu-west-3
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET_NAME=tender-scrape-data

# SQS
RESULTS_OCR_QUEUE_URL=
```

- [ ] **Step 3: Write result_updater.py**

Create `6_Result_Update/result_updater.py`:

```python
"""
Result Update Service.
Queries Fuseki for tenders past deadline without results,
scrapes marchespublics.gov.ma for PV documents,
uploads PDFs to S3, sends messages to RESULTS_OCR_QUEUE.
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import boto3
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from fuseki_client import FusekiClient
from scraper import ResultScraper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("result_updater.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ResultUpdater:
    def __init__(self):
        self.fuseki = FusekiClient(
            endpoint=os.getenv("JENA_ENDPOINT", "http://fuseki:3030"),
            dataset=os.getenv("JENA_DATASET", "tenders"),
            username=os.getenv("JENA_USERNAME", ""),
            password=os.getenv("JENA_PASSWORD", ""),
        )
        self.scraper = ResultScraper()
        self.bucket = os.getenv("S3_BUCKET_NAME")
        self.queue_url = os.getenv("RESULTS_OCR_QUEUE_URL")
        self.s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "eu-west-3"))

    def _upload_to_s3(self, local_path: str, tender_ref: str) -> str:
        """Upload result PDF to S3. Returns S3 key."""
        safe_ref = tender_ref.replace("/", "_")
        ext = Path(local_path).suffix or ".pdf"
        s3_key = f"tender_results/{safe_ref}_result{ext}"
        self.s3.upload_file(local_path, self.bucket, s3_key)
        logger.info(f"Uploaded to s3://{self.bucket}/{s3_key}")
        return s3_key

    def _send_to_queue(self, tender_ref: str, s3_key: str) -> bool:
        """Send message to RESULTS_OCR_QUEUE."""
        if not self.queue_url:
            logger.warning("RESULTS_OCR_QUEUE_URL not configured")
            return False
        message = {
            "tender_ref": tender_ref,
            "s3_paths": [s3_key],
            "bucket": self.bucket,
            "timestamp": datetime.now().isoformat(),
        }
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(message),
        )
        logger.info(f"Sent to RESULTS_OCR_QUEUE: {tender_ref}")
        return True

    async def run(self):
        """Main flow: query Fuseki → scrape → upload → queue."""
        tenders = self.fuseki.get_pending_tenders()
        if not tenders:
            logger.info("No pending tenders found")
            return

        logger.info(f"Processing {len(tenders)} tenders")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=os.getenv("HEADLESS_BROWSER", "true").lower() == "true",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--lang=fr-FR",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/91.0.4472.124 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            found = 0
            for tender in tenders:
                file_path = await self.scraper.search_and_download(
                    page,
                    search_ref=tender["search_ref"],
                    buyer_name=tender["buyer"],
                    tender_ref=tender["ref"],
                )
                if file_path:
                    s3_key = self._upload_to_s3(file_path, tender["ref"])
                    self._send_to_queue(tender["ref"], s3_key)
                    # Clean up local file
                    os.remove(file_path)
                    found += 1

            await browser.close()
            logger.info(f"Done. Found results for {found}/{len(tenders)} tenders")


if __name__ == "__main__":
    asyncio.run(ResultUpdater().run())
```

- [ ] **Step 4: Create Dockerfile**

Create `6_Result_Update/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

CMD ["python", "result_updater.py"]
```

- [ ] **Step 5: Create docker-compose.yml**

Create `6_Result_Update/docker-compose.yml`:

```yaml
version: '3.8'

services:
  result-update:
    build: .
    container_name: result-update
    env_file:
      - .env
    volumes:
      - ./download_results:/app/download_results
    restart: "no"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 6: Create run_result_update.sh**

Create `6_Result_Update/run_result_update.sh`:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Result Update ==="
echo "Querying Fuseki for tenders past deadline without results..."
cd "$(dirname "$0")"
python result_updater.py
echo "=== Done ==="
```

```bash
chmod +x 6_Result_Update/run_result_update.sh
```

- [ ] **Step 7: Commit**

```bash
git add 6_Result_Update/result_updater.py 6_Result_Update/requirements.txt \
       6_Result_Update/.env.template 6_Result_Update/Dockerfile \
       6_Result_Update/docker-compose.yml 6_Result_Update/run_result_update.sh
git commit -m "feat(6_Result_Update): add result_updater main service with Docker setup"
```

---

## Task 11: Modify `2_Ocr/` for dual-queue polling

**Files:**
- Modify: `2_Ocr/config.py`
- Modify: `2_Ocr/main.py`
- Modify: `2_Ocr/docker-compose.yml`

- [ ] **Step 1: Add new env vars to config.py**

In `2_Ocr/config.py`, add these two class attributes after `CLASSIFICATION_QUEUE_URL`:

```python
    RESULTS_OCR_QUEUE_URL: str = os.getenv('RESULTS_OCR_QUEUE_URL', '')
    RESULTS_INGESTION_QUEUE_URL: str = os.getenv('RESULTS_INGESTION_QUEUE_URL', '')
```

Add to `print_config()` method, after the `CLASSIFICATION_QUEUE_URL` print line:

```python
        if cls.RESULTS_OCR_QUEUE_URL:
            print(f"  RESULTS_OCR_QUEUE_URL: {cls.RESULTS_OCR_QUEUE_URL[:50]}...")
        if cls.RESULTS_INGESTION_QUEUE_URL:
            print(f"  RESULTS_INGESTION_QUEUE_URL: {cls.RESULTS_INGESTION_QUEUE_URL[:50]}...")
```

Do NOT add `RESULTS_OCR_QUEUE_URL` or `RESULTS_INGESTION_QUEUE_URL` to the `required_vars` in `validate()` — they are optional (OCR container works without results pipeline).

- [ ] **Step 2: Add result processing method to main.py**

In `2_Ocr/main.py`, add a new method `_process_result` to `OCRService` class after the `_process_tender` method (after line ~275). This method handles result messages with different S3 paths and downstream routing:

```python
    def _process_result(self, message_body: dict) -> bool:
        """Process result document from RESULTS_OCR_QUEUE.

        Same OCR pipeline as tenders, but uploads to Results_markdown/
        and sends downstream message to RESULTS_INGESTION_QUEUE.
        """
        start_time = time.time()
        tender_ref = message_body.get('tender_ref')
        s3_paths = message_body.get('s3_paths', [])

        if not tender_ref or not s3_paths:
            logger.error("Invalid result message: missing tender_ref or s3_paths")
            return False

        log_processing_start(tender_ref, len(s3_paths), s3_paths)
        batch_id = _get_active_batch_id()
        if batch_id:
            mon_enter(batch_id, tender_ref, "ocr")

        try:
            # Download files
            local_paths = self._download_tender_files(tender_ref, s3_paths)
            if not local_paths:
                logger.error(f"No files downloaded for result {tender_ref}")
                return False

            # Process each file with same OCR pipeline
            markdown_parts = []
            for local_path in local_paths:
                if not self._is_supported_file(local_path):
                    continue
                file_markdown = self._process_file(local_path, tender_ref)
                markdown_parts.append(file_markdown)
                markdown_parts.append("\n\n---\n\n")

            final_markdown = "".join(markdown_parts)

            # Upload to Results_markdown/ (different prefix from tenders)
            tender_ref_safe = tender_ref.replace('/', '_')
            markdown_filename = f"{tender_ref_safe}.md"
            local_md_path = os.path.join(self.temp_dir, markdown_filename)
            with open(local_md_path, 'w', encoding='utf-8') as f:
                f.write(final_markdown)

            md_s3_key = f"Results_markdown/markdown_files/{markdown_filename}"
            metadata = {
                'tender_ref': tender_ref.encode('ascii', 'ignore').decode('ascii'),
                'processed_date': datetime.utcnow().isoformat(),
                'ocr_engine': 'docling',
                'type': 'result',
            }
            if not self.s3_client.upload_file(local_md_path, md_s3_key, metadata):
                logger.error(f"Failed to upload result markdown for {tender_ref}")
                return False

            if os.path.exists(local_md_path):
                os.remove(local_md_path)

            # Send to RESULTS_INGESTION_QUEUE
            if Config.RESULTS_INGESTION_QUEUE_URL:
                ingestion_msg = {
                    'tender_ref': tender_ref,
                    'markdown_s3_key': md_s3_key,
                    'bucket': Config.S3_BUCKET_NAME,
                    'timestamp': datetime.utcnow().isoformat(),
                }
                self.sqs_client.send_message(
                    ingestion_msg,
                    queue_url=Config.RESULTS_INGESTION_QUEUE_URL,
                )
                logger.info(f"Sent result to RESULTS_INGESTION_QUEUE: {tender_ref}")

            self._cleanup_temp_files(tender_ref)
            processing_time = time.time() - start_time

            if batch_id:
                mon_complete(
                    batch_id, tender_ref, "ocr",
                    processing_time_s=round(processing_time, 1),
                    file_count=len(local_paths),
                    markdown_chars=len(final_markdown),
                    type="result",
                )
            return True

        except Exception as e:
            log_processing_error(tender_ref, e)
            if batch_id:
                mon_failed(batch_id, tender_ref, "ocr", error=str(e))
            self._cleanup_temp_files(tender_ref)
            return False
```

- [ ] **Step 3: Modify the run() loop for dual-queue polling**

Replace the `run()` method in `2_Ocr/main.py` (lines ~277-309) with:

```python
    def run(self) -> None:
        """Main service loop. Polls OCR_QUEUE and RESULTS_OCR_QUEUE."""
        logger.info("Starting OCR service main loop")
        polls_results = bool(Config.RESULTS_OCR_QUEUE_URL)
        if polls_results:
            logger.info(f"Dual-queue mode: also polling RESULTS_OCR_QUEUE")

        while True:
            try:
                # Poll primary OCR queue
                message = self.sqs_client.receive_message()
                if message:
                    logger.info(f"Processing tender message: {message['message_id']}")
                    success = self._process_tender(message['body'])
                    if success:
                        self.sqs_client.delete_message(message['receipt_handle'])
                        logger.info("Tender message processed and deleted")
                    else:
                        logger.error("Tender message failed, will retry")
                    continue

                # Poll results OCR queue (only if configured)
                if polls_results:
                    result_msg = self.sqs_client.receive_message(
                        queue_url=Config.RESULTS_OCR_QUEUE_URL
                    )
                    if result_msg:
                        logger.info(f"Processing result message: {result_msg['message_id']}")
                        success = self._process_result(result_msg['body'])
                        if success:
                            self.sqs_client.delete_message(
                                result_msg['receipt_handle'],
                                queue_url=Config.RESULTS_OCR_QUEUE_URL,
                            )
                            logger.info("Result message processed and deleted")
                        else:
                            logger.error("Result message failed, will retry")

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(5)
```

- [ ] **Step 4: Add new env vars to docker-compose.yml**

In `2_Ocr/docker-compose.yml`, add these to the `environment` section:

```yaml
      - RESULTS_OCR_QUEUE_URL=${RESULTS_OCR_QUEUE_URL:-}
      - RESULTS_INGESTION_QUEUE_URL=${RESULTS_INGESTION_QUEUE_URL:-}
```

- [ ] **Step 5: Commit**

```bash
git add 2_Ocr/config.py 2_Ocr/main.py 2_Ocr/docker-compose.yml
git commit -m "feat(2_Ocr): add dual-queue polling for RESULTS_OCR_QUEUE"
```

---

## Task 12: Integration smoke test

**Files:**
- Create: `7_Result_Ingestion/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `7_Result_Ingestion/tests/test_integration.py`:

```python
"""Integration test: extraction → RDF mapping → SHACL validation → N-Triples."""
import pytest
import json
from unittest.mock import patch, MagicMock

from ollama_client import OllamaClient
from rdf_mapper import ResultRdfMapper
from shacl_validator import ShaclValidator
from uri_builder import TS


SAMPLE_MARKDOWN = """
# PV d'ouverture des plis
Référence: 003/2026
Objet: Travaux de construction

## Résultats
Attributaire: ATLAS SARL - Montant: 1 234 567,89 MAD TTC

Autres soumissionnaires:
- BETA SA: 2 345 678,90 MAD TTC (admis)
- GAMMA SARL AU: 999 999,00 MAD TTC (écarté - dossier incomplet)
"""

OLLAMA_RESPONSE = {
    "lots": [{
        "lot_reference": "0",
        "winner": {"company_name": "ATLAS SARL", "winning_amount": 1234567.89},
        "bidders": [
            {"company_name": "BETA SA", "bid_amount": 2345678.90, "status": "admitted", "rejection_reason": None},
            {"company_name": "GAMMA SARL AU", "bid_amount": 999999.00, "status": "rejected", "rejection_reason": "Dossier incomplet"},
        ]
    }]
}

TENDER_IRI = "http://www.tenderintelligence.io/ontology/tender-structure#Tender_003_2026_SRMCS"


@patch("ollama_client.requests.post")
def test_full_pipeline(mock_post):
    """Test: Ollama extraction → RDF mapping → SHACL → N-Triples output."""
    # Mock Ollama
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(OLLAMA_RESPONSE)}}]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    # 1. Extract
    client = OllamaClient(base_url="http://localhost:11434", model="deepseek-r1:1.5b")
    extracted = client.extract_structured_data(SAMPLE_MARKDOWN, "003_2026_SRMCS")
    assert extracted is not None

    # 2. Map to RDF
    mapper = ResultRdfMapper("003_2026_SRMCS", TENDER_IRI)
    mapper.map_results(extracted)

    # 3. Validate with SHACL
    validator = ShaclValidator(shapes_path="ontology/shapes_results.ttl")
    assert validator.validate(mapper.graph) is True

    # 4. Serialize N-Triples
    nt = mapper.get_ntriples()
    assert len(nt) > 0
    assert "TenderResults" in nt
    assert "TenderBids" in nt
    assert "Contractor" in nt
    assert "Is_Winner_Bid" in nt
    assert "Rejected_Bid" in nt

    # 5. Is_Result triple
    is_result_nt = mapper.get_is_result_triple()
    assert "Is_Result" in is_result_nt
```

- [ ] **Step 2: Run all tests**

```bash
cd 7_Result_Ingestion && python -m pytest tests/ -v
```

Expected: All tests PASS (uri_builder: 8, ollama_client: 4, rdf_mapper: 10, shacl_validator: 5, integration: 1 = 28 total)

- [ ] **Step 3: Commit**

```bash
git add 7_Result_Ingestion/tests/test_integration.py
git commit -m "test(7_Result_Ingestion): add integration test for full extraction-to-RDF pipeline"
```

---

## Task 13: Run `6_Result_Update` tests

- [ ] **Step 1: Run all tests**

```bash
cd 6_Result_Update && python -m pytest tests/ -v
```

Expected: All 4 fuseki_client tests PASS

- [ ] **Step 2: Final commit with all files**

Verify nothing is left unstaged:

```bash
git status
```

If there are any remaining files (e.g. `__init__.py` files), stage and commit them:

```bash
git add 6_Result_Update/ 7_Result_Ingestion/
git diff --cached --stat  # verify
git commit -m "chore: add remaining init files for 6_Result_Update and 7_Result_Ingestion"
```
