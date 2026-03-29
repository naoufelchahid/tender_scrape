import pytest
import json
import os
import re
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pydantic import ValidationError
from src.models import (
    ChunkItem, AvisMetadata, SpecificationMetadata,
    AdministrativeMetadata, ProductChunkMetadata, ChunkingOutput
)

# Mock environment for OpenAI client initialization
os.environ["OPENAI_API_KEY"] = "sk-test-key"
os.environ["OPENROUTER_API_KEY"] = "sk-test-key"

def test_avis_metadata_schema():
    """Test AvisMetadata validation and alias support."""
    valid_data = {
        "type": "avis",
        "objet": "Test Object",
        "mode de soumission": "en ligne",
        "mode de passation": "public",
        "qualifications": "C1",
        "budget": "1 200 000,00 DH", # Test numeric parsing
        "location": "Rabat",
        "deadline": "2024-12-31",
        "caution": "500,50",
        "contact": "test@example.com",
        "phone": "0600000000",
        "lot_number": "1"
    }
    
    model = AvisMetadata(**valid_data)
    assert model.mode_de_soumission == "en ligne"
    assert model.budget == 1200000.0
    assert model.caution == 500.5
    
    # Test alias dumping
    dumped = model.model_dump(by_alias=True)
    assert dumped["mode de soumission"] == "en ligne"
    assert dumped["mode de passation"] == "public"

def test_specification_metadata_schema():
    """Test SpecificationMetadata defaults and required fields."""
    data = {
        "title": "Article 1",
        "chapter": "Chapter I"
    }
    model = SpecificationMetadata(**data)
    assert model.type == "specification"
    assert model.title == "Article 1"

def test_administrative_metadata_schema():
    model = AdministrativeMetadata(title="Admin Title")
    assert model.type == "administrative"

def test_product_metadata_schema():
    """Test ProductChunkMetadata alias and dynamic fields."""
    data = {
        "product header": "Header info",
        "designation": "Item Name",
        "quantity": "10,5",
        "unit": "KG"
    }
    model = ProductChunkMetadata(**data)
    assert model.product_header == "Header info"
    assert model.quantity == 10.5
    
    dumped = model.model_dump(by_alias=True)
    assert dumped["product header"] == "Header info"

def test_chunk_item_union():
    """Test ChunkItem correctly handles different metadata types."""
    avis_chunk = {
        "content": "some text",
        "metadata": {"type": "avis", "objet": "obj", "lot_number": "1"}
    }
    spec_chunk = {
        "content": "other text",
        "metadata": {"type": "specification", "title": "T1"}
    }
    
    item1 = ChunkItem(**avis_chunk)
    assert isinstance(item1.metadata, AvisMetadata)
    
    item2 = ChunkItem(**spec_chunk)
    assert isinstance(item2.metadata, SpecificationMetadata)

@patch("src.document_chunker.OpenRouterClientWrapper")
@pytest.mark.parametrize("doc_type,expected_fields", [
    ("avis", ["mode de soumission", "lot_number"]),
    ("specification", ["title", "chapter"]),
    ("administrative", ["title", "chapter"]),
    ("product", ["product header", "designation"])
])
def test_field_presence_in_mock_outputs(mock_llm, doc_type, expected_fields):
    """Verify that mock output simulations contain expected keys."""
    from src.document_chunker import DocumentChunker
    chunker = DocumentChunker(region_name="eu-west-3")
    
    sample_meta = {
        "type": doc_type,
        "mode de soumission": "val",
        "lot_number": "1",
        "title": "T",
        "chapter": "C",
        "product header": "H",
        "designation": "D",
        "garbage": "extra"
    }
    
    cleaned = chunker._clean_metadata_for_type(sample_meta, doc_type)
    
    for field in expected_fields:
        assert field in cleaned
    
    assert "garbage" not in cleaned
    if doc_type != "avis":
        assert "mode de soumission" not in cleaned

def test_product_metadata_preservation():
    """Verify that product_n keys are not stripped by metadata cleaner."""
    from src.document_chunker import DocumentChunker
    chunker = DocumentChunker(region_name="eu-west-3")
    
    product_meta = {
        "type": "product",
        "product_1": {"designation": "item 1", "quantity": 5},
        "product_2": {"designation": "item 2", "quantity": 10}
    }
    
    cleaned = chunker._clean_metadata_for_type(product_meta, "product")
    
    # These should be preserved, but currently they are stripped
    assert "product_1" in cleaned
    assert "product_2" in cleaned
    assert cleaned["product_1"]["designation"] == "item 1"

def test_avis_arabic_removal():
    """Verify that Arabic characters are removed from avis content."""
    # This might need a new method in cleaning.py or document_chunker.py
    # For now, let's assume we want a utility that does this.
    from src.document_chunker import DocumentChunker
    chunker = DocumentChunker(region_name="eu-west-3")
    
    # Simulated item from LLM that failed to follow translation instructions
    items = [
        ChunkItem(
            content="Tender content in French. محتوى بالعربية",
            metadata={"type": "avis"}
        )
    ]
    
    # We want finalize_chunks to clean the content too
    final = chunker._finalize_chunks(items, "REF", 1, "avis")
    
    # Resulting content should not have Arabic
    content = final[0]["content"]
    assert "Tender content in French." in content
    assert "محتوى بالعربية" not in content

def test_robust_parsing_malformed_json():
    """Reproduce reported ValidationError where LLM returns stray strings in chunks."""
    from src.document_chunker import DocumentChunker
    from src.cleaning import LogicalDocument
    import pytest
    from unittest.mock import AsyncMock, patch

    chunker = DocumentChunker(region_name="eu-west-3")
    
    # Simulate the exact malformed response reported in the error
    # { "chunks": [ {...}, "metadata", ":", {"objet": "...", ...} ] }
    malformed_json = json.dumps({
        "chunks": [
            {
                "content": "Valid chunk",
                "metadata": {"type": "avis", "objet": "Test"}
            },
            "metadata",
            ":",
            {
                "type": "avis",
                "objet": "Missing content chunk",
                "lot_number": "0"
            }
        ]
    })
    
    doc = LogicalDocument(original_filename="test.md", content="dummy", doc_type="avis_fr")
    
    with patch.object(chunker.llm, 'chat_completion_async', return_value=malformed_json):
        # Currently, this should FAIL with ValidationError or log error and return fallback
        # The user's error showed it reached main.py, meaning _process_with_llm didn't handle it
        # Actually in _process_with_llm:
        # parsed = ChunkingOutput(**data) -> this raises ValidationError
        # except Exception as e: logger.error(...) -> returns self._simple_split(doc, ...)
        
        # We want to verify that after our FIX, it instead returns the valid chunks and skips junk
        # For RED phase, we check that it currently fails to return the valid chunk 1 
        # (it actually returns simple_split on failure)
        chunks = asyncio.run(chunker._process_with_llm(doc, "REF", 1))
        
        # In RED phase, this will likely be simple_split which usually has different structure
        # or it might have logged an error.
        # The goal is that it should NOT be simple_split, but the valid extracted chunk.
        assert any(c["content"] == "Valid chunk" for c in chunks)
        assert not any(c.get("metadata", {}).get("objet") == "Missing content chunk" for c in chunks)
