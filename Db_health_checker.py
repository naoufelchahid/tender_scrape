#!/usr/bin/env python3
"""
Database Health Checker
Checks for inconsistencies between the database and S3 bucket.
Specifically, identifies tenders in the database that are missing their corresponding ZIP file in S3.
Generates a JSON report of missing files.
"""
import os
import json
import boto3
import logging
from datetime import datetime
from typing import List, Dict
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DbHealthChecker:
    def __init__(self):
        self.s3_bucket = os.getenv('S3_BUCKET_NAME')
        self.aws_region = os.getenv('AWS_REGION', 'eu-west-3')
        self.database_url = self._build_database_url()
        
        # Initialize S3 client
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        
        # Initialize Database engine
        self.engine = create_engine(self.database_url)

    def _build_database_url(self) -> str:
        """Build database URL from environment variables"""
        db_url = os.getenv('DATABASE_URL')
        if db_url:
            return db_url
        
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME')
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')
        
        if all([db_host, db_name, db_user, db_password]):
            return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        raise ValueError("Database configuration not found in environment variables")

    def get_all_tenders(self) -> List[Dict]:
        """Fetch all tender references from the database"""
        logger.info("Fetching tenders from database...")
        query = text("SELECT id, reference FROM tenders")
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            tenders = [{'id': row[0], 'reference': row[1]} for row in result]
            
        logger.info(f"Found {len(tenders)} tenders in database")
        return tenders

    def check_s3_file_exists(self, reference: str) -> bool:
        """Check if the ZIP file for a given reference exists in S3"""
        # Convert reference to filename format (replace / with _)
        # Sanitize reference same way as scraper
        safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in reference])
        filename = f"{safe_ref}.zip"
        key = f"tender-documents/{filename}"
        
        try:
            self.s3_client.head_object(Bucket=self.s3_bucket, Key=key)
            return True
        except:
            return False

    def run_health_check(self):
        """Run the health check and generate report"""
        logger.info("=" * 60)
        logger.info("STARTING DATABASE HEALTH CHECK")
        logger.info("=" * 60)
        
        tenders = self.get_all_tenders()
        missing_files = []
        
        total = len(tenders)
        logger.info(f"Checking S3 files for {total} tenders...")
        
        for i, tender in enumerate(tenders, 1):
            ref = tender['reference']
            if not self.check_s3_file_exists(ref):
                # Sanitize reference same way as scraper
                safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in ref])
                missing_files.append({
                    'tender_id': tender['id'],
                    'reference': ref,
                    'expected_filename': f"{safe_ref}.zip"
                })
                logger.warning(f"Missing S3 file for tender: {ref}")
            
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{total}")

        # Generate Report
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_tenders_checked': total,
            'missing_files_count': len(missing_files),
            'missing_files': missing_files
        }
        
        report_filename = 'db_health_report.json'
        with open(report_filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
            
        logger.info("=" * 60)
        logger.info("HEALTH CHECK COMPLETE")
        logger.info(f"Total Tenders: {total}")
        logger.info(f"Missing Files: {len(missing_files)}")
        logger.info(f"Report saved to: {report_filename}")
        logger.info("=" * 60)

if __name__ == "__main__":
    try:
        checker = DbHealthChecker()
        checker.run_health_check()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
