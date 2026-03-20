import pytest
from src.uri_builder import slugify, get_tender_uri, get_buyer_uri, TS

def test_slugify():
    assert slugify("AO/2024/001") == "AO_2024_001"
    assert slugify("Buyer Name & Co") == "Buyer_Name_Co"
    assert slugify("   Space Test   ") == "Space_Test"
    assert slugify(None) == "unknown"

def test_get_tender_uri():
    uri = get_tender_uri("AO/2024/123")
    assert str(uri) == f"{TS}Tender_AO_2024_123"

def test_get_buyer_uri():
    uri = get_buyer_uri("Ministère de l'Intérieur")
    assert str(uri).startswith(str(TS))
    assert "Minist_re_de_l_Int_rieur" in str(uri)
