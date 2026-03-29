
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional
from src.document_chunker import DocumentChunker
from src.cleaning import LogicalDocument

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_metadata_extraction():
    # Mock Decompose Function to simulate actual behavior reported by user
    def mock_decompose_func(content, compact=True):
        if compact:
            return {"units": [{"text": content}]}
        else:
            # Simulate a sequence of units: H2 then H3
            return {"units": [
                {"text": "## CHAPITRE PREMIER - DISPOSITIONS GENERALES\nContenu du chapitre...", "intent": "header"},
                {"text": "### ARTICLE I.4 - PIECES CONSTITUTIVES DU MARCHE\n4.1 Les obligations de l’IC...", "intent": "article"}
            ]}

    chunker = DocumentChunker(openrouter_api_key="dummy_key", decomposer_func=mock_decompose_func)
    
    doc = LogicalDocument(
        original_filename="spec_test.md",
        content="## CHAPITRE PREMIER...\n### ARTICLE I.4...",
        doc_type="specification"
    )
    
    logger.info("Running extraction to reproduce metadata issue...")
    results = await chunker.chunk_all_documents([doc], 1, "REF001")
    
    spec_chunks = results.get('specification', [])
    for i, chunk in enumerate(spec_chunks):
        content_preview = chunk['content'][:50].replace('\n', '\\n')
        meta = chunk['metadata']
        logger.info(f"Chunk {i+1}:")
        logger.info(f"  Content: {content_preview}...")
        logger.info(f"  Title:   {meta.get('title')}")
        logger.info(f"  Chapter: {meta.get('chapter')}")
        
    # Assertions according to user request
    if len(spec_chunks) >= 2:
        # Check second chunk (the ARTICLE I.4 one)
        article_chunk = spec_chunks[1]
        title = article_chunk['metadata'].get('title')
        chapter = article_chunk['metadata'].get('chapter')
        
        expected_title = "ARTICLE I.4 - PIECES CONSTITUTIVES DU MARCHE"
        expected_chapter = "CHAPITRE PREMIER - DISPOSITIONS GENERALES"
        
        # Current logic will fail these:
        # Title will be "article" (intent) or "specification" (doc_type)
        # Chapter will be "Extracted Segment"
        
        print("\n--- RESULTS ---")
        if title == expected_title:
            print(f"TITLE:   PASS ({title})")
        else:
            print(f"TITLE:   FAIL (Got: '{title}', Expected: '{expected_title}')")
            
        if chapter == expected_chapter:
            print(f"CHAPTER: PASS ({chapter})")
        else:
            print(f"CHAPTER: FAIL (Got: '{chapter}', Expected: '{expected_chapter}')")

if __name__ == "__main__":
    asyncio.run(test_metadata_extraction())
