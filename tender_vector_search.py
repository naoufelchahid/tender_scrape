"""
AWS Bedrock Knowledge Base Query SDK for Tender Documents

This module provides a Python SDK for querying the Bedrock Knowledge Base
with advanced RAG features including:
- Multi-query expansion (multilingual)
- Metadata filtering
- Reranking
- Hierarchical retrieval
- Agentic query routing

Usage:
    from tender_vector_search import TenderVectorSearch
    
    search = TenderVectorSearch(
        knowledge_base_id='YOUR_KB_ID',
        region='us-east-1'
    )
    
    results = search.search_tender_docs(
        query="What are the concrete specifications?",
        tender_ref="AO-123-2024"
    )
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QueryStrategy(Enum):
    """Query routing strategies"""
    METADATA_ONLY = "metadata_only"
    SEMANTIC_ONLY = "semantic_only"
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    """Search result from Knowledge Base"""
    content: str
    metadata: Dict
    relevance_score: float
    source_uri: str


class TenderVectorSearch:
    """
    AWS Bedrock Knowledge Base query interface for tender documents
    """
    
    def __init__(
        self,
        knowledge_base_id: str,
        region: str = 'us-east-1',
        enable_multi_query: bool = True,
        enable_reranking: bool = False
    ):
        """
        Initialize the search client
        
        Args:
            knowledge_base_id: Bedrock Knowledge Base ID
            region: AWS region
            enable_multi_query: Enable multilingual query expansion
            enable_reranking: Enable Cohere reranking (Phase 2)
        """
        self.knowledge_base_id = knowledge_base_id
        self.region = region
        self.enable_multi_query = enable_multi_query
        self.enable_reranking = enable_reranking
        
        # Initialize AWS clients
        self.bedrock_runtime = boto3.client(
            'bedrock-agent-runtime',
            region_name=region
        )
        
        self.bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=region
        )
    
    def _expand_query_multilingual(self, query: str) -> List[str]:
        """
        Expand query into multiple language variations
        
        Args:
            query: Original user query
            
        Returns:
            List of query variations (French, Arabic, English)
        """
        if not self.enable_multi_query:
            return [query]
        
        try:
            prompt = f"""Given this tender search query: "{query}"

Generate 3 variations to improve cross-language retrieval:
1. French version (if not already French)
2. Arabic version (if applicable to Moroccan tenders)
3. Technical/formal variation

