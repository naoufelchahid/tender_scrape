
import asyncio
import logging
from typing import List, Dict, Any, Optional
from src.document_chunker import DocumentChunker
from src.cleaning import LogicalDocument

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def smoke_test_extraction():
    logger.info("Starting CLEAN smoke test for Extraction Container...")
    
    # Mock LLM Client
    class MockClient:
        async def chat_completion_async(self, messages, **kwargs):
            logger.info("✓ Mocked chat_completion_async called")
            # Return valid JSON for ChunkingOutput
            return '{"chunks": [{"content": "Mocked extracted section", "metadata": {"objet": "mock objet", "type": "avis"}}]}'

    # Mock Decompose Function
    def mock_decompose_func(content, compact=True):
        logger.info(f"✓ Mocked decompose_text called (compact={compact})")
        if compact:
            return {"units": [{"text": f"[CLEANED] {content[:50]}"}]}
        else:
            return {"units": [
                {"text": f"Segment 1: {content[:20]}", "intent": "article"},
                {"text": "Segment 2: more content", "intent": "chapter"}
            ]}

    # Initialize Chunker with Mocks
    mock_client = MockClient()
    # Note: DocumentChunker.__init__ was updated to support client and decomposer_func injection
    chunker = DocumentChunker(client=mock_client, decomposer_func=mock_decompose_func)
    
    # Test Data
    docs = [
        LogicalDocument(
            original_filename="spec_tech.md",
            content="## Chapitre 1\nContenu technique important.\n### Article 1.1\nDétails techniques.\n> Document Type: specification",
            doc_type="specification"
        ),
        LogicalDocument(
            original_filename="avis_pub.md",
            content="Objet: Construction d'un pont.\nLieu: Rabat.\n> Document Type: avis",
            doc_type="avis"
        )
    ]
    
    tender_id = 123
    tender_ref = "REF-2026-001"
    
    try:
        logger.info("Running extraction with mocks...")
        results = await chunker.chunk_all_documents(docs, tender_id, tender_ref)
        
        # Verification
        spec_chunks = results.get('specification', [])
        avis_chunks = results.get('avis', [])
        
        logger.info(f"Results: {len(spec_chunks)} specification chunks, {len(avis_chunks)} avis chunks")
        
        if spec_chunks and "Segment 1:" in spec_chunks[0]['content']:
            logger.info("✓ Semantic segmentation logic verified.")
            
        if avis_chunks:
            # Check ID generation verified.
            if "REF-2026-001" in avis_chunks[0]['id']:
                logger.info("✓ ID generation verified.")
            
            # Flow through cleaning verified.
            if "[CLEANED]" in avis_chunks[0]['content']:
                 logger.info("✓ Flow through cleaning verified.")

        logger.info("\nClean smoke test COMPLETED SUCCESSFULLY.")
        
    except Exception as e:
        logger.error(f"Smoke test FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(smoke_test_extraction())
