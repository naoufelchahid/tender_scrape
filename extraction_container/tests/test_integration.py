import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.cleaning import DocumentCleaners, LogicalDocument
from src.models import TenderMetadata, LotMetadata, ProductItem


class TestExtractionContainer(unittest.TestCase):

    def test_document_cleaner_split(self):
        """Test splitting concatenated markdown files."""
        content = """# File: doc1.txt
content1
---
# File: doc2.bdp
content2"""
        
        docs = DocumentCleaners.split_concatenated_file(content)
        
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].original_filename, "doc1.txt")
        self.assertEqual(docs[1].doc_type, "product")
        
    def test_document_classification(self):
        """Test document type classification."""
        self.assertEqual(DocumentCleaners.classify_document("cps.docx"), "specification")
        self.assertEqual(DocumentCleaners.classify_document("rc.pdf"), "administrative")
        self.assertEqual(DocumentCleaners.classify_document("bordereau_prix.xlsx"), "product")
        self.assertEqual(DocumentCleaners.classify_document("avis_appel_offres.pdf"), "avis")
        
    def test_excluded_document_types(self):
        """Test that engagement and declaration types are properly classified."""
        self.assertEqual(DocumentCleaners.classify_document("acte_engagement.pdf"), "engagement")
        self.assertEqual(DocumentCleaners.classify_document("declaration_honneur.pdf"), "declaration")
        self.assertEqual(DocumentCleaners.classify_document("attestation_fiscale.pdf"), "declaration")
    
    def test_content_based_classification(self):
        """Test content-based classification for ambiguous filenames."""
        # BDP detection from content
        bdp_content = "N° prix | Désignation | Quantité | Prix"
        self.assertEqual(DocumentCleaners.classify_document("document.pdf", bdp_content), "product")
        
        # CPS detection from content
        cps_content = "ARTICLE 5 - DÉLAI D'EXÉCUTION\nLe délai est fixé à 60 jours..."
        self.assertEqual(DocumentCleaners.classify_document("document.pdf", cps_content), "specification")


class TestLLMChunker(unittest.TestCase):
    
    @patch('src.llm_chunker.boto3.client')
    def test_llm_chunker_init(self, MockBoto):
        """Test LLMChunker initialization."""
        from src.llm_chunker import LLMChunker
        
        chunker = LLMChunker('eu-west-3', 'eu.amazon.nova-micro-v1:0')
        
        self.assertEqual(chunker.region_name, 'eu-west-3')
        self.assertEqual(chunker.model_id, 'eu.amazon.nova-micro-v1:0')
        MockBoto.assert_called_with('bedrock-runtime', region_name='eu-west-3')
    
    @patch('src.llm_chunker.boto3.client')
    def test_excluded_documents_skipped(self, MockBoto):
        """Test that excluded documents are skipped during chunking."""
        from src.llm_chunker import LLMChunker
        
        chunker = LLMChunker('eu-west-3')
        
        docs = [
            LogicalDocument("acte_engagement.pdf", "content", "engagement"),
            LogicalDocument("declaration_honneur.pdf", "content", "declaration"),
        ]
        
        chunks = chunker.chunk_all_documents(docs, tender_id=123)
        
        # Both documents should be skipped
        self.assertEqual(len(chunks), 0)
    
    @patch('src.llm_chunker.boto3.client')
    def test_standard_chunking_fallback(self, MockBoto):
        """Test standard chunking for 'other' document types."""
        from src.llm_chunker import LLMChunker
        
        chunker = LLMChunker('eu-west-3')
        
        # Long content to ensure chunking happens
        long_content = "This is test content. " * 200
        docs = [LogicalDocument("unknown_doc.pdf", long_content, "other")]
        
        chunks = chunker.chunk_all_documents(docs, tender_id=123)
        
        # Should produce chunks via standard splitting
        self.assertGreater(len(chunks), 0)
        self.assertEqual(chunks[0]['metadata']['type'], 'other')
    
    @patch('src.llm_chunker.boto3.client')
    def test_chunk_marker_parsing(self, MockBoto):
        """Test parsing of LLM chunk markers."""
        from src.llm_chunker import LLMChunker
        
        chunker = LLMChunker('eu-west-3')
        
        response = """Some preamble text
<!-- CHUNK:product:item_57 -->
| 57 | Pc portable HP | Intel Core i5 | 10 | u |
<!-- /CHUNK -->
<!-- CHUNK:product:item_58 -->
| 58 | Imprimante laser | HP LaserJet | 5 | u |
<!-- /CHUNK -->
"""
        
        doc = LogicalDocument("bdp.pdf", "content", "product")
        chunks = chunker._parse_chunk_markers(response, doc, tender_id=123)
        
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]['metadata']['type'], 'product')
        self.assertEqual(chunks[0]['metadata']['chunk_id'], 'item_57')
        self.assertIn('Pc portable HP', chunks[0]['content'])


if __name__ == '__main__':
    unittest.main()