Return ONLY a JSON array of strings, no other text:
["query1", "query2", "query3"]
"""
            
            response = self.bedrock_client.invoke_model(
                modelId='anthropic.claude-3-haiku-20240307-v1:0',
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body['content'][0]['text']
            
            # Parse JSON array from response
            queries = json.loads(content)
            
            # Always include original query
            if query not in queries:
                queries.insert(0, query)
            
            logger.info(f"Expanded query into {len(queries)} variations")
            return queries
            
        except Exception as e:
            logger.error(f"Error expanding query: {e}")
            return [query]  # Fallback to original query
    
    def _build_metadata_filter(self, **filters) -> Optional[Dict]:
        """
        Build metadata filter for Knowledge Base query
        
        Args:
            **filters: Metadata filters (tenderRef, buyerName, category, etc.)
            
        Returns:
            Filter dictionary for Bedrock API
        """
        if not filters:
            return None
        
        # Build filter conditions
        conditions = []
        
        for key, value in filters.items():
            if value is not None:
                conditions.append({
                    'equals': {
                        'key': key,
                        'value': str(value)
                    }
                })
        
        if not conditions:
            return None
        
        if len(conditions) == 1:
            return conditions[0]
        
        # Multiple conditions - use AND
        return {'and': conditions}
    
    def _retrieve_from_kb(
        self,
        query: str,
        metadata_filter: Optional[Dict] = None,
        num_results: int = 10
    ) -> List[Dict]:
        """
        Retrieve results from Knowledge Base
        
        Args:
            query: Search query
            metadata_filter: Optional metadata filter
            num_results: Number of results to retrieve
            
        Returns:
            List of retrieval results
        """
        try:
            retrieval_config = {
                'vectorSearchConfiguration': {
                    'numberOfResults': num_results
                }
            }
            
            if metadata_filter:
                retrieval_config['vectorSearchConfiguration']['filter'] = metadata_filter
            
            response = self.bedrock_runtime.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={'text': query},
                retrievalConfiguration=retrieval_config
            )
            
            return response.get('retrievalResults', [])
            
        except ClientError as e:
            logger.error(f"Error retrieving from Knowledge Base: {e}")
            return []
    
    def _rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_n: int = 5
    ) -> List[Dict]:
        """
        Rerank results using Cohere Rerank
        
        Args:
            query: Original query
            results: Retrieved results
            top_n: Number of top results to return
            
        Returns:
            Reranked results
        """
        if not self.enable_reranking or not results:
            return results[:top_n]
        
        try:
            # Extract documents for reranking
            documents = [r['content']['text'] for r in results]
            
            response = self.bedrock_client.invoke_model(
                modelId='cohere.rerank-v3-5:0',
                body=json.dumps({
                    'query': query,
                    'documents': documents,
                    'top_n': top_n,
                    'return_documents': True
                })
            )
            
            rerank_response = json.loads(response['body'].read())
            reranked_results = []
            
            for item in rerank_response['results']:
                original_result = results[item['index']]
                original_result['relevance_score'] = item['relevance_score']
                reranked_results.append(original_result)
            
            logger.info(f"Reranked {len(results)} results to top {len(reranked_results)}")
            return reranked_results
            
        except Exception as e:
            logger.error(f"Error reranking results: {e}")
            return results[:top_n]
    
    def _deduplicate_results(self, results: List[Dict]) -> List[Dict]:
        """
        Deduplicate results from multiple queries
        
        Args:
            results: List of results
            
        Returns:
            Deduplicated results
        """
        seen_uris = set()
        unique_results = []
        
        for result in results:
            uri = result.get('location', {}).get('s3Location', {}).get('uri', '')
            
            if uri and uri not in seen_uris:
                seen_uris.add(uri)
                unique_results.append(result)
        
        return unique_results
    
    def _format_results(self, results: List[Dict]) -> List[SearchResult]:
        """
        Format results into SearchResult objects
        
        Args:
            results: Raw results from Knowledge Base
            
        Returns:
            List of SearchResult objects
        """
        formatted = []
        
        for result in results:
            try:
                content = result.get('content', {}).get('text', '')
                metadata = result.get('metadata', {})
                score = result.get('relevance_score', result.get('score', 0.0))
                
                # Extract S3 URI
                s3_location = result.get('location', {}).get('s3Location', {})
                source_uri = s3_location.get('uri', '')
                
                formatted.append(SearchResult(
                    content=content,
                    metadata=metadata,
                    relevance_score=score,
                    source_uri=source_uri
                ))
            except Exception as e:
                logger.error(f"Error formatting result: {e}")
                continue
        
        return formatted
    
    def search_tender_docs(
        self,
        query: str,
        tender_ref: str,
        num_results: int = 10
    ) -> List[SearchResult]:
        """
        Search within a specific tender's documents
        
        Args:
            query: Search query
            tender_ref: Tender reference (e.g., "AO-123-2024")
            num_results: Number of results to return
            
        Returns:
            List of SearchResult objects
        """
        logger.info(f"Searching tender {tender_ref} for: {query}")
        
        # Build metadata filter
        metadata_filter = self._build_metadata_filter(tenderRef=tender_ref)
        
        # Expand query if enabled
        queries = self._expand_query_multilingual(query)
        
        # Retrieve results for each query variation
        all_results = []
        for q in queries:
            results = self._retrieve_from_kb(
                query=q,
                metadata_filter=metadata_filter,
                num_results=num_results
            )
            all_results.extend(results)
        
        # Deduplicate
        unique_results = self._deduplicate_results(all_results)
        
        # Rerank if enabled
        final_results = self._rerank_results(query, unique_results, num_results)
        
        # Format and return
        return self._format_results(final_results)
    
    def search_by_buyer(
        self,
        query: str,
        buyer_name: str,
        category: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search across all tenders from a specific buyer
        
        Args:
            query: Search query
            buyer_name: Buyer name (e.g., "ONCF")
            category: Optional category filter (e.g., "Travaux")
            limit: Number of results to return
            
        Returns:
            List of SearchResult objects
        """
        logger.info(f"Searching buyer {buyer_name} for: {query}")
        
        # Build metadata filter
        filters = {'buyerName': buyer_name}
        if category:
            filters['category'] = category
        
        metadata_filter = self._build_metadata_filter(**filters)
        
        # Expand query
        queries = self._expand_query_multilingual(query)
        
        # Retrieve and process
        all_results = []
        for q in queries:
            results = self._retrieve_from_kb(
                query=q,
                metadata_filter=metadata_filter,
                num_results=limit
            )
            all_results.extend(results)
        
        unique_results = self._deduplicate_results(all_results)
        final_results = self._rerank_results(query, unique_results, limit)
        
        return self._format_results(final_results)
    
    def search_by_category(
        self,
        query: str,
        category: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search within a category with optional date range
        
        Args:
            query: Search query
            category: Category (e.g., "Travaux", "Fournitures", "Services")
            date_from: Optional start date (YYYY-MM-DD)
            date_to: Optional end date (YYYY-MM-DD)
            limit: Number of results to return
            
        Returns:
            List of SearchResult objects
        """
        logger.info(f"Searching category {category} for: {query}")
        
        # Build metadata filter
        metadata_filter = self._build_metadata_filter(category=category)
        
        # Note: Date range filtering would require custom logic
        # as Bedrock filters don't support range queries directly
        # This would be implemented in Phase 3 with agentic routing
        
        # Expand query
        queries = self._expand_query_multilingual(query)
        
        # Retrieve and process
        all_results = []
        for q in queries:
            results = self._retrieve_from_kb(
                query=q,
                metadata_filter=metadata_filter,
                num_results=limit
            )
            all_results.extend(results)
        
        unique_results = self._deduplicate_results(all_results)
        final_results = self._rerank_results(query, unique_results, limit)
        
        return self._format_results(final_results)
    
    def get_context_for_llm(
        self,
        query: str,
        tender_ref: Optional[str] = None,
        **filters
    ) -> str:
        """
        Get formatted context for LLM from search results
        
        Args:
            query: Search query
            tender_ref: Optional tender reference
            **filters: Additional metadata filters
            
        Returns:
            Formatted context string for LLM
        """
        # Search based on filters
        if tender_ref:
            results = self.search_tender_docs(query, tender_ref)
        else:
            metadata_filter = self._build_metadata_filter(**filters)
            queries = self._expand_query_multilingual(query)
            
            all_results = []
            for q in queries:
                results = self._retrieve_from_kb(
                    query=q,
                    metadata_filter=metadata_filter,
                    num_results=10
                )
                all_results.extend(results)
            
            unique_results = self._deduplicate_results(all_results)
            final_results = self._rerank_results(query, unique_results, 5)
            results = self._format_results(final_results)
        
        # Format context
        context_parts = []
        for idx, result in enumerate(results, 1):
            context_parts.append(f"[Source {idx}]")
            context_parts.append(f"Tender: {result.metadata.get('tenderRef', 'Unknown')}")
            context_parts.append(f"Document: {result.metadata.get('fileName', 'Unknown')}")
            context_parts.append(f"Section: {result.metadata.get('sectionHeader', 'General')}")
            context_parts.append(f"Content:\n{result.content}")
            context_parts.append("---")
        
        return "\n".join(context_parts)


def main():
    """Example usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Search tender documents')
    parser.add_argument('--kb-id', required=True, help='Knowledge Base ID')
    parser.add_argument('--query', required=True, help='Search query')
    parser.add_argument('--tender-ref', help='Tender reference')
    parser.add_argument('--buyer', help='Buyer name')
    parser.add_argument('--category', help='Category')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    
    args = parser.parse_args()
    
    # Initialize search client
    search = TenderVectorSearch(
        knowledge_base_id=args.kb_id,
        region=args.region,
        enable_multi_query=True,
        enable_reranking=False  # Enable in Phase 2
    )
    
    # Search based on parameters
    if args.tender_ref:
        results = search.search_tender_docs(args.query, args.tender_ref)
    elif args.buyer:
        results = search.search_by_buyer(args.query, args.buyer, args.category)
    elif args.category:
        results = search.search_by_category(args.query, args.category)
    else:
        print("Please specify --tender-ref, --buyer, or --category")
        return
    
    # Print results
    print(f"\nFound {len(results)} results:\n")
    for idx, result in enumerate(results, 1):
        print(f"Result {idx}:")
        print(f"  Tender: {result.metadata.get('tenderRef', 'Unknown')}")
        print(f"  Buyer: {result.metadata.get('buyerName', 'Unknown')}")
        print(f"  Document: {result.metadata.get('fileName', 'Unknown')}")
        print(f"  Section: {result.metadata.get('sectionHeader', 'General')}")
        print(f"  Relevance: {result.relevance_score:.3f}")
        print(f"  Content preview: {result.content[:200]}...")
        print()


if __name__ == '__main__':
    main()
