import os
import json
import logging
import boto3
from typing import Dict, Any
from src.config import settings
from src.models import IngestionMessage, ChunkingOutput, AvisMetadata, ProductChunkMetadata
from src.uri_builder import TS
from src.json_to_rdf import JsonToRdfMapper
from src.data_tester import DataTester
from src.owl_reasoner import OwlReasoner
from src.embedding_client import EmbeddingClient
from src.vector_storage import VectorStorage
from src.neptune_client import NeptuneClient

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class KBIngestor:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=settings.AWS_REGION)
        self.sqs = boto3.client('sqs', region_name=settings.AWS_REGION)
        self.queue_url = settings.KB_INGESTION_QUEUE_URL
        
        # Initialize components
        self.tester = DataTester(
            ontology_path=os.path.join(settings.ONTOLOGY_DIR, settings.TENDER_STRUCTURE_FILE),
            shapes_path=os.path.join(settings.ONTOLOGY_DIR, settings.SHACL_SHAPES_FILE)
        )
        self.reasoner = OwlReasoner(
            ontology_path=os.path.join(settings.ONTOLOGY_DIR, settings.TENDER_STRUCTURE_FILE)
        )
        self.embedder = EmbeddingClient()
        self.vector_store = VectorStorage()
        self.neptune = NeptuneClient()

    def process_message(self, message: Dict[str, Any]):
        try:
            body = json.loads(message['Body'])
            data = IngestionMessage(**body)
            logger.info(f"Processing tender: {data.tender_ref} (ID: {data.tender_id})")
            
            # 1. Download and Parse JSONs
            mapper = JsonToRdfMapper(data.tender_ref)
            
            if data.avis_key:
                avis_data = self._get_s3_json(data.avis_key)
                # extraction_container saves specific structure for chunks
                # we need to find the one with AvisMetadata
                for chunk in avis_data.get('chunks', []):
                    if chunk.get('metadata', {}).get('type') == 'avis':
                        mapper.map_avis(AvisMetadata(**chunk['metadata']))
            
            if data.product_key:
                product_data = self._get_s3_json(data.product_key)
                products = []
                for chunk in product_data.get('chunks', []):
                    if chunk.get('metadata', {}).get('type') == 'product':
                        products.append(ProductChunkMetadata(**chunk['metadata']))
                mapper.map_products(products)

            if data.specification_key:
                spec_data = self._get_s3_json(data.specification_key)
                spec_uri = f"s3://{settings.S3_BUCKET_NAME}/{data.specification_key}"
                mapper.map_specification([], spec_uri)
                
                # Generate Embedding for Spec
                full_text = "\n".join([c.get('content', '') for c in spec_data.get('chunks', [])])
                vector = self.embedder.get_embedding(full_text)
                if vector:
                    v_s3_uri = self.vector_store.save_vector(data.tender_ref, "specification", vector)
                    from rdflib import Literal, XSD
                    mapper.graph.add((mapper.tender_uri, TS.Has_Vector_Ref, Literal(v_s3_uri, datatype=XSD.string)))

            if data.administrative_key:
                admin_data = self._get_s3_json(data.administrative_key)
                admin_uri = f"s3://{settings.S3_BUCKET_NAME}/{data.administrative_key}"
                mapper.map_administrative([], admin_uri)
                
                # Generate Embedding for RC
                full_text = "\n".join([c.get('content', '') for c in admin_data.get('chunks', [])])
                vector = self.embedder.get_embedding(full_text)
                if vector:
                    v_s3_uri = self.vector_store.save_vector(data.tender_ref, "administrative", vector)
                    from rdflib import Literal, XSD
                    mapper.graph.add((mapper.tender_uri, TS.Has_Vector_Ref, Literal(v_s3_uri, datatype=XSD.string)))

            # 2. TDD Data Testing
            if not self.tester.test_tender_graph(mapper.graph):
                logger.error(f"TDD Validation failed for {data.tender_ref}. Abortion ingestion.")
                self._move_to_dlq(message)
                return

            # 3. Inference
            self.reasoner.infer_and_materialize(mapper.graph)

            # 4. Neptune Ingestion
            self.neptune.upload_graph(mapper.graph)
            
            logger.info(f"Successfully ingested tender {data.tender_ref}")
            
            # 5. Cleanup
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message['ReceiptHandle'])

        except Exception as e:
            logger.exception(f"Failed to process message: {str(e)}")

    def _get_s3_json(self, key: str) -> Dict[str, Any]:
        response = self.s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))

    def _move_to_dlq(self, message: Dict[str, Any]):
        if settings.DLQ_URL:
            # Simple send to DLQ
            self.sqs.send_message(QueueUrl=settings.DLQ_URL, MessageBody=message['Body'])
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message['ReceiptHandle'])
            logger.info("Message moved to DLQ.")
        else:
            logger.warning("No DLQ configured. Message will stay in queue.")

    def run(self):
        logger.info("Starting KB Ingestion service loop...")
        while True:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )
            
            messages = response.get('Messages', [])
            for msg in messages:
                self.process_message(msg)

if __name__ == "__main__":
    ingestor = KBIngestor()
    ingestor.run()
