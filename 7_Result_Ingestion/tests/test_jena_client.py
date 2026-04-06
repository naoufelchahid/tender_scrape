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
