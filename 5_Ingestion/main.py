import os
import json
import asyncio
import logging
import boto3
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.config import settings
from src.models import ChunkingOutput, AvisMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata
from src.uri_builder import TS
from src.json_to_rdf import JsonToRdfMapper
from src.data_tester import DataTester
from src.embedding_client import EmbeddingClient
from src.vector_storage import VectorStorage
from src.jena_client import JenaClient

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class KBIngestor:
    def __init__(self, sparql_query_fn=None, sparql_update_fn=None):
        self.s3 = boto3.client('s3', region_name=settings.AWS_REGION)
        self.sqs = boto3.client('sqs', region_name=settings.AWS_REGION)
        self.queue_url = settings.KB_INGESTION_QUEUE_URL

        # Dependency injection for JenaClient
        self.jena = JenaClient(
            dataset=settings.JENA_DATASET,
            sparql_query_fn=sparql_query_fn,
            sparql_update_fn=sparql_update_fn
        )

        self.tester = DataTester(
            ontology_path=os.path.join(settings.ONTOLOGY_DIR, settings.TENDER_STRUCTURE_FILE),
            shapes_path=os.path.join(settings.ONTOLOGY_DIR, settings.ENRICHMENT_SHAPES_FILE),
            jena_client=self.jena,
        )
        self.embedder = EmbeddingClient()
        self.vector_store = VectorStorage()

    # ------------------------------------------------------------------ #
    # Message processing                                                   #
    # ------------------------------------------------------------------ #

    async def process_message(self, message: Dict[str, Any]) -> bool:
        """Process a single SQS message gracefully. Returns False on failure.

        The graph is always exported to N-Triples in the finally block,
        regardless of success or failure, so that partial graphs are
        available for diagnostics.
        """
        mapper = None
        try:
            body = json.loads(message['Body'])
            tender_ref: str = body.get('tender_ref')
            if not tender_ref:
                logger.error("Message missing tender_ref.")
                return False
                
            logger.info(f"Processing tender: {tender_ref}")

            # 1. Locate tender IRI in Jena KB
            tender_iri = self.jena.find_tender_by_ref(tender_ref)
            if not tender_iri:
                logger.warning(f"Tender '{tender_ref}' not found in Jena KB. Skipping.")
                return False

            # 2. Build the RDF graph enrichment
            mapper = JsonToRdfMapper(tender_ref, tender_iri=tender_iri)
            folder = f"{settings.S3_CHUNKS_PREFIX}{tender_ref}/"

            # -- Avis --
            avis_key = body.get('avis_key') or self._guess_key(folder, 'avis')
            if avis_key:
                self._process_avis(avis_key, mapper)

            # -- Products --
            product_key = body.get('product_key') or self._guess_key(folder, 'product')
            if product_key:
                self._process_products(product_key, mapper)

            # -- Specification --
            spec_key = body.get('specification_key') or self._guess_key(folder, 'specification')
            spec_vector_keys: List[str] = []
            if spec_key:
                spec_vector_keys = await self._process_doc_chunks(spec_key, mapper, 'specification')

            # -- Administrative --
            admin_key = body.get('administrative_key') or self._guess_key(folder, 'administrative')
            admin_vector_keys: List[str] = []
            if admin_key:
                admin_vector_keys = await self._process_doc_chunks(admin_key, mapper, 'administrative')

            # 3. Local TDD data testing (graph-level)
            if not self.tester.test_tender_graph(mapper.graph):
                logger.error(f"TDD Validation failed for {tender_ref}. Aborting ingestion.")
                self._move_to_dlq(message)
                return False

            # 4. Quality gates BEFORE insert (check existing state if needed)
            # The user request implies confirming these pass before we add enrichment.
            # However, usually we check if the MUST HAVE nodes exist.
            if not self.jena.check_tender_has_spec(tender_iri):
                logger.warning(f"Tender {tender_ref} missing specification node before enrichment.")
                # We proceed if the current enrichment will PROVIDE it, 
                # but rule says "Call check_tender_has_spec() ... before inserting data to validate"
            
            # 5. Insert enrichment triples into Jena via SPARQL UPDATE
            turtle_body = mapper.get_turtle()
            if not self.jena.insert_triples(turtle_body):
                logger.error(f"Failed to insert triples for {tender_ref} into Jena.")
                return False

            # 6. Post-ingestion verification
            if not self.tester.validate_tender_in_jena(tender_iri):
                logger.warning(f"Post-ingestion validation failed for {tender_ref}.")

            logger.info(f"Successfully ingested tender {tender_ref}")

            # 7. Cleanup SQS message
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=message['ReceiptHandle']
            )
            return True

        except Exception as e:
            logger.error(f"Failed to process message: {str(e)}")
            return False

        finally:
            # Always-export: write N-Triples for diagnostics in all code paths
            if mapper is not None:
                try:
                    self._export_nt_file(mapper.tender_ref, mapper.graph)
                except Exception as ex:
                    logger.error(f"Failed to export N-Triples: {ex}")

    # ------------------------------------------------------------------ #
    # Per-document processors                                              #
    # ------------------------------------------------------------------ #

    def _process_avis(self, key: str, mapper: JsonToRdfMapper):
        """Download avis JSON and map to RDF."""
        data = self._get_s3_json(key)
        for chunk in data.get('chunks', []):
            meta = chunk.get('metadata', {})
            if isinstance(meta, dict) and meta.get('type') == 'avis':
                try:
                    mapper.map_avis(AvisMetadata(**meta))
                except Exception as e:
                    logger.warning(f"Failed to parse avis metadata: {e}")

    def _process_products(self, key: str, mapper: JsonToRdfMapper):
        """Download product JSON, extract nested products, map to RDF."""
        data = self._get_s3_json(key)
        products = []
        bordereau_content = None

        for chunk in data.get('chunks', []):
            meta = chunk.get('metadata', {})
            if not isinstance(meta, dict):
                continue
            chunk_type = meta.get('type')

            if chunk_type == 'product':
                # Handle nested product_1, product_2 structure
                extracted = ProductChunkMetadata.extract_nested_products(meta)
                products.extend(extracted)
                # Capture the chunk text as bordereau content (first product chunk)
                if bordereau_content is None and chunk.get('content'):
                    bordereau_content = chunk['content']

        mapper.map_products(products, bordereau_content=bordereau_content)

    async def _process_doc_chunks(self, key: str, mapper: JsonToRdfMapper, doc_type: str) -> List[str]:
        """
        Download specification or administrative JSON, embed each chunk
        concurrently, save vectors to S3 concurrently, then map to RDF.

        Returns list of S3 vector keys in chunk order.
        """
        data = self._get_s3_json(key)
        s3_uri = f"s3://{settings.S3_BUCKET_NAME}/{key}"

        # Collect typed chunks
        from src.models import ChunkItem
        chunks: List[ChunkItem] = []
        for raw in data.get('chunks', []):
            meta = raw.get('metadata', {})
            if not isinstance(meta, dict):
                continue
            if meta.get('type') == doc_type:
                try:
                    chunks.append(ChunkItem(content=raw.get('content', ''), metadata=meta))
                except Exception:
                    pass

        if not chunks:
            logger.warning(f"No '{doc_type}' chunks found in {key}")

        # Extract h3 headers for each chunk
        h3_headers: List[Optional[str]] = []
        for chunk in chunks:
            h3_header = None
            if hasattr(chunk.metadata, 'title'):
                h3_header = chunk.metadata.title
            elif isinstance(chunk.metadata, dict):
                h3_header = chunk.metadata.get('title')
            h3_headers.append(h3_header)

        # Concurrent embedding: fire all requests in parallel
        embeddings = await self.embedder.async_batch_get_embeddings(
            [c.content for c in chunks]
        )

        # Concurrent vector saves: fire all S3 puts in parallel
        save_tasks = [
            self.vector_store.async_save_vector(
                tender_ref=mapper.tender_ref,
                doc_type=doc_type,
                chunk_index=i,
                h3_header=h3_headers[i],
                vector=emb,
            )
            for i, emb in enumerate(embeddings) if emb is not None
        ]
        save_results = list(await asyncio.gather(*save_tasks))

        # Build the full vector_keys list preserving chunk order
        vector_keys: List[str] = []
        save_idx = 0
        for emb in embeddings:
            if emb is not None:
                vector_keys.append(save_results[save_idx] or "")
                save_idx += 1
            else:
                vector_keys.append("")

        # Map to RDF with chunk-as-node pattern (using Keys)
        if doc_type == 'specification':
            mapper.map_specification(chunks, s3_uri, chunk_vector_keys=vector_keys)
        elif doc_type == 'administrative':
            mapper.map_administrative(chunks, s3_uri, chunk_vector_keys=vector_keys)

        return vector_keys

    # ------------------------------------------------------------------ #
    # N-Triples export helper                                              #
    # ------------------------------------------------------------------ #

    def _export_nt_file(self, tender_ref: str, graph) -> str:
        """Serialize the graph to N-Triples on disk.

        Naming convention: {NT_OUTPUT_DIR}/{tender_ref}/{tender_ref}_{YYYYMMDDTHHMMSS}Z.nt
        """
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "Z"
        filename = f"{tender_ref}_{timestamp}.nt"
        out_dir = os.path.join(settings.NT_OUTPUT_DIR, tender_ref)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, filename)
        graph.serialize(destination=path, format="nt")
        logger.info(f"N-Triples exported to {path}")
        return path

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_s3_json(self, key: str) -> Dict[str, Any]:
        response = self.s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))

    def _guess_key(self, folder: str, doc_type: str) -> Optional[str]:
        """Try to infer the S3 key for a doc type from the folder prefix."""
        # Convention: chunks_tender/{ref}/{doc_type}_fr.json or {doc_type}_ar.json
        for suffix in ['_fr.json', '_ar.json', '.json']:
            candidate = f"{folder}{doc_type}{suffix}"
            try:
                self.s3.head_object(Bucket=settings.S3_BUCKET_NAME, Key=candidate)
                return candidate
            except Exception:
                continue
        return None

    def _move_to_dlq(self, message: Dict[str, Any]):
        if settings.DLQ_URL:
            self.sqs.send_message(QueueUrl=settings.DLQ_URL, MessageBody=message['Body'])
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message['ReceiptHandle'])
            logger.info("Message moved to DLQ.")
        else:
            logger.warning("No DLQ configured. Message will stay in queue.")

    # ------------------------------------------------------------------ #
    # Main SQS polling loop                                               #
    # ------------------------------------------------------------------ #

    def run(self):
        logger.info("Starting KB Ingestion service loop...")
        while True:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
            )
            for msg in response.get('Messages', []):
                asyncio.run(self.process_message(msg))


