"""
Result Ingestion Service.
Polls RESULTS_INGESTION_QUEUE, fetches OCR markdown from S3,
extracts structured data via Ollama, maps to RDF, validates with SHACL,
and inserts into Jena Fuseki.
"""
import os
import json
import logging
import time
from typing import Optional

import boto3
from dotenv import load_dotenv

from ollama_client import OllamaClient
from rdf_mapper import ResultRdfMapper
from shacl_validator import ShaclValidator
from jena_client import JenaClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ResultIngestor:
    def __init__(self):
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.queue_url = os.getenv("RESULTS_INGESTION_QUEUE_URL")
        self.bucket = os.getenv("S3_BUCKET_NAME")

        self.ollama = OllamaClient(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            model=os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b"),
        )
        self.validator = ShaclValidator(
            shapes_path=os.path.join(os.path.dirname(__file__), "ontology", "shapes_results.ttl"),
        )
        self.jena = JenaClient(
            endpoint=os.getenv("JENA_ENDPOINT", "http://fuseki:3030"),
            dataset=os.getenv("JENA_DATASET", "tenders"),
            username=os.getenv("JENA_USERNAME", ""),
            password=os.getenv("JENA_PASSWORD", ""),
        )

        if not self.queue_url:
            raise ValueError("RESULTS_INGESTION_QUEUE_URL is required")
        logger.info("ResultIngestor initialized")

    def _fetch_markdown(self, s3_key: str) -> Optional[str]:
        """Download markdown content from S3."""
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
            return resp["Body"].read().decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to fetch {s3_key}: {e}")
            return None

    def process_message(self, message: dict) -> bool:
        """Process one SQS message end-to-end."""
        body = json.loads(message["Body"])
        tender_ref = body.get("tender_ref")
        markdown_key = body.get("markdown_s3_key")

        if not tender_ref or not markdown_key:
            logger.error(f"Invalid message: {body}")
            return False

        logger.info(f"Processing result for {tender_ref}")

        # 1. Verify tender exists in Jena
        tender_iri = self.jena.find_tender_iri(tender_ref)
        if not tender_iri:
            logger.error(f"Tender {tender_ref} not found in Jena — deleting message")
            self._delete_message(message)
            return False

        # 2. Fetch markdown from S3
        markdown = self._fetch_markdown(markdown_key)
        if not markdown:
            return False

        # 3. Extract structured data via Ollama
        extracted = self.ollama.extract_structured_data(markdown, tender_ref)
        if not extracted or not extracted.get("lots"):
            logger.error(f"Extraction failed for {tender_ref}")
            return False

        # 4. Map to RDF
        mapper = ResultRdfMapper(tender_ref, tender_iri)
        mapper.map_results(extracted)

        # 5. SHACL + logical validation
        if not self.validator.validate(mapper.graph):
            logger.error(f"Validation failed for {tender_ref} — skipping ingestion")
            return False

        # 6. Insert result triples into Jena
        ntriples = mapper.get_ntriples()
        if not self.jena.insert_triples(ntriples):
            logger.error(f"Failed to insert triples for {tender_ref}")
            return False

        # 7. Set ts:Is_Result = true on the tender node
        is_result_nt = mapper.get_is_result_triple()
        if not self.jena.insert_triples(is_result_nt):
            logger.warning(f"Failed to set Is_Result for {tender_ref}")

        # 8. Post-ingestion quality gates
        has_result = self.jena.check_tender_has_result(tender_iri)
        has_bids = self.jena.check_result_has_bids(tender_iri)
        if not has_result or not has_bids:
            logger.warning(f"Post-ingestion check failed for {tender_ref}")

        # 9. Delete SQS message
        self._delete_message(message)
        logger.info(f"Successfully ingested results for {tender_ref}")
        return True

    def _delete_message(self, message: dict) -> None:
        self.sqs.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )

    def run(self):
        """Main polling loop."""
        logger.info("Starting Result Ingestion service...")
        while True:
            try:
                resp = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                )
                for msg in resp.get("Messages", []):
                    self.process_message(msg)
            except KeyboardInterrupt:
                logger.info("Shutting down")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(5)


if __name__ == "__main__":
    ResultIngestor().run()
