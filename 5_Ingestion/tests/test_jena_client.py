import pytest
from unittest.mock import MagicMock
from src.jena_client import JenaClient


TENDER_IRI = "http://www.tenderintelligence.io/ontology/tender-structure#Tender_AO_TEST_001"


def _make_select_result(tender_iri: str) -> dict:
    """Simulate a SPARQL SELECT result for a tender lookup."""
    return {
        "results": {
            "bindings": [
                {"tender": {"type": "uri", "value": tender_iri}}
            ]
        }
    }


def _make_empty_select_result() -> dict:
    return {"results": {"bindings": []}}


def _make_ask_result(value: bool) -> dict:
    return {"boolean": value}


# ------------------------------------------------------------------ #
# find_tender_by_ref                                                   #
# ------------------------------------------------------------------ #

class TestFindTenderByRef:
    def test_found(self):
        query_fn = MagicMock(return_value=_make_ask_result(True))
        client = JenaClient(dataset="tenders", sparql_query_fn=query_fn)
        result = client.find_tender_by_ref("AO_TEST_001")
        assert result == TENDER_IRI
        query_fn.assert_called_once()
        call_kwargs = query_fn.call_args
        assert "AO_TEST_001" in call_kwargs.kwargs.get("query", "") or "AO_TEST_001" in str(call_kwargs)

    def test_not_found(self):
        query_fn = MagicMock(return_value=_make_ask_result(False))
        client = JenaClient(dataset="tenders", sparql_query_fn=query_fn)
        result = client.find_tender_by_ref("UNKNOWN_REF")
        assert result is None

    def test_query_failure(self):
        query_fn = MagicMock(side_effect=Exception("Connection refused"))
        client = JenaClient(dataset="tenders", sparql_query_fn=query_fn)
        result = client.find_tender_by_ref("AO_ERROR")
        assert result is None


# ------------------------------------------------------------------ #
# insert_triples                                                        #
# ------------------------------------------------------------------ #

class TestInsertTriples:
    def test_success(self):
        update_fn = MagicMock(return_value=None)
        client = JenaClient(dataset="tenders", sparql_update_fn=update_fn)
        ok = client.insert_triples("<http://ex.org/s> <http://ex.org/p> 'value' .")
        assert ok is True
        update_fn.assert_called_once()

    def test_failure(self):
        update_fn = MagicMock(side_effect=Exception("SPARQL error"))
        client = JenaClient(dataset="tenders", sparql_update_fn=update_fn)
        ok = client.insert_triples("<http://ex.org/s> <http://ex.org/p> 'value' .")
        assert ok is False

    def test_no_update_fn(self):
        client = JenaClient(dataset="tenders")
        ok = client.insert_triples("some turtle")
        assert ok is False


# ------------------------------------------------------------------ #
# quality gates (SPARQL ASK)                                           #
# ------------------------------------------------------------------ #

class TestQualityGates:
    def _client(self, ask_result: bool) -> JenaClient:
        query_fn = MagicMock(return_value=_make_ask_result(ask_result))
        return JenaClient(dataset="tenders", sparql_query_fn=query_fn)

    def test_check_tender_has_spec_true(self):
        assert self._client(True).check_tender_has_spec(TENDER_IRI) is True

    def test_check_tender_has_spec_false(self):
        assert self._client(False).check_tender_has_spec(TENDER_IRI) is False

    def test_check_tender_has_admin_true(self):
        assert self._client(True).check_tender_has_admin(TENDER_IRI) is True

    def test_check_tender_has_bordereau_true(self):
        assert self._client(True).check_tender_has_bordereau(TENDER_IRI) is True

    def test_check_bordereau_has_articles_false(self):
        assert self._client(False).check_bordereau_has_articles(TENDER_IRI) is False


# ------------------------------------------------------------------ #
# build helpers                                                         #
# ------------------------------------------------------------------ #

class TestBuildHelpers:
    def test_build_find_tender_query_contains_ref(self):
        client = JenaClient(sparql_query_fn=lambda **kwargs: {}) # Provide dummy to avoid error log
        q = client._build_find_tender_query("MY_REF_2025")
        assert "MY_REF_2025" in q
        assert "ts:Tenders" in q

    def test_build_insert_update_contains_body(self):
        client = JenaClient(sparql_update_fn=lambda **kwargs: {})
        body = "<http://ex.org/s> <http://ex.org/p> 'value' ."
        update = client._build_insert_update(body)
        assert "INSERT DATA" in update
        assert body in update