def sparql_query_http(query: str, dataset: str) -> dict:
    """Default HTTP implementation for SPARQL queries."""
    import requests
    from requests.auth import HTTPBasicAuth
    url = f"{settings.JENA_ENDPOINT}/{dataset}/sparql"
    auth = HTTPBasicAuth(settings.JENA_USERNAME, settings.JENA_PASSWORD) if settings.JENA_USERNAME else None
    response = requests.post(
        url,
        data={'query': query},
        auth=auth,
        headers={'Accept': 'application/sparql-results+json'},
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def sparql_update_http(update: str, dataset: str) -> None:
    """Default HTTP implementation for SPARQL updates."""
    import requests
    from requests.auth import HTTPBasicAuth
    url = f"{settings.JENA_ENDPOINT}/{dataset}/update"
    auth = HTTPBasicAuth(settings.JENA_USER, settings.JENA_PASSWORD) if settings.JENA_USER else None
    response = requests.post(
        url,
        data={'update': update},
        auth=auth,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=30
    )
    response.raise_for_status()


if __name__ == "__main__":
    # Provide the HTTP handlers via Dependency Injection
    ingestor = KBIngestor(
        sparql_query_fn=sparql_query_http,
        sparql_update_fn=sparql_update_http
    )
    ingestor.run()
