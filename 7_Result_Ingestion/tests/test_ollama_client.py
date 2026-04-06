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
