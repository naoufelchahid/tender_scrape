import pytest
from uri_builder import (
    slugify, TS,
    get_result_uri, get_winner_bid_uri, get_bid_uri, get_contractor_uri,
    get_tender_uri,
)


def test_slugify_basic():
    assert slugify("003/2026_SRMCS") == "003_2026_SRMCS"


def test_slugify_accents():
    assert slugify("Société Générale") == "SOCIETE_GENERALE"


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
