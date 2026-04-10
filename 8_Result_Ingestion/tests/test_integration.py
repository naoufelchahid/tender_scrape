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
