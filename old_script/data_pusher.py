#!/usr/bin/env python3
"""
Data Pusher Script for Tender Scraper
Pushes tender JSON data to AWS RDS PostgreSQL and uploads ZIP files to S3
"""
import os
import json
import boto3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError
from database.models import Database, Tender, TenderDocument, Buyer, Category

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_pusher.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def generate_initials(name):
    """Generate initials from buyer name - New logic for better matching"""
    if not name:
        return "UNK"
    
    # Common words to ignore
    ignore = ['LE', 'LA', 'LES', 'DE', 'DES', 'DU', 'ET', 'EN', 'AU', 'AUX', 'A']
    
    # Clean name
    clean_name = name.upper().replace('-', ' ').replace('_', ' ').replace("'", " ")
    words = [w for w in clean_name.split() if w not in ignore and len(w) > 1]
    
    if not words:
        return name[:3].upper()
    
    if len(words) == 1:
        return words[0][:3]
    
    # New logic:
    # - If 2 or 3 words: use the entire words
    # - If more than 3 words: take first 3 letters from ALL words
    if 2 <= len(words) <= 3:
        # Use full words joined together
        return "".join(words)
    else:
        # Take first 3 letters from ALL words
        return "".join([w[:3] for w in words])


class DataPusher:
    """Pushes tender data to AWS RDS and S3"""
    
    def __init__(
        self,
        json_file: str = 'tenders.json',
        downloads_dir: str = 'downloads',
        aws_region: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        database_url: Optional[str] = None
    ):
        """
        Initialize DataPusher
        
        Args:
            json_file: Path to tenders JSON file
            downloads_dir: Directory containing downloaded ZIP files
            aws_region: AWS region (defaults to env var)
            s3_bucket: S3 bucket name (defaults to env var)
            database_url: Database connection URL (defaults to env var)
        """
        self.json_file = Path(json_file)
        self.downloads_dir = Path(downloads_dir)
        
        # AWS Configuration
        self.aws_region = aws_region or os.getenv('AWS_REGION', 'eu-west-3')
        self.s3_bucket = s3_bucket or os.getenv('S3_BUCKET_NAME')
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            region_name=self.aws_region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        # Initialize Database
        self.database_url = database_url or self._build_database_url()
        self.db = Database(self.database_url)
        
        # Statistics
        self.stats = {
            'tenders_processed': 0,
            'tenders_inserted': 0,
            'tenders_updated': 0,
            'tenders_failed': 0,
            'files_uploaded': 0,
            'files_failed': 0,
            'files_skipped': 0
        }
        
        logger.info(f"DataPusher initialized")
        logger.info(f"S3 Bucket: {self.s3_bucket}")
        logger.info(f"AWS Region: {self.aws_region}")
        logger.info(f"Database: {self.database_url.split('@')[1] if '@' in self.database_url else 'configured'}")
    
    def _build_database_url(self) -> str:
        """Build database URL from environment variables or terraform outputs"""
        db_url = os.getenv('DATABASE_URL')
        
        if db_url:
            return db_url
        
        # Try building from individual components
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME')
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')
        
        if all([db_host, db_name, db_user, db_password]):
            return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        raise ValueError(
            "Database configuration not found. Please set DATABASE_URL or "
            "DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables"
        )
    
    def load_tenders_json(self) -> List[Dict]:
        """Load tenders from JSON file"""
        logger.info(f"Loading tenders from {self.json_file}")
        
        if not self.json_file.exists():
            logger.error(f"JSON file not found: {self.json_file}")
            return []
        
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                tenders = json.load(f)
            
            logger.info(f"Loaded {len(tenders)} tenders from JSON")
            return tenders
        except Exception as e:
            logger.error(f"Error loading JSON file: {e}")
            return []
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime object"""
        if not date_str or date_str == '...':
            return None
        
        # Try different date formats
        formats = [
            '%d/%m/%Y %H:%M',  # 20/01/2026 10:30
            '%d/%m/%Y',        # 02/12/2025
            '%Y-%m-%dT%H:%M:%S.%f',  # ISO format with microseconds
            '%Y-%m-%dT%H:%M:%S',     # ISO format
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    def get_or_create_buyer(self, session, name: str) -> Optional[Buyer]:
        """Get or create buyer and return Buyer object"""
        if not name:
            return None
            
        name = name.strip()
        # Try to find existing buyer
        buyer = session.query(Buyer).filter_by(name=name).first()
        
        if not buyer:
            # Create new buyer
            # Determine type based on name (simple logic matching migration script)
            buyer_type = 'Other'
            upper_name = name.upper()
            if 'COMMUNE' in upper_name:
                buyer_type = 'Commune'
            elif 'PROVINCE' in upper_name or 'GOUVERNEUR' in upper_name:
                buyer_type = 'Province'
            elif 'CONSEIL' in upper_name:
                buyer_type = 'Council'
            elif 'AGENCE' in upper_name:
                buyer_type = 'Agency'
            elif 'DIRECTEUR' in upper_name:
                buyer_type = 'Directorate'
            elif 'SOCIETE' in upper_name:
                buyer_type = 'Company'
            
            initials = generate_initials(name)
                
            buyer = Buyer(name=name, type=buyer_type, initials=initials)
            session.add(buyer)
            session.flush() # Flush to get ID
            
        return buyer

    def get_or_create_category(self, session, name: str) -> Optional[int]:
        """Get or create category and return ID"""
        if not name:
            return None
            
        name = name.strip()
        category = session.query(Category).filter_by(name=name).first()
        
        if not category:
            category = Category(name=name, description='Auto-created by data pusher')
            session.add(category)
            session.flush()
            
        return category.id

    def push_tender_to_database(self, tender_data: Dict, session) -> Optional[Tender]:
        """
        Push a single tender to the database
        
        Args:
            tender_data: Tender data dictionary
            session: Database session
            
        Returns:
            Tender object if successful, None otherwise
        """
        try:
            # Get related objects
            buyer = self.get_or_create_buyer(session, tender_data.get('buyer'))
            category_id = self.get_or_create_category(session, tender_data.get('category'))
            
            # Generate new reference with initials
            original_reference = tender_data['reference']
            # Store original reference for file lookup
            tender_data['original_reference'] = original_reference
            
            if buyer and buyer.initials:
                new_reference = f"{original_reference}_{buyer.initials}"
            else:
                new_reference = original_reference
                
            # Update reference in tender_data for consistency
            tender_data['reference'] = new_reference

            # Check if tender already exists
            existing_tender = session.query(Tender).filter_by(
                reference=new_reference
            ).first()
            
            # Parse dates
            launch_date = self.parse_date(tender_data.get('launch_date'))
            deadline = self.parse_date(tender_data.get('deadline'))
            scraped_at = self.parse_date(tender_data.get('scraped_at'))
            
            buyer_id = buyer.id if buyer else None
            
            if existing_tender:
                # Update existing tender
                existing_tender.title = tender_data.get('object', '')
                existing_tender.buyer_id = buyer_id
                existing_tender.category_id = category_id
                existing_tender.publication_date = launch_date
                existing_tender.deadline = deadline
                existing_tender.last_scraped_at = scraped_at
                existing_tender.updated_at = datetime.now()
                existing_tender.raw_data = tender_data
                
                session.commit()
                self.stats['tenders_updated'] += 1
                logger.debug(f"Updated tender: {new_reference}")
                return existing_tender
            else:
                # Create new tender
                tender = Tender(
                    reference=new_reference,
                    title=tender_data.get('object', ''),
                    buyer_id=buyer_id,
                    category_id=category_id,
                    publication_date=launch_date,
                    deadline=deadline,
                    last_scraped_at=scraped_at,
                    raw_data=tender_data
                )
                
                session.add(tender)
                session.commit()
                self.stats['tenders_inserted'] += 1
                logger.debug(f"Inserted tender: {new_reference}")
                return tender
                
        except IntegrityError as e:
            session.rollback()
            logger.error(f"Integrity error for tender {tender_data.get('reference')}: {e}")
            self.stats['tenders_failed'] += 1
            return None
        except Exception as e:
            session.rollback()
            logger.error(f"Error pushing tender {tender_data.get('reference')}: {e}")
            self.stats['tenders_failed'] += 1
            return None
    
    def upload_file_to_s3(
        self,
        file_path: Path,
        s3_key: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Upload file to S3 bucket
        
        Args:
            file_path: Local file path
            s3_key: S3 object key (defaults to filename)
            metadata: Additional metadata for S3 object
            
        Returns:
            S3 path if successful, None otherwise
        """
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        
        if not s3_key:
            s3_key = f"tender-documents/{file_path.name}"
        
        try:
            # Check if file already exists in S3
            try:
                self.s3_client.head_object(Bucket=self.s3_bucket, Key=s3_key)
                logger.debug(f"File already exists in S3: {s3_key}")
                self.stats['files_skipped'] += 1
                return f"s3://{self.s3_bucket}/{s3_key}"
            except:
                pass  # File doesn't exist, proceed with upload
            
            # Sanitize metadata for S3 (must be ASCII)
            s3_metadata = self._sanitize_metadata(metadata) if metadata else {}
            s3_metadata['uploaded_at'] = datetime.now().isoformat() # Add uploaded_at after sanitization
            
            # Upload file
            logger.info(f"Uploading {file_path.name} to S3...")
            self.s3_client.upload_file(
                str(file_path),
                self.s3_bucket,
                s3_key,
                ExtraArgs={
                    'Metadata': s3_metadata
                }
            )
            
            self.stats['files_uploaded'] += 1
            s3_path = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"Uploaded successfully: {s3_path}")
            return s3_path
            
        except Exception as e:
            logger.error(f"Error uploading {file_path.name} to S3: {e}")
            self.stats['files_failed'] += 1
            return None
    
    def process_tender_documents(self, tender: Tender, tender_data: Dict, session):
        """
        Process and upload tender documents to S3
        
        Args:
            tender: Tender database object
            tender_data: Original tender data
            session: Database session
        """
        # Find the ZIP file
        zip_path = None
        json_path_str = tender_data.get('download_path') or tender_data.get('file_path')
        found_filename = None
        
        possible_paths = []
        if json_path_str:
             possible_paths.append(Path(json_path_str))
             possible_paths.append(Path(json_path_str.replace('./', '')))
             possible_paths.append(Path(os.path.basename(json_path_str)))

        # Directories to search
        search_dirs = [
            self.downloads_dir,
            Path('scraper_download'),
            Path('downloads')
        ]
        
        # Search for the file
        for p in possible_paths:
            if p.exists():
                zip_path = p
                found_filename = p.name
                break
            for d in search_dirs:
                candidate = d / p.name
                if candidate.exists():
                    zip_path = candidate
                    found_filename = candidate.name
                    break
            if zip_path: break

        
        if not zip_path or not zip_path.exists():
            logger.debug(f"No ZIP file found for tender: {tender.reference} (tried {json_path_str})")
            return
        
        # Upload to S3
        # Use new reference for S3 key
        safe_new_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in tender.reference])
        s3_key = f"tender-documents/{safe_new_ref}.zip"
        metadata = {
            'tender_reference': tender.reference,
            'tender_category': tender_data.get('category', ''),
            'buyer': tender_data.get('buyer', '')
        }
        
        s3_path = self.upload_file_to_s3(zip_path, s3_key, metadata)
        
        if s3_path:
            # Check if document record already exists
            existing_doc = session.query(TenderDocument).filter_by(
                tender_id=tender.id,
                document_name=found_filename
            ).first()
            
            if existing_doc:
                existing_doc.s3_path = s3_path
                existing_doc.downloaded = True
            else:
                # Create document record
                document = TenderDocument(
                    tender_id=tender.id,
                    document_name=found_filename,
                    document_type='zip',
                    document_size=f"{zip_path.stat().st_size / 1024 / 1024:.2f} MB",
                    downloaded=True,
                    s3_path=s3_path
                )
                session.add(document)
            
            try:
                session.commit()
                logger.debug(f"Document record updated for: {found_filename}")
            except Exception as e:
                session.rollback()
                logger.error(f"Error updating document record: {e}")
    
    def push_all_data(self):
        """Main method to push all data to AWS"""
        self.start_time = datetime.now()
        logger.info("=" * 80)
        logger.info("Starting data push to AWS")
        logger.info("=" * 80)
        
        # Load tenders
        tenders = self.load_tenders_json()
        if not tenders:
            logger.warning("No tenders to process")
            return
        
        # Create tables if they don't exist
        try:
            self.db.create_tables()
            logger.info("Database tables verified/created")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}")
            return
        
        # Process each tender
        session = self.db.get_session()
        
        try:
            for tender_data in tenders:
                self.stats['tenders_processed'] += 1
                
                # Push tender to database
                tender = self.push_tender_to_database(tender_data, session)
                
                if tender:
                    # Process documents
                    self.process_tender_documents(tender, tender_data, session)
                
                # Log progress every 10 tenders
                if self.stats['tenders_processed'] % 10 == 0:
                    logger.info(
                        f"Progress: {self.stats['tenders_processed']}/{len(tenders)} tenders | "
                        f"Inserted: {self.stats['tenders_inserted']} | "
                        f"Updated: {self.stats['tenders_updated']} | "
                        f"Files uploaded: {self.stats['files_uploaded']}"
                    )
            
        finally:
            session.close()
        
        # Cleanup and Report
        self.cleanup_and_report(tenders, session)        
    def cleanup_and_report(self, all_tenders: List[Dict], session):
        """
        Delete pushed ZIP files, remove processed entries from JSON, and generate report
        """
        logger.info("=" * 80)
        logger.info("STARTING CLEANUP")
        logger.info("=" * 80)

        successful_references = []
        files_deleted = 0
        remaining_tenders = []

        # Identify successfully processed tenders
        # We consider a tender successful if it was inserted/updated AND its file (if any) was uploaded/skipped
        # Since we don't track per-tender success strictly in the loop, we'll re-verify against DB/S3 logic or 
        # simply assume if no exception was raised for it. 
        # A safer approach: check if it exists in DB.
        
        for tender_data in all_tenders:
            ref = tender_data['reference']
            
            # Check if tender is in DB
            db_tender = session.query(Tender).filter_by(reference=ref).first()
            
            if db_tender:
                successful_references.append(ref)
                
                # 1. Delete ZIP file
                # Try to use the file_path from JSON first
                zip_path = None
                json_path_str = tender_data.get('download_path') or tender_data.get('file_path')
                
                possible_paths = []
                
                # Option A: From JSON path
                if json_path_str:
                     # It might be relative like './scraper_download/file.zip'
                     # We want to check relative to CWD
                     possible_paths.append(Path(json_path_str))
                     possible_paths.append(Path(json_path_str.replace('./', '')))
                     possible_paths.append(Path(os.path.basename(json_path_str)))

                # Option B: Reconstruct from Reference (New Composite Logic)
                # But safer to just scan directories for the file if we know the name
                
                # Directories to search
                search_dirs = [
                    self.downloads_dir,
                    Path('scraper_download'),
                    Path('downloads')
                ]
                
                found_file = None
                
                # Search strategies
                # 1. Check exact paths from JSON
                for p in possible_paths:
                    if p.exists():
                        found_file = p
                        break
                    # Check in search dirs
                    for d in search_dirs:
                        candidate = d / p.name
                        if candidate.exists():
                            found_file = candidate
                            break
                    if found_file: break
                
                # 2. If not found, try constructing strict filename from DB/JSON data?
                # For now, rely on JSON path correctness as Scraper sets it.
                
                if found_file and found_file.exists():
                    try:
                        os.remove(found_file)
                        files_deleted += 1
                        logger.debug(f"Deleted local file: {found_file}")
                    except Exception as e:
                        logger.error(f"Error deleting file {found_file}: {e}")
                else:
                    logger.warning(f"File for {ref} not found on disk (tried {json_path_str}). Skipped deletion.")
            else:
                remaining_tenders.append(tender_data)

        # 2. Update JSON file (remove successful entries)
        try:
            if remaining_tenders:
                with open(self.json_file, 'w', encoding='utf-8') as f:
                    json.dump(remaining_tenders, f, ensure_ascii=False, indent=4)
                logger.info(f"Updated JSON file. Remaining entries: {len(remaining_tenders)}")
            else:
                # If empty, write empty list or delete file? Usually empty list is safer.
                with open(self.json_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=4)
                logger.info("All tenders processed. JSON file cleared.")
                
        except Exception as e:
            logger.error(f"Error updating JSON file: {e}")

        # 3. Generate Report
        report_file = "push_report.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report_content = [
            "================================================================================",
            f"DATA PUSH REPORT - {timestamp}",
            "================================================================================",
            f"Total Tenders Processed: {len(all_tenders)}",
            f"Successfully Pushed:     {len(successful_references)}",
            f"Remaining in JSON:       {len(remaining_tenders)}",
            f"Local Files Deleted:     {files_deleted}",
            "",
            "Details:",
            "--------------------------------------------------------------------------------"
        ]
        
        if successful_references:
            report_content.append("Successfully Pushed References:")
            for ref in successful_references:
                report_content.append(f"  [OK] {ref}")
        
        if remaining_tenders:
            report_content.append("\nFailed / Remaining References:")
            for t in remaining_tenders:
                report_content.append(f"  [PENDING] {t['reference']}")

        report_content.append("================================================================================")
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_content))
            logger.info(f"Report generated: {report_file}")
        except Exception as e:
            logger.error(f"Error generating report: {e}")

        # Print summary to console
        self.print_summary()
        logger.info(f"Cleanup complete. Local files deleted: {files_deleted}")

    def print_summary(self):
        """Print execution summary"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        logger.info("=" * 80)
        logger.info("DATA PUSH SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("")
        logger.info("Database Statistics:")
        logger.info(f"  Tenders Processed: {self.stats['tenders_processed']}")
        logger.info(f"  Tenders Inserted:  {self.stats['tenders_inserted']}")
        logger.info(f"  Tenders Updated:   {self.stats['tenders_updated']}")
        logger.info(f"  Tenders Failed:    {self.stats['tenders_failed']}")
        logger.info("")
        logger.info("S3 Statistics:")
        logger.info(f"  Files Uploaded:    {self.stats['files_uploaded']}")
        logger.info(f"  Files Skipped:     {self.stats['files_skipped']}")
        logger.info(f"  Files Failed:      {self.stats['files_failed']}")
        logger.info("=" * 80)

    def _sanitize_metadata(self, metadata: Dict) -> Dict:
        """Ensure metadata values are ASCII-safe for S3"""
        sanitized = {}
        if not metadata:
            return sanitized
            
        for k, v in metadata.items():
            if v:
                # Encode to ASCII, ignoring errors or replacing
                # Better: URL encode to preserve content
                try:
                    # Try to encode as ASCII directly
                    str(v).encode('ascii')
                    sanitized[k] = str(v)
                except UnicodeEncodeError:
                    # If it fails, normalize or url-encode
                    # Simple approach: remove accents
                    import unicodedata
                    nfkd_form = unicodedata.normalize('NFKD', str(v))
                    ascii_val = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
                    sanitized[k] = ascii_val
        return sanitized

        """Print execution summary"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        logger.info("=" * 80)
        logger.info("DATA PUSH SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("")
        logger.info("Database Statistics:")
        logger.info(f"  Tenders Processed: {self.stats['tenders_processed']}")
        logger.info(f"  Tenders Inserted:  {self.stats['tenders_inserted']}")
        logger.info(f"  Tenders Updated:   {self.stats['tenders_updated']}")
        logger.info(f"  Tenders Failed:    {self.stats['tenders_failed']}")
        logger.info("")
        logger.info("S3 Statistics:")
        logger.info(f"  Files Uploaded:    {self.stats['files_uploaded']}")
        logger.info(f"  Files Skipped:     {self.stats['files_skipped']}")
        logger.info(f"  Files Failed:      {self.stats['files_failed']}")
        logger.info("=" * 80)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Push tender data to AWS RDS and S3')
    parser.add_argument(
        '--json-file',
        default='tenders.json',
        help='Path to tenders JSON file (default: tenders.json)'
    )
    parser.add_argument(
        '--downloads-dir',
        default='downloads',
        help='Directory containing ZIP files (default: downloads)'
    )
    parser.add_argument(
        '--s3-bucket',
        help='S3 bucket name (defaults to env var S3_BUCKET_NAME)'
    )
    parser.add_argument(
        '--aws-region',
        help='AWS region (defaults to env var AWS_REGION)'
    )
    parser.add_argument(
        '--database-url',
        help='Database URL (defaults to env var DATABASE_URL)'
    )
    
    args = parser.parse_args()
    
    # Create and run pusher
    pusher = DataPusher(
        json_file=args.json_file,
        downloads_dir=args.downloads_dir,
        aws_region=args.aws_region,
        s3_bucket=args.s3_bucket,
        database_url=args.database_url
    )
    
    try:
        pusher.push_all_data()
    except KeyboardInterrupt:
        logger.info("\nData push interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
