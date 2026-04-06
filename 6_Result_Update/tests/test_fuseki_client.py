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
