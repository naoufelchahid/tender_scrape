"""
Result Update Service.
Queries Fuseki for tenders past deadline without results,
scrapes marchespublics.gov.ma for PV documents,
uploads PDFs to S3, sends messages to RESULTS_OCR_QUEUE.
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import boto3
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from fuseki_client import FusekiClient
from scraper import ResultScraper

load_dotenv()

_log_dir = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(__file__), '..', 'Logs', '6_Result_Update'))
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, 'result_updater.log')),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ResultUpdater:
    def __init__(self):
        self.fuseki = FusekiClient(
            endpoint=os.getenv("JENA_ENDPOINT", "http://fuseki:3030"),
            dataset=os.getenv("JENA_DATASET", "tenders"),
            username=os.getenv("JENA_USERNAME", ""),
            password=os.getenv("JENA_PASSWORD", ""),
        )
        self.scraper = ResultScraper()
        self.bucket = os.getenv("S3_BUCKET_NAME")
        self.queue_url = os.getenv("RESULTS_OCR_QUEUE_URL")
        self.s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-3"))
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "eu-west-3"))

    def _upload_to_s3(self, local_path: str, tender_ref: str) -> str:
        """Upload result PDF to S3. Returns S3 key."""
        safe_ref = tender_ref.replace("/", "_")
        ext = Path(local_path).suffix or ".pdf"
        s3_key = f"tender_results/{safe_ref}_result{ext}"
        self.s3.upload_file(local_path, self.bucket, s3_key)
        logger.info(f"Uploaded to s3://{self.bucket}/{s3_key}")
        return s3_key

    def _send_to_queue(self, tender_ref: str, s3_key: str) -> bool:
        """Send message to RESULTS_OCR_QUEUE."""
        if not self.queue_url:
            logger.warning("RESULTS_OCR_QUEUE_URL not configured")
            return False
        message = {
            "tender_ref": tender_ref,
            "s3_paths": [s3_key],
            "bucket": self.bucket,
            "timestamp": datetime.now().isoformat(),
        }
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(message),
        )
        logger.info(f"Sent to RESULTS_OCR_QUEUE: {tender_ref}")
        return True

    async def run(self):
        """Main flow: query Fuseki → scrape → upload → queue."""
        tenders = self.fuseki.get_pending_tenders()
        if not tenders:
            logger.info("No pending tenders found")
            return

        logger.info(f"Processing {len(tenders)} tenders")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=os.getenv("HEADLESS_BROWSER", "true").lower() == "true",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--lang=fr-FR",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/91.0.4472.124 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            found = 0
            for tender in tenders:
                file_path = await self.scraper.search_and_download(
                    page,
                    search_ref=tender["search_ref"],
                    buyer_name=tender["buyer"],
                    tender_ref=tender["ref"],
                )
                if file_path:
                    s3_key = self._upload_to_s3(file_path, tender["ref"])
                    self._send_to_queue(tender["ref"], s3_key)
                    # Clean up local file
                    os.remove(file_path)
                    found += 1

            await browser.close()
            logger.info(f"Done. Found results for {found}/{len(tenders)} tenders")


if __name__ == "__main__":
    asyncio.run(ResultUpdater().run())
