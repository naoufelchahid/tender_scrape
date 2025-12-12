#!/usr/bin/env python3
"""
Database Updater Script
Reads new_references.json and updates the database with new tenders
Downloads ZIP files using original reference for search and composite reference for naming
"""
import asyncio
import random
import logging
import json
import os
import boto3
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import Page
from playwright_stealth import stealth_async
from database.models import Database, Tender, TenderDocument, Buyer, Category
from scraper.browser_config import create_browser
from sqlalchemy.exc import IntegrityError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('db_updater.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Moroccan names for form filling
MOROCCAN_FAMILY_NAMES = [
    'Bennani', 'El Amrani', 'Alaoui', 'Idrissi', 'Berrada',
    'Tazi', 'Fassi', 'Lazrak', 'Bensouda', 'ElKettani',
    'Chraibi', 'Sefrioui', 'Lahlou', 'Belkadi', 'Benjelloun',
    'Squalli', 'Kettani', 'Benmoussa', 'Elmaleh', 'Azoulay'
]

MOROCCAN_MALE_NAMES = [
    'Mohammed', 'Ahmed', 'Youssef', 'Hassan', 'Ali',
    'Omar', 'Karim', 'Mehdi', 'Othmane', 'Amine',
    'Rachid', 'Said', 'Hamza', 'Bilal', 'Tarik'
]

MOROCCAN_FEMALE_NAMES = [
    'Fatima', 'Aicha', 'Khadija', 'Zineb', 'Amina',
    'Salma', 'Nora', 'Samira', 'Laila', 'Rim',
    'Latifa', 'Malika', 'Naima', 'Karima', 'Hafsa'
]

EMAIL_PROVIDERS = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com']


async def human_delay(min_sec=1, max_sec=3):
    """Random delay to mimic human behavior"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def human_scroll(page: Page):
    """Scroll page like a human"""
    await page.evaluate('''
        window.scrollTo({
            top: Math.random() * 500 + 200,
            behavior: 'smooth'
        });
    ''')


async def generate_moroccan_identity():
    """Generate random Moroccan identity for form"""
    is_male = random.choice([True, False])
    first_name = random.choice(MOROCCAN_MALE_NAMES if is_male else MOROCCAN_FEMALE_NAMES)
    family_name = random.choice(MOROCCAN_FAMILY_NAMES)
    email = f"{first_name.lower()}.{family_name.lower()}{random.randint(1, 999)}@{random.choice(EMAIL_PROVIDERS)}"
    
    return {
        'first_name': first_name,
        'family_name': family_name,
        'email': email
    }


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


class DatabaseUpdater:
    """Updates database with new tender references and downloads ZIP files"""
    
    def __init__(
        self,
        input_file: str = 'new_references.json',
        downloads_dir: str = 'downloads',
        database_url: Optional[str] = None
    ):
        """
        Initialize DatabaseUpdater
        
        Args:
            input_file: Path to new_references.json file
            downloads_dir: Directory to save downloaded ZIP files
            database_url: Database connection URL
        """
        self.input_file = Path(input_file)
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)
        
        # Initialize Database
        self.database_url = database_url or self._build_database_url()
        self.db = Database(self.database_url)
        
        # AWS Configuration
        self.aws_region = os.getenv('AWS_REGION', 'eu-west-3')
        self.s3_bucket = os.getenv('S3_BUCKET_NAME')
        
        if not self.s3_bucket:
            logger.warning("S3_BUCKET_NAME not set. creating placeholder.")
            
        self.s3_client = boto3.client(
            's3', 
            region_name=self.aws_region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )

        # Storage for new references
        self.new_references: List[Dict] = []
        
        # Statistics
        self.stats = {
            'total_references': 0,
            'db_inserted': 0,
            'db_updated': 0,
            'db_failed': 0,
            'files_downloaded': 0,
            'files_failed': 0,
            'already_processed': 0
        }
        
        logger.info(f"DatabaseUpdater initialized")
        logger.info(f"Input file: {self.input_file}")
        logger.info(f"Downloads directory: {self.downloads_dir}")
    
    def _build_database_url(self) -> str:
        """Build database URL from environment variables"""
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
    
    def load_new_references(self) -> List[Dict]:
        """Load new references from JSON file"""
        logger.info(f"Loading new references from {self.input_file}")
        
        if not self.input_file.exists():
            logger.error(f"Input file not found: {self.input_file}")
            return []
        
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            new_refs = data.get('new_references', [])
            self.stats['total_references'] = len(new_refs)
            
            logger.info(f"Loaded {len(new_refs)} new references")
            logger.info(f"Category: {data.get('category', 'Unknown')}")
            logger.info(f"Scan date: {data.get('scan_date', 'Unknown')}")
            
            return new_refs
            
        except Exception as e:
            logger.error(f"Error loading input file: {e}")
            return []
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime object"""
        if not date_str or date_str == '...':
            return None
        
        # Fix dates without space between date and time (e.g., "03/02/202610:00")
        # This happens when the format is DD/MM/YYYYHH:MM - we need to insert a space
        import re
        # Pattern: DD/MM/YYYYHH:MM -> DD/MM/YYYY HH:MM
        date_str_fixed = re.sub(r'(\d{2}/\d{2}/\d{4})(\d{2}:\d{2})', r'\1 \2', date_str)
        
        # Try different date formats
        formats = [
            '%d/%m/%Y %H:%M',       # 03/02/2026 10:00 (with space)
            '%d/%m/%Y',             # 02/12/2025
            '%Y-%m-%dT%H:%M:%S.%f', # ISO format with microseconds
            '%Y-%m-%dT%H:%M:%S',    # ISO format
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str_fixed, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str} (tried: {date_str_fixed})")
        return None
    
    def get_or_create_buyer(self, session, name: str) -> Optional[Buyer]:
        """Get or create buyer and return Buyer object"""
        if not name:
            return None
            
        name = name.strip()
        buyer = session.query(Buyer).filter_by(name=name).first()
        
        if not buyer:
            # Create new buyer
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
            session.flush()
            
        return buyer
    
    def get_or_create_category(self, session, name: str) -> Optional[int]:
        """Get or create category and return ID"""
        if not name:
            return None
            
        name = name.strip()
        category = session.query(Category).filter_by(name=name).first()
        
        if not category:
            category = Category(name=name, description='Auto-created by db updater')
            session.add(category)
            session.flush()
            
        return category.id
    
    def save_tender_to_database(self, tender_data: Dict, session) -> Optional[Tender]:
        """
        Save tender to database using composite reference
        
        Args:
            tender_data: Tender data from new_references.json
            session: Database session
            
        Returns:
            Tender object if successful, None otherwise
        """
        try:
            # Get composite reference (with initials)
            composite_reference = tender_data['reference']
            
            # Check if tender already exists
            existing_tender = session.query(Tender).filter_by(
                reference=composite_reference
            ).first()
            
            if existing_tender:
                logger.info(f"Tender already exists in database: {composite_reference}")
                self.stats['already_processed'] += 1
                return existing_tender
            
            # Get related objects
            buyer = self.get_or_create_buyer(session, tender_data.get('buyer'))
            category_id = self.get_or_create_category(session, tender_data.get('category'))
            
            # Parse dates
            launch_date = self.parse_date(tender_data.get('launch_date'))
            deadline = self.parse_date(tender_data.get('deadline'))
            scraped_at = self.parse_date(tender_data.get('scraped_at'))
            
            buyer_id = buyer.id if buyer else None
            
            # Create new tender
            tender = Tender(
                reference=composite_reference,
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
            self.stats['db_inserted'] += 1
            logger.info(f"✅ Inserted tender to database: {composite_reference}")
            return tender
                
        except IntegrityError as e:
            session.rollback()
            logger.error(f"Integrity error for tender {tender_data.get('reference')}: {e}")
            self.stats['db_failed'] += 1
            return None
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving tender {tender_data.get('reference')}: {e}")
            self.stats['db_failed'] += 1
            return None
    
    async def search_by_reference(
        self, 
        page: Page, 
        original_reference: str,
        target_composite_reference: str
    ) -> bool:
        """
        Search for tender by original reference and navigate to the correct one
        Searches through all pages if multiple results exist
        
        Args:
            page: Playwright page object
            original_reference: Reference without initials (e.g., "11/2025")
            target_composite_reference: Full reference with initials (e.g., "11/2025_DPMS")
            
        Returns:
            True if tender found and navigated to, False if no match found (don't download)
        """
        logger.info(f"Searching for reference: {original_reference}")
        logger.info(f"Target composite reference: {target_composite_reference}")
        
        try:
            # Navigate to advanced search page
            await page.goto(
                'http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                wait_until='domcontentloaded',
                timeout=60000
            )
            logger.info("Loaded advanced search page")
            
            await human_delay(2, 4)
            await human_scroll(page)
            
            # Fill reference input
            reference_input = await page.query_selector('input#ctl0_CONTENU_PAGE_AdvancedSearch_reference')
            if not reference_input:
                logger.error("Reference input field not found")
                return False
            
            await reference_input.fill(original_reference)
            logger.info(f"Filled reference: {original_reference}")
            await human_delay(1, 2)
            
            # Scroll to search button
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await human_delay(0.5, 1)
            
            # Click search button
            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
            logger.info("Clicked search button")
            
            # Wait for page load
            await page.wait_for_load_state('networkidle')
            await human_delay(3, 5)
            
            # Check if tender was found
            tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
            if not tender_links:
                logger.warning(f"No tender found for reference: {original_reference}")
                return False
            
            logger.info(f"Found {len(tender_links)} tender(s) for reference: {original_reference}")
            
            # If only one result, navigate to it
            if len(tender_links) == 1:
                logger.info("Only one result found, navigating to it")
                await tender_links[0].click()
                await page.wait_for_load_state('networkidle')
                await human_delay(1, 2)
                return True
            
            # Multiple results - need to match by buyer across all pages
            logger.info("Multiple results found - matching by composite reference")
            
            # Read the number of pages from the span element
            from bs4 import BeautifulSoup
            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            total_pages = 1
            page_count_element = soup.find('span', id='ctl0_CONTENU_PAGE_resultSearch_nombrePageTop')
            if page_count_element:
                try:
                    total_pages = int(page_count_element.get_text(strip=True))
                    logger.info(f"Total pages to search: {total_pages}")
                except ValueError:
                    logger.warning("Could not parse page count, searching only current page")
            
            # Search through all pages
            for current_page in range(1, total_pages + 1):
                logger.info(f"Searching page {current_page}/{total_pages}")
                
                # Get fresh HTML content for current page
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Get tender links on current page
                tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
                
                # Find all buyer divs
                buyer_divs = soup.find_all('div', id=lambda x: x and 'panelBlocDenomination' in x)
                
                if len(buyer_divs) != len(tender_links):
                    logger.warning(f"Mismatch: {len(buyer_divs)} buyers vs {len(tender_links)} links")
                
                # Extract buyer names and create composite references
                matched_index = None
                for idx, buyer_div in enumerate(buyer_divs):
                    if idx >= len(tender_links):
                        break
                        
                    # Extract buyer name
                    buyer_text = buyer_div.get_text(strip=True).replace("Acheteur public :", "").strip()
                    buyer_text = " ".join(buyer_text.split())
                    
                    # Generate buyer initials
                    buyer_initials = generate_initials(buyer_text)
                    
                    # Create composite reference
                    composite_ref = f"{original_reference}_{buyer_initials}"
                    
                    logger.info(f"  Result {idx + 1}: Buyer='{buyer_text[:50]}...' -> Composite='{composite_ref}'")
                    
                    # Check if this matches our target
                    if composite_ref == target_composite_reference:
                        logger.info(f"✅ MATCH FOUND at index {idx} on page {current_page}!")
                        matched_index = idx
                        break
                
                # If match found, navigate to it
                if matched_index is not None:
                    logger.info(f"Navigating to matched tender at position {matched_index + 1}")
                    await tender_links[matched_index].click()
                    await page.wait_for_load_state('networkidle')
                    await human_delay(1, 2)
                    return True
                
                # If not found and there are more pages, navigate to next page
                if current_page < total_pages:
                    logger.info(f"Match not found on page {current_page}, navigating to next page...")
                    
                    # Click next page link
                    next_page_link = await page.query_selector(f'a[href*="numPageEnCours={current_page + 1}"]')
                    if next_page_link:
                        await next_page_link.click()
                        await page.wait_for_load_state('networkidle')
                        await human_delay(2, 3)
                    else:
                        logger.warning(f"Could not find link to page {current_page + 1}")
                        break
            
            # No match found across all pages
            logger.error(f"❌ No match found for composite reference: {target_composite_reference} across {total_pages} page(s)")
            logger.warning("⚠️ Skipping download - no matching tender found")
            return False
            
        except Exception as e:
            logger.error(f"Error searching for reference {original_reference}: {e}")
            return False
    
    async def download_tender_file(
        self, 
        page: Page, 
        original_reference: str, 
        composite_reference: str
    ) -> Optional[str]:
        """
        Download tender ZIP file
        
        Args:
            page: Playwright page object
            original_reference: Original reference for logging
            composite_reference: Composite reference for filename
            
        Returns:
            File path if successful, None otherwise
        """
        logger.info(f"Attempting to download file for: {original_reference}")
        
        try:
            # Click on "Dossier de consultation" link
            dce_link = await page.query_selector('a#ctl0_CONTENU_PAGE_linkDownloadDce')
            if not dce_link:
                logger.warning("Download link not found")
                return None
            
            await human_scroll(page)
            await dce_link.click()
            logger.info("Clicked on document download link")
            
            await page.wait_for_load_state('networkidle')
            await human_delay(2, 3)
            
            # Retry loop for form submission (max 3 attempts)
            max_retries = 3
            for attempt in range(max_retries):
                logger.info(f"Form submission attempt {attempt + 1}/{max_retries}")
                
                # Generate random Moroccan identity
                identity = await generate_moroccan_identity()
                logger.info(f"Using identity: {identity['first_name']} {identity['family_name']} <{identity['email']}>")
                
                # Check the acceptance checkbox
                checkbox = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions')
                if checkbox:
                    is_checked = await checkbox.is_checked()
                    if not is_checked:
                        await human_delay(0.5, 1)
                        await checkbox.check()
                        logger.info("Checked conditions acceptance")
                
                await human_delay(0.5, 1.5)
                
                # Fill family name
                nom_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_nom')
                if nom_input:
                    await nom_input.fill(identity['family_name'])
                
                await human_delay(0.5, 1)
                
                # Fill first name
                prenom_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_prenom')
                if prenom_input:
                    await prenom_input.fill(identity['first_name'])
                
                await human_delay(0.5, 1)
                
                # Fill email
                email_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_email')
                if email_input:
                    await email_input.fill(identity['email'])
                
                await human_delay(1, 2)
                
                # Submit form
                logger.info("Submitting form...")
                valider_button = await page.query_selector('input[type="submit"][value="Valider"], input[name*="valider"], button:has-text("Valider")')
                if valider_button:
                    await valider_button.click()
                    logger.info("Form submitted")
                    await page.wait_for_load_state('networkidle')
                    await human_delay(3, 5)
                
                # Check for error message
                error_msg = await page.query_selector('div#divValidationSummary, span#ctl0_CONTENU_PAGE_ctl4_validationSummary')
                if error_msg and await error_msg.is_visible():
                    logger.warning("⚠️ Form validation error detected! Retrying with new identity...")
                    await human_delay(2, 3)
                    continue
                
                logger.info("Form submission successful")
                break
            
            # Click download button
            logger.info("Clicking download button...")
            download_button = await page.query_selector('a#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload')
            
            if not download_button:
                download_button = await page.query_selector('a.bouton-telecharger-long230, a:has-text("Télécharger le Dossier")')
            
            if download_button:
                # Create safe filename using composite reference
                safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in composite_reference])
                filename = f"{safe_ref}.zip"
                filepath = self.downloads_dir / filename
                
                async with page.expect_download(timeout=60000) as download_info:
                    await download_button.click(force=True)
                    logger.info("Clicked download button")
                
                download = await download_info.value
                
                try:
                    await asyncio.wait_for(download.save_as(str(filepath)), timeout=180)
                    logger.info(f"✅ Downloaded: {filepath}")
                    return str(filepath)
                except asyncio.TimeoutError:
                    logger.error(f"❌ Download timed out after 3 minutes")
                    return None
            else:
                logger.warning("Download button not found")
                return None
                
        except Exception as e:
            logger.error(f"Error downloading file for {original_reference}: {e}")
            return None
    
    def _sanitize_metadata(self, metadata: Dict) -> Dict:
        """Ensure metadata values are ASCII-safe for S3"""
        sanitized = {}
        if not metadata:
            return sanitized
            
        for k, v in metadata.items():
            if v:
                try:
                    str(v).encode('ascii')
                    sanitized[k] = str(v)
                except UnicodeEncodeError:
                    nfkd_form = unicodedata.normalize('NFKD', str(v))
                    ascii_val = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
                    sanitized[k] = ascii_val
        return sanitized

    def upload_file_to_s3(self, file_path: Path, s3_key: str, metadata: Dict) -> Optional[str]:
        """Upload file to S3 bucket"""
        if not self.s3_bucket:
            logger.error("Cannot upload: S3 bucket not configured")
            return None
            
        try:
            # Check if file already exists in S3
            try:
                self.s3_client.head_object(Bucket=self.s3_bucket, Key=s3_key)
                logger.debug(f"File already exists in S3: {s3_key}")
                return f"s3://{self.s3_bucket}/{s3_key}"
            except:
                pass

            s3_metadata = self._sanitize_metadata(metadata)
            s3_metadata['uploaded_at'] = datetime.now().isoformat()

            logger.info(f"Uploading {file_path.name} to S3...")
            self.s3_client.upload_file(
                str(file_path),
                self.s3_bucket,
                s3_key,
                ExtraArgs={'Metadata': s3_metadata}
            )
            
            return f"s3://{self.s3_bucket}/{s3_key}"
            
        except Exception as e:
            logger.error(f"Error uploading {file_path.name}: {e}")
            return None

    def update_tender_document(self, session, tender: Tender, filename: str, s3_path: str, file_path: Path) -> bool:
        """Update or insert TenderDocument record"""
        try:
            existing_doc = session.query(TenderDocument).filter_by(
                tender_id=tender.id,
                document_name=filename
            ).first()

            if existing_doc:
                existing_doc.s3_path = s3_path
                existing_doc.downloaded = True
                logger.info(f"Updated existing document record for {filename}")
            else:
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                new_doc = TenderDocument(
                    tender_id=tender.id,
                    document_name=filename,
                    document_type='zip',
                    document_size=f"{file_size_mb:.2f} MB",
                    downloaded=True,
                    s3_path=s3_path
                )
                session.add(new_doc)
                logger.info(f"Created new document record for {filename}")
            
            session.commit()
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating database for {filename}: {e}")
            return False

    def remove_from_new_references(self, reference: str):
        """Remove processed tender from new_references.json"""
        try:
            if not self.input_file.exists():
                return
            
            with open(self.input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            new_refs = data.get('new_references', [])
            original_count = len(new_refs)
            
            # Filter out the processed reference
            # Use 'reference' which corresponds to the composite reference
            data['new_references'] = [
                r for r in new_refs 
                if r.get('reference') != reference
            ]
            
            new_count = len(data['new_references'])
            data['new_references_count'] = new_count
            
            if new_count < original_count:
                with open(self.input_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                logger.info(f"Removed {reference} from new_references.json")
                
        except Exception as e:
            logger.error(f"Error updating references file: {e}")
    
    async def process_tender(self, page: Page, tender_data: Dict, session) -> bool:
        """Process a single tender: save to DB and download file"""
        composite_reference = tender_data['reference']
        original_reference = tender_data['original_reference']
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {composite_reference}")
        logger.info(f"Original ref: {original_reference}")
        logger.info(f"{'='*80}")
        
        try:
            # Save to database first
            tender = self.save_tender_to_database(tender_data, session)
            if not tender:
                logger.error(f"❌ Failed to save tender to database: {composite_reference}")
                return False
            
            # Check if file already exists
            safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in composite_reference])
            zip_filename = f"{safe_ref}.zip"
            zip_path = self.downloads_dir / zip_filename
            
            if zip_path.exists():
                logger.info(f"File already exists, skipping download: {zip_filename}")
                self.stats['already_processed'] += 1
                return True
            
            # Search for tender using original reference and match by composite reference
            found = await self.search_by_reference(page, original_reference, composite_reference)
            if not found:
                logger.error(f"❌ Failed to find tender: {original_reference}")
                self.stats['files_failed'] += 1
                return False
            
            # Download file using composite reference for naming
            file_path = await self.download_tender_file(page, original_reference, composite_reference)
            if not file_path:
                logger.error(f"❌ Failed to download: {composite_reference}")
                self.stats['files_failed'] += 1
                return False
            
            self.stats['files_downloaded'] += 1
            
            # Upload to S3
            s3_key = f"tender-documents/{Path(file_path).name}"
            metadata = {
                'tender_reference': tender.reference,
                'tender_category': tender.category.name if tender.category else '',
                'buyer': tender.buyer.name if tender.buyer else ''
            }
            
            s3_path = self.upload_file_to_s3(Path(file_path), s3_key, metadata)
            if not s3_path:
                logger.error(f"❌ Failed to upload to S3: {composite_reference}")
                return False
                
            # Update Document in Database
            if not self.update_tender_document(session, tender, Path(file_path).name, s3_path, Path(file_path)):
                logger.error(f"❌ Failed to update document in DB: {composite_reference}")
                return False
            
            # Remove from new_references.json
            self.remove_from_new_references(composite_reference)
            
            # Cleanup local file
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up local file: {file_path}")
            except Exception as e:
                logger.warning(f"Could not delete local file {file_path}: {e}")

            logger.info(f"✅ Successfully processed and uploaded: {composite_reference}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {composite_reference}: {e}")
            return False
        
        finally:
            # Always navigate back to search page for next iteration
            await human_delay(2, 3)
            
            try:
                logger.info("Navigating back to search page...")
                await page.goto(
                    'http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                    wait_until='domcontentloaded',
                    timeout=60000
                )
                await human_delay(2, 3)
                logger.info("Returned to search page")
                    
            except Exception as nav_error:
                logger.warning(f"Error during return navigation: {nav_error}")
    
    async def run(self, max_tenders: Optional[int] = None):
        """Main execution method"""
        logger.info("=" * 80)
        logger.info("STARTING DATABASE UPDATE")
        logger.info("=" * 80)
        
        # Load new references
        self.new_references = self.load_new_references()
        if not self.new_references:
            logger.warning("No new references to process")
            return
        
        # Limit number of tenders if specified
        if max_tenders:
            self.new_references = self.new_references[:max_tenders]
            logger.info(f"Limited to {max_tenders} tenders")
        
        # Create database tables if they don't exist
        try:
            self.db.create_tables()
            logger.info("Database tables verified/created")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}")
            return
        
        # Create browser
        browser = await create_browser(headless=False)
        
        try:
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='fr-FR',
                timezone_id='Europe/Paris'
            )
            
            page = await context.new_page()
            await stealth_async(page)
            page.set_default_timeout(120000)
            
            # Get database session
            session = self.db.get_session()
            
            try:
                # Process each tender
                for idx, tender_data in enumerate(self.new_references, 1):
                    logger.info(f"\n{'#'*80}")
                    logger.info(f"Progress: {idx}/{len(self.new_references)}")
                    logger.info(f"{'#'*80}")
                    
                    await self.process_tender(page, tender_data, session)
                    
                    # Log progress
                    if idx % 5 == 0:
                        self.print_progress()
                    
            finally:
                session.close()
                
        finally:
            await browser.close()
        
        # Print final summary
        self.print_summary()
    
    def print_progress(self):
        """Print current progress"""
        logger.info("=" * 80)
        logger.info("PROGRESS UPDATE")
        logger.info("=" * 80)
        logger.info(f"Total References: {self.stats['total_references']}")
        logger.info(f"DB Inserted: {self.stats['db_inserted']}")
        logger.info(f"DB Already Exists: {self.stats['already_processed']}")
        logger.info(f"Files Downloaded: {self.stats['files_downloaded']}")
        logger.info(f"Files Failed: {self.stats['files_failed']}")
        logger.info("=" * 80)
    
    def print_summary(self):
        """Print execution summary"""
        logger.info("=" * 80)
        logger.info("DATABASE UPDATE SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total References: {self.stats['total_references']}")
        logger.info("")
        logger.info("Database Statistics:")
        logger.info(f"  Inserted: {self.stats['db_inserted']}")
        logger.info(f"  Already Existed: {self.stats['already_processed']}")
        logger.info(f"  Failed: {self.stats['db_failed']}")
        logger.info("")
        logger.info("File Download Statistics:")
        logger.info(f"  Downloaded: {self.stats['files_downloaded']}")
        logger.info(f"  Failed: {self.stats['files_failed']}")
        logger.info("=" * 80)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Update database with new tender references and download ZIP files'
    )
    parser.add_argument(
        '--input-file',
        default='new_references.json',
        help='Input JSON file with new references (default: new_references.json)'
    )
    parser.add_argument(
        '--downloads-dir',
        default='downloads',
        help='Directory to save ZIP files (default: downloads)'
    )
    parser.add_argument(
        '--max-tenders',
        type=int,
        help='Maximum number of tenders to process (default: all)'
    )
    parser.add_argument(
        '--database-url',
        help='Database URL (defaults to env var DATABASE_URL)'
    )
    
    args = parser.parse_args()
    
    # Create and run updater
    updater = DatabaseUpdater(
        input_file=args.input_file,
        downloads_dir=args.downloads_dir,
        database_url=args.database_url
    )
    
    try:
        await updater.run(max_tenders=args.max_tenders)
    except KeyboardInterrupt:
        logger.info("\nDatabase update interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    asyncio.run(main())
