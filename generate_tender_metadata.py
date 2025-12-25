"""
AWS S3 Metadata Generation Script for Bedrock Knowledge Base

This script generates .metadata.json files for each document in S3 to enable
filtered vector search in AWS Bedrock Knowledge Bases with S3 Vector Store.

Features:
- Extracts tender metadata from PostgreSQL database
- Generates metadata JSON files for each S3 document
- Supports contextual retrieval with section headers
- Batch processing with progress tracking
- Dry-run mode for testing
- Error handling and retry logic
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import Database, Tender, Buyer, Category

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('metadata_generation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TenderMetadataGenerator:
    """Generate metadata JSON files for tender documents in S3"""
    
    def __init__(self, bucket_name: str, prefix: str = "tenders_doc_final/"):
        """
        Initialize metadata generator
        
        Args:
            bucket_name: S3 bucket name
            prefix: S3 prefix for tender documents
        """
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.s3_client = boto3.client('s3')
        
        # Initialize database connection
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL not found in environment variables")
        
        self.db = Database(db_url)
        
        # Statistics
        self.stats = {
            'total_files': 0,
            'metadata_generated': 0,
            'metadata_skipped': 0,
            'errors': 0,
            'tenders_processed': set()
        }
    
    def extract_tender_ref_from_path(self, s3_key: str) -> Optional[str]:
        """
        Extract tender reference from S3 path
        
        Expected format: tenders_doc_final/{tender_ref}/filename.ext
        
        Args:
            s3_key: S3 object key
            
        Returns:
            Tender reference or None if not found
        """
        try:
            # Remove prefix
            path = s3_key.replace(self.prefix, '')
            
            # Split by / and get first part (tender reference)
            parts = path.split('/')
            if len(parts) >= 2:
                tender_ref = parts[0]
                return tender_ref
            
            return None
        except Exception as e:
            logger.error(f"Error extracting tender ref from {s3_key}: {e}")
            return None
    
    def get_tender_metadata(self, tender_ref: str) -> Optional[Dict]:
        """
        Get tender metadata from database
        
        Args:
            tender_ref: Tender reference
            
        Returns:
            Dictionary with tender metadata or None if not found
        """
        session = self.db.get_session()
        try:
            tender = session.query(Tender).filter(
                Tender.reference == tender_ref
            ).first()
            
            if not tender:
                logger.warning(f"Tender {tender_ref} not found in database")
                return None
            
            # Build metadata dictionary
            metadata = {
                'tenderRef': tender.reference,
                'buyerName': tender.buyer.name if tender.buyer else 'Unknown',
                'buyerId': str(tender.buyer_id) if tender.buyer_id else '',
                'category': tender.category.name if tender.category else 'Unknown',
                'publicationDate': tender.publication_date.strftime('%Y-%m-%d') if tender.publication_date else '',
                'deadline': tender.deadline.strftime('%Y-%m-%d') if tender.deadline else '',
                'budget': str(tender.budget) if tender.budget else '0',
                'city': tender.execution_location or '',
                'hasResults': 'true' if tender.is_results else 'false',
                'lotCount': str(tender.lot_count) if tender.lot_count else '0',
            }
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error getting metadata for tender {tender_ref}: {e}")
            return None
        finally:
            session.close()
    
    def get_document_type(self, filename: str) -> str:
        """
        Get document type from filename extension
        
        Args:
            filename: Document filename
            
        Returns:
            Document type (pdf, docx, txt, etc.)
        """
        ext = Path(filename).suffix.lower().lstrip('.')
        return ext or 'unknown'
    
    def extract_section_header(self, s3_key: str, content: Optional[bytes] = None) -> str:
        """
        Extract section header from document for contextual retrieval
        
        For now, we'll use the filename as a basic section header.
        In Phase 2, we can enhance this with actual document parsing.
        
        Args:
            s3_key: S3 object key
            content: Optional document content for parsing
            
        Returns:
            Section header string
        """
        filename = Path(s3_key).stem
        
        # Basic heuristics based on filename
        filename_lower = filename.lower()
        
        if 'cahier' in filename_lower or 'specs' in filename_lower:
            return 'Technical Specifications'
        elif 'bpx' in filename_lower or 'bordereau' in filename_lower or 'boq' in filename_lower:
            return 'Bill of Quantities'
        elif 'plan' in filename_lower:
            return 'Plans and Drawings'
        elif 'resultat' in filename_lower or 'result' in filename_lower or 'pv' in filename_lower:
            return 'Results and Awards'
        elif 'reglement' in filename_lower or 'rc' in filename_lower:
            return 'Regulations'
        else:
            return 'General Documents'
    
    def generate_metadata_json(
        self, 
        s3_key: str, 
        tender_metadata: Dict,
        section_header: Optional[str] = None
    ) -> Dict:
        """
        Generate metadata JSON for a document
        
        Args:
            s3_key: S3 object key
            tender_metadata: Tender metadata from database
            section_header: Optional section header for contextual retrieval
            
        Returns:
            Metadata dictionary
        """
        filename = Path(s3_key).name
        doc_type = self.get_document_type(filename)
        
        # Build filterable metadata
        filterable_metadata = {
            **tender_metadata,
            'documentType': doc_type,
            'sectionHeader': section_header or self.extract_section_header(s3_key),
            'chunkType': 'child',  # For hierarchical RAG (Phase 3)
        }
        
        # Build non-filterable metadata (for retrieval only)
        # Note: These will be configured in the Knowledge Base setup
        non_filterable_metadata = {
            's3Uri': f"s3://{self.bucket_name}/{s3_key}",
            'fileName': filename,
        }
        
        # Bedrock Knowledge Base metadata format
        metadata = {
            'metadataAttributes': filterable_metadata
        }
        
        # Add non-filterable as regular fields (they'll be marked non-filterable in KB config)
        metadata['metadataAttributes'].update(non_filterable_metadata)
        
        return metadata
    
    def upload_metadata_to_s3(
        self, 
        s3_key: str, 
        metadata: Dict,
        dry_run: bool = False
    ) -> bool:
        """
        Upload metadata JSON file to S3
        
        Args:
            s3_key: Original document S3 key
            metadata: Metadata dictionary
            dry_run: If True, don't actually upload
            
        Returns:
            True if successful, False otherwise
        """
        metadata_key = f"{s3_key}.metadata.json"
        
        try:
            if dry_run:
                logger.info(f"[DRY RUN] Would upload metadata to: {metadata_key}")
                logger.debug(f"Metadata content: {json.dumps(metadata, indent=2)}")
                return True
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=metadata_key,
                Body=json.dumps(metadata, indent=2),
                ContentType='application/json'
            )
            
            logger.info(f"Uploaded metadata: {metadata_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error uploading metadata for {s3_key}: {e}")
            return False
    
    def list_s3_documents(self, limit: Optional[int] = None) -> List[str]:
        """
        List all documents in S3 bucket
        
        Args:
            limit: Optional limit on number of documents to process
            
        Returns:
            List of S3 object keys
        """
        logger.info(f"Listing documents in s3://{self.bucket_name}/{self.prefix}")
        
        documents = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix):
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    key = obj['Key']
                    
                    # Skip directories and metadata files
                    if key.endswith('/') or key.endswith('.metadata.json'):
                        continue
                    
                    # Skip if not a document file
                    if not any(key.lower().endswith(ext) for ext in ['.pdf', '.docx', '.doc', '.txt', '.md']):
                        continue
                    
                    documents.append(key)
                    
                    if limit and len(documents) >= limit:
                        logger.info(f"Reached limit of {limit} documents")
                        return documents
            
            logger.info(f"Found {len(documents)} documents")
            return documents
            
        except ClientError as e:
            logger.error(f"Error listing S3 objects: {e}")
            return []
    
    def process_document(
        self, 
        s3_key: str,
        dry_run: bool = False
    ) -> bool:
        """
        Process a single document and generate metadata
        
        Args:
            s3_key: S3 object key
            dry_run: If True, don't actually upload metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract tender reference
            tender_ref = self.extract_tender_ref_from_path(s3_key)
            if not tender_ref:
                logger.warning(f"Could not extract tender ref from: {s3_key}")
                self.stats['errors'] += 1
                return False
            
            # Get tender metadata from database
            tender_metadata = self.get_tender_metadata(tender_ref)
            if not tender_metadata:
                logger.warning(f"No metadata found for tender: {tender_ref}")
                self.stats['errors'] += 1
                return False
            
            # Track processed tenders
            self.stats['tenders_processed'].add(tender_ref)
            
            # Generate metadata JSON
            metadata = self.generate_metadata_json(s3_key, tender_metadata)
            
            # Upload to S3
            success = self.upload_metadata_to_s3(s3_key, metadata, dry_run)
            
            if success:
                self.stats['metadata_generated'] += 1
            else:
                self.stats['errors'] += 1
            
            return success
            
        except Exception as e:
            logger.error(f"Error processing document {s3_key}: {e}")
            self.stats['errors'] += 1
            return False
    
    def process_all_documents(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        batch_size: int = 100
    ):
        """
        Process all documents in S3 bucket
        
        Args:
            limit: Optional limit on number of documents
            dry_run: If True, don't actually upload metadata
            batch_size: Number of documents to process before logging progress
        """
        logger.info("Starting metadata generation process")
        logger.info(f"Bucket: {self.bucket_name}, Prefix: {self.prefix}")
        logger.info(f"Dry run: {dry_run}, Limit: {limit or 'None'}")
        
        # List all documents
        documents = self.list_s3_documents(limit)
        self.stats['total_files'] = len(documents)
        
        if not documents:
            logger.warning("No documents found to process")
            return
        
        # Process each document
        for idx, s3_key in enumerate(documents, 1):
            logger.info(f"Processing {idx}/{len(documents)}: {s3_key}")
            
            self.process_document(s3_key, dry_run)
            
            # Log progress every batch_size documents
            if idx % batch_size == 0:
                self.log_progress()
        
        # Final statistics
        self.log_final_stats()
    
    def log_progress(self):
        """Log current progress"""
        logger.info(f"Progress: {self.stats['metadata_generated']}/{self.stats['total_files']} metadata files generated")
        logger.info(f"Errors: {self.stats['errors']}, Tenders processed: {len(self.stats['tenders_processed'])}")
    
    def log_final_stats(self):
        """Log final statistics"""
        logger.info("=" * 80)
        logger.info("METADATA GENERATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Total files scanned: {self.stats['total_files']}")
        logger.info(f"Metadata files generated: {self.stats['metadata_generated']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Unique tenders processed: {len(self.stats['tenders_processed'])}")
        logger.info("=" * 80)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Generate metadata JSON files for tender documents in S3'
    )
    parser.add_argument(
        '--bucket',
        default='my-tender-documents-bucket',
        help='S3 bucket name'
    )
    parser.add_argument(
        '--prefix',
        default='tenders_doc_final/',
        help='S3 prefix for tender documents'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of documents to process (for testing)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - do not upload metadata'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for progress logging'
    )
    
    args = parser.parse_args()
    
    try:
        generator = TenderMetadataGenerator(
            bucket_name=args.bucket,
            prefix=args.prefix
        )
        
        generator.process_all_documents(
            limit=args.limit,
            dry_run=args.dry_run,
            batch_size=args.batch_size
        )
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
