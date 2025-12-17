"""
Production scraper for marchespublics.gov.ma - Services category
Follows exact navigation steps with human-like behavior
"""
import asyncio
import random
import logging
import os
from playwright.async_api import Page
from typing import List, Dict, Optional
from datetime import datetime
from scraper.browser_config import create_browser
import json
from faker import Faker
from playwright_stealth import stealth_async
import re
import boto3
import unicodedata
from dotenv import load_dotenv
from database.models import Database, Tender, TenderDocument, Buyer, Category
from sqlalchemy.exc import IntegrityError
from pathlib import Path

load_dotenv()

def generate_initials(name):
    """Generate initials from buyer name - New logic"""
    if not name:
        return "UNK"
    
    # Common words to ignore
    ignore = ['LE', 'LA', 'LES', 'DE', 'DES', 'DU', 'ET', 'EN', 'AU', 'AUX', 'A', "L'"]
    
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('production_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Moroccan names for form filling
MOROCCAN_FAMILY_NAMES = [
    'Bennani', 'El Amrani', 'Alaoui', 'Idrissi', 'Berrada',
    'Tazi', 'Fassi', 'Lazrak', 'Bensouda', 'ElKettani',
    'Chraibi', 'Sefrioui', 'Lahlou', 'Belkadi', 'Benjelloun',
    'Tahiri', 'Zniber', 'Amor', 'Bensaid', 'ElHarti',
    'Benkirane', 'Mansouri', 'Bouabid', 'Chaoui', 'Naciri',
    'Raji', 'Slaoui', 'Kadiri', 'Bakkali', 'Jettou',
    'Ouazzani', 'ElFassi', 'Boukhris', 'Hassani', 'Cherkaoui',
    'Filali', 'Benani', 'Tounsi', 'Squalli', 'Benslimane',
    'Alami', 'Benabdellah', 'Lahrizi', 'Benomar', 'Kettani',
    'Bennis', 'Benjelloun', 'Lamrani', 'Benabbes', 'Benmoussa',
    'Aziz', 'Bentaleb', 'Bensouda', 'Lahlimi', 'Benhamou'
]

MOROCCAN_FIRST_NAMES = [
    'Ahmed', 'Mohamed', 'Fatima', 'Aicha', 'Youssef', 'Hassan',
    'Omar', 'Salma', 'Karim', 'Laila', 'Rachid', 'Samira',
    'Hamza', 'Nadia', 'Said', 'Zineb', 'Khalid', 'Amina',
    'Mehdi', 'Imane', 'Tarik', 'Khadija', 'Anas', 'Leila',
    'Yassine', 'Hicham', 'Meryem', 'Saloua', 'Nabil', 'Houda',
    'Mustapha', 'Brahim', 'Sanae', 'Reda', 'Othmane', 'Kenza',
    'Zakaria', 'Soukaina', 'Bilal', 'Nouhaila', 'Walid',
    'Abdellatif', 'Abderrahim', 'Abdelkader', 'Abdelaziz', 'Fouad',
    'Jamal', 'Driss', 'Aziz', 'Samir', 'Adil', 'Hafid',
    'Latifa', 'Malika', 'Naima', 'Karima', 'Hafsa', 'Siham',
    'Ilham', 'Rajae', 'Btissam', 'Hanane', 'Loubna', 'Ghizlane'
]

EMAIL_PROVIDERS = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com']

STATE_FILE = 'scraper_services_state.json'


def _sanitize_metadata(metadata: Dict) -> Dict:
    """Ensure metadata values are ASCII-safe for S3"""
    sanitized = {}
    if not metadata:
        return sanitized
        
    for k, v in metadata.items():
        if v:
            # First normalize content
            value_str = str(v)
            
            # Additional manual replacements for common issues
            replacements = {
                '’': "'",
                '‘': "'",
                '“': '"',
                '”': '"',
                '–': '-',
                '—': '-'
            }
            for char, repl in replacements.items():
                value_str = value_str.replace(char, repl)
            
            try:
                # Try direct encoding
                value_str.encode('ascii')
                sanitized[k] = value_str
            except UnicodeEncodeError:
                # Normalize unicode characters
                nfkd_form = unicodedata.normalize('NFKD', value_str)
                # Keep only ASCII characters (ord < 128)
                ascii_val = "".join([c for c in nfkd_form if not unicodedata.combining(c) and ord(c) < 128])
                sanitized[k] = ascii_val
    return sanitized

def upload_file_to_s3(s3_client, bucket_name: str, file_path: str, s3_key: str, metadata: Dict) -> bool:
    """Upload file to S3 bucket"""
    if not bucket_name or not s3_client:
        logger.error("Cannot upload: S3 bucket or client not configured")
        return False
        
    try:
        # Check if file already exists in S3
        try:
            s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            logger.debug(f"File already exists in S3: {s3_key}")
            return True
        except:
            pass

        s3_metadata = _sanitize_metadata(metadata)
        s3_metadata['uploaded_at'] = datetime.now().isoformat()

        logger.info(f"Uploading {os.path.basename(file_path)} to S3...")
        s3_client.upload_file(
            file_path,
            bucket_name,
            s3_key,
            ExtraArgs={'Metadata': s3_metadata}
        )
        
        logger.info(f"✅ Uploaded to s3://{bucket_name}/{s3_key}")
        return True
        
    except Exception as e:
        logger.error(f"Error uploading {file_path}: {e}")
        return False

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to datetime object"""
    if not date_str or date_str == '...' or date_str == 'N/A':
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

def get_or_create_buyer(session, name: str) -> Optional[Buyer]:
    """Get or create buyer and return Buyer object"""
    if not name or name == "N/A":
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

def get_or_create_category(session, name: str) -> Optional[int]:
    """Get or create category and return ID"""
    if not name or name == "N/A":
        return None
        
    name = name.strip()
    category = session.query(Category).filter_by(name=name).first()
    
    if not category:
        category = Category(name=name, description='Auto-created by scraper')
        session.add(category)
        session.flush()
        
    return category.id

def save_tender_to_database(tender_data: Dict, session) -> Optional[Tender]:
    """
    Save tender to database using composite reference
    """
    try:
        # Get composite reference (with initials)
        composite_reference = tender_data['reference']
        
        # Check if tender already exists
        existing_tender = session.query(Tender).filter_by(
            reference=composite_reference
        ).first()
        
        if existing_tender:
            logger.info(f"ℹ️ Tender already exists in database: {composite_reference}")
            return existing_tender
        
        # Get related objects
        buyer = get_or_create_buyer(session, tender_data.get('buyer'))
        category_id = get_or_create_category(session, tender_data.get('category'))
        
        # Parse dates
        launch_date = parse_date(tender_data.get('launch_date'))
        deadline = parse_date(tender_data.get('deadline'))
        scraped_at = parse_date(tender_data.get('scraped_at'))
        
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
        logger.info(f"✅ Inserted tender to database: {composite_reference}")
        return tender
            
    except IntegrityError as e:
        session.rollback()
        logger.error(f"Integrity error for tender {tender_data.get('reference')}: {e}")
        return None
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving tender {tender_data.get('reference')}: {e}")
        return None

def update_tender_document(session, tender: Tender, filename: str, s3_path: str, file_path: str) -> bool:
    """Update or insert TenderDocument record"""
    try:
        if not tender:
            logger.error(f"Cannot update document {filename}: Tender object is None")
            return False

        logger.info(f"Updating/Creating document record for {filename} (Tender ID: {tender.id})")
        
        existing_doc = session.query(TenderDocument).filter_by(
            tender_id=tender.id,
            document_name=filename
        ).first()

        if existing_doc:
            existing_doc.s3_path = s3_path
            existing_doc.downloaded = True
            logger.info(f"Updated existing document record for {filename}")
        else:
            p = Path(file_path)
            file_size_mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0
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
        logger.info(f"✅ Database committed for document {filename}")
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating database for {filename}: {e}")
        return False

def load_state() -> Dict:
    """Load scraper state from file"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                logger.info(f"📂 Loaded state: Page {state.get('page_number', 1)}, "
                           f"Tender {state.get('tender_index', 0)}, "
                           f"Total processed: {state.get('total_processed_count', 0)}")
                return state
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load state file: {e}")
    
    return {
        'page_number': 1,
        'tender_index': 0,
        'total_processed_count': 0
    }


def save_state(page_number: int, tender_index: int, total_processed_count: int):
    """Save current scraper state to file"""
    state = {
        'page_number': page_number,
        'tender_index': tender_index,
        'total_processed_count': total_processed_count,
        'last_updated': datetime.now().isoformat()
    }
    
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)
    
    logger.info(f"💾 Saved state: Page {page_number}, Tender {tender_index}, Total: {total_processed_count}")


def clear_state():
    """Clear state file when batch completes"""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        logger.info("🗑️  Cleared state file - batch complete")



async def human_delay(min_sec=1, max_sec=3):
    """Random delay to mimic human behavior"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def human_scroll(page: Page):
    """Scroll page like a human"""
    # Scroll down gradually
    for _ in range(random.randint(2, 4)):
        scroll_amount = random.randint(200, 500)
        await page.evaluate(f'window.scrollBy(0, {scroll_amount})')
        await human_delay(0.5, 1.5)
    
    # Sometimes scroll back up a bit
    if random.random() > 0.5:
        await page.evaluate(f'window.scrollBy(0, -{random.randint(100, 300)})')
        await human_delay(0.3, 0.8)


async def generate_moroccan_identity():
    """Generate random Moroccan identity for form"""
    first_name = random.choice(MOROCCAN_FIRST_NAMES)
    family_name = random.choice(MOROCCAN_FAMILY_NAMES)
    email_provider = random.choice(EMAIL_PROVIDERS)
    
    # Create email: firstname.familyname123@provider.com
    email = f"{first_name.lower()}.{family_name.lower()}{random.randint(100, 999)}@{email_provider}"
    
    return {
        'first_name': first_name,
        'family_name': family_name,
        'email': email
    }


async def navigate_to_consultations(page: Page):
    """Step 1: Navigate to 'Consultations en cours' page with retry logic"""
    logger.info("Step 1: Navigating to Consultations en cours...")
    
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Navigation attempt {attempt + 1}/{max_retries}")
            
            # Strategy 1: Navigate to homepage first (intermediate step)
            if attempt == 0:
                logger.info("Strategy 1: Homepage → Search page")
                try:
                    await page.goto('http://www.marchespublics.gov.ma/', 
                                  wait_until='commit', timeout=30000)
                    logger.info("Loaded homepage")
                    await human_delay(3, 5)
                    
                    # Now navigate to search page
                    await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                                  wait_until='domcontentloaded', timeout=60000)
                    logger.info("✅ Successfully loaded Consultations page (Strategy 1)")
                    await human_delay(2, 4)
                    await human_scroll(page)
                    return  # Success!
                    
                except Exception as e:
                    logger.warning(f"Strategy 1 failed: {e}")
                    await human_delay(retry_delay, retry_delay + 2)
                    continue
            
            # Strategy 2: Direct navigation with 'load' wait
            elif attempt == 1:
                logger.info("Strategy 2: Direct navigation with 'load' wait")
                try:
                    await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                                  wait_until='load', timeout=60000)
                    logger.info("✅ Successfully loaded Consultations page (Strategy 2)")
                    await human_delay(2, 4)
                    await human_scroll(page)
                    return  # Success!
                    
                except Exception as e:
                    logger.warning(f"Strategy 2 failed: {e}")
                    await human_delay(retry_delay, retry_delay + 2)
                    continue
            
            # Strategy 3: Direct navigation with 'networkidle' wait
            else:
                logger.info("Strategy 3: Direct navigation with 'networkidle' wait")
                try:
                    await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                                  wait_until='networkidle', timeout=90000)
                    logger.info("✅ Successfully loaded Consultations page (Strategy 3)")
                    await human_delay(2, 4)
                    await human_scroll(page)
                    return  # Success!
                    
                except Exception as e:
                    logger.warning(f"Strategy 3 failed: {e}")
                    if attempt < max_retries - 1:
                        await human_delay(retry_delay, retry_delay + 2)
                        continue
                    else:
                        raise  # Re-raise on last attempt
        
        except Exception as e:
            logger.error(f"Navigation attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                logger.error("❌ All navigation strategies failed!")
                raise
            await human_delay(retry_delay, retry_delay + 2)
    
    # If we get here, all retries failed
    raise Exception("Failed to navigate to Consultations page after all retries")


async def select_services_category(page: Page):
    """Step 2: select 'Services' category"""
    logger.info("Step 2: Selecting 'Services' category...")
    
    # Wait for the select element
    await page.wait_for_selector('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie')
    
    # Scroll to the category dropdown
    await human_scroll(page)
    
    # Select Services (value="3")
    await page.select_option(
        'select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie',
        value='3'
    )
    logger.info("Selected 'Services' category")
    
    await human_delay(1, 2)


async def launch_search(page: Page):
    """Step 3: Click search button with retry logic"""
    logger.info("Step 3: Launching search...")
    
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Search attempt {attempt + 1}/{max_retries}")
            
            # Scroll to search button
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await human_delay(0.5, 1)
            
            # Click search button with timeout
            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche', timeout=30000)
            logger.info("✅ Clicked 'Lancer la recherche'")
            
            # Wait for results to load
            await page.wait_for_load_state('networkidle', timeout=60000)
            await human_delay(3, 5)
            
            logger.info("✅ Search completed successfully")
            return  # Success!
            
        except Exception as e:
            logger.warning(f"Search attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                # Wait before retry with exponential backoff
                wait_time = retry_delay * (attempt + 1)
                logger.info(f"Retrying in {wait_time} seconds...")
                await human_delay(wait_time, wait_time + 2)
                
                # Try to reload the page and re-apply filters
                try:
                    logger.info("Reloading page before retry...")
                    await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                                  wait_until='domcontentloaded', timeout=60000)
                    await human_delay(2, 3)
                    
                    # Re-select Services category
                    await page.select_option('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', value='3')
                    await human_delay(1, 2)
                    logger.info("Page reloaded and category re-selected")
                except Exception as reload_error:
                    logger.error(f"Failed to reload page: {reload_error}")
            else:
                logger.error("❌ All search attempts failed!")
                raise  # Re-raise on last attempt
    
    raise Exception("Failed to launch search after all retries")


async def get_tender_rows(page: Page) -> List:
    """Step 4: Get all tender access links"""
    logger.info("Step 4: Getting tender access links...")
    
    # Find all links with href containing "EntrepriseDetailConsultation"
    # These are the "Accéder à la consultation" links
    tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
    logger.info(f"Found {len(tender_links)} tender links")
    
    return tender_links


async def process_tender(page: Page, tender_index: int, total_tenders: int, tender_data: Dict, session, s3_client=None, s3_bucket: str = None) -> bool:
    """Process a single tender: save to DB, download document, upload to S3, update DB"""
    composite_reference = tender_data['reference']
    original_reference = tender_data.get('original_reference', composite_reference)
    buyer_name = tender_data.get('buyer', '')
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Processing Tender {tender_index}/{total_tenders} - Ref: {composite_reference}")
    logger.info(f"{'='*80}")
    
    try:
        # Save tender to database
        tender = save_tender_to_database(tender_data, session)
        if not tender:
            logger.warning(f"Could not save/retrieve tender {composite_reference} in DB, proceeding with download anyway")

        # Step 5: Click on "Dossier de consultation" link
        logger.info("Step 5: Clicking on 'Dossier de consultation'...")
        
        dce_link = await page.query_selector('a#ctl0_CONTENU_PAGE_linkDownloadDce')
        if not dce_link:
            logger.warning("Download link not found for this tender")
            return False
        
        await human_scroll(page)
        await dce_link.click()
        logger.info("Clicked on document download link")
        
        await page.wait_for_load_state('networkidle')
        await human_delay(2, 3)
        
        # Retry loop for form submission (max 3 attempts)
        max_retries = 3
        for attempt in range(max_retries):
            logger.info(f"Form submission attempt {attempt + 1}/{max_retries}")
            
            # Generate random Moroccan identity (new one for each attempt if needed)
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
            
            # Fill family name (nom)
            nom_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_nom')
            if nom_input:
                await nom_input.fill(identity['family_name'])
                logger.info(f"Filled family name: {identity['family_name']}")
            
            await human_delay(0.5, 1)
            
            # Fill first name (prenom)
            prenom_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_prenom')
            if prenom_input:
                await prenom_input.fill(identity['first_name'])
                logger.info(f"Filled first name: {identity['first_name']}")
            
            await human_delay(0.5, 1)
            
            # Fill email
            email_input = await page.query_selector('input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_email')
            if email_input:
                await email_input.fill(identity['email'])
                logger.info(f"Filled email: {identity['email']}")
            
            await human_delay(1, 2)
            
            # Submit the form first (click "Valider" button) to enable download
            logger.info("Submitting form...")
            valider_button = await page.query_selector('input[type="submit"][value="Valider"], input[name*="valider"], button:has-text("Valider")')
            if valider_button:
                await valider_button.click()
                logger.info("Form submitted")
                await page.wait_for_load_state('networkidle')
                await human_delay(3, 5)  # Increased delay
            
            # Check for error message
            error_msg = await page.query_selector('div#divValidationSummary, span#ctl0_CONTENU_PAGE_ctl4_validationSummary')
            if error_msg and await error_msg.is_visible():
                logger.warning("⚠️ Form validation error detected! Retrying with new identity...")
                await human_delay(2, 3)
                continue  # Retry loop
            
            # If no error, assume success and break loop
            logger.info("Form submission successful (no error detected)")
            break
        
        # Now click download button (should be visible after form submission)
        logger.info("Clicking download button...")
        download_button = await page.query_selector('a#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload')
        
        if not download_button:
            # Try alternative selectors
            download_button = await page.query_selector('a.bouton-telecharger-long230, a:has-text("Télécharger le Dossier")')
        
        if download_button:
            # Wait for download to start
            async with page.expect_download(timeout=60000) as download_info:
                # Execute the JavaScript onclick (click the button)
                await download_button.click(force=True)  # force click even if hidden
                logger.info("Clicked 'Télécharger le Dossier de consultation'")
            
            # Wait for download to complete
            download = await download_info.value
            
            # Filename Logic: Use composite reference for uniqueness
            safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in composite_reference])
            filename = f"{safe_ref}.zip"
            filepath = f"./scraper_download/{filename}"
            Path("./scraper_download").mkdir(exist_ok=True)
            
            try:
                # Wait for download to finish with 3 minute timeout
                await asyncio.wait_for(download.save_as(filepath), timeout=180)
                logger.info(f"✅ Downloaded: {filepath}")
                
                # Wait for download to fully complete
                await human_delay(2, 3)
                
                # S3 Upload Logic
                if s3_client and s3_bucket:
                    s3_key = f"tender-documents/{filename}"
                    metadata = {
                        'tender_reference': composite_reference,
                        'buyer': buyer_name,
                        'original_filename': filename
                    }
                    
                    if upload_file_to_s3(s3_client, s3_bucket, filepath, s3_key, metadata):
                        # Update Database with new document
                        if tender:
                            logger.info("Calling update_tender_document...")
                            update_tender_document(session, tender, filename, f"s3://{s3_bucket}/{s3_key}", filepath)
                        else:
                            logger.error("Skipping document update because tender object is missing!")
                        
                        # Clean up local file only if upload successful
                        try:
                            os.remove(filepath)
                            logger.info(f"🗑️  Deleted local file: {filepath}")
                        except Exception as e:
                            logger.warning(f"Could not delete local file {filepath}: {e}")
                    else:
                        logger.warning(f"Keeping local file {filepath} due to upload failure")
                
                return True
            except asyncio.TimeoutError:
                logger.error(f"❌ Download timed out after 3 minutes: {filepath}")
                return False
            except Exception as e:
                logger.error(f"❌ Download failed: {e}")
                return False
        else:
            logger.warning("Download button not found")
            return False
        
    except Exception as e:
        logger.error(f"Error processing tender {tender_index}: {e}")
        return False
        
    finally:

        await human_delay(2, 3)
        
        # Navigate back to search results using menu system with retry
        max_nav_retries = 2
        for nav_attempt in range(max_nav_retries):
            try:
                logger.info(f"Navigating back to tender list (attempt {nav_attempt + 1}/{max_nav_retries})...")
                
                # Step 1: Click "Annonces" menu to activate it
                try:
                    annonces_menu = await page.query_selector('a[onclick*="toggleMenu"][accesskey="a"]')
                    if annonces_menu:
                        await annonces_menu.click(timeout=30000)
                        logger.info("Clicked 'Annonces' menu")
                        await human_delay(0.5, 1)
                except Exception as e:
                    logger.warning(f"Could not click Annonces menu: {e}")
                
                # Step 2: Click "Consultations en cours" link
                try:
                    consultations_link = await page.query_selector('a[href="?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons"]')
                    if consultations_link:
                        await consultations_link.click(timeout=30000)
                        logger.info("Clicked 'Consultations en cours'")
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        await human_delay(2, 3)
                        
                        # Re-apply search filters (Services category)
                        logger.info("Re-applying Services filter...")
                        try:
                            await page.wait_for_selector('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', state='visible', timeout=30000)
                            await page.select_option('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', value='3', timeout=30000)
                            await human_delay(1, 2)
                            
                            # Click search button
                            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche', timeout=30000)
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            await human_delay(2, 3)
                            logger.info("✅ Returned to search results")
                            return  # Success!
                        except Exception as filter_error:
                            logger.error(f"Failed to re-apply filter: {filter_error}")
                            raise
                    else:
                        logger.warning("Consultations link not found")
                        raise Exception("Consultations link not found")
                except Exception as nav_error:
                    logger.error(f"Navigation error: {nav_error}")
                    if nav_attempt < max_nav_retries - 1:
                        logger.info("Retrying navigation...")
                        await human_delay(3, 5)
                        continue
                    else:
                        raise
                        
            except Exception as e:
                if nav_attempt < max_nav_retries - 1:
                    logger.warning(f"Navigation attempt {nav_attempt + 1} failed, retrying...")
                    await human_delay(3, 5)
                else:
                    logger.error(f"All navigation attempts failed: {e}")
                    logger.warning("Will attempt recovery on next iteration")


async def scrape_services():
    """Main scraping function"""
    logger.info("\n" + "="*80)
    logger.info("STARTING PRODUCTION SCRAPER - SERVICES CATEGORY")
    logger.info("="*80 + "\n")
    
    # Create browser in VISIBLE mode for debugging
    browser = await create_browser(headless=False)
    
    try:
        # Create context with additional stealth settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='fr-FR',
            timezone_id='Europe/Paris',
            permissions=['geolocation'],
            geolocation={'latitude': 33.5731, 'longitude': -7.5898},  # Casablanca coordinates
            color_scheme='light',
            accept_downloads=True,
            extra_http_headers={
                'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Upgrade-Insecure-Requests': '1'
            }
        )
        
        page = await context.new_page()
        
        # Apply stealth and additional JavaScript to mask automation
        await stealth_async(page)
        
        # Additional JavaScript to hide automation signals
        await page.add_init_script("""
            // Overwrite the `navigator.webdriver` property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Overwrite the `plugins` property to use a fake length
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Overwrite the `languages` property
            Object.defineProperty(navigator, 'languages', {
                get: () => ['fr-FR', 'fr', 'en-US', 'en']
            });
            
            // Mock chrome object
            window.chrome = {
                runtime: {}
            };
            
            // Mock permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        
        # Increase default timeout for all operations
        # Increase default timeout for all operations
        page.set_default_timeout(90000)
        
        # Initialize S3 Client
        s3_bucket = os.getenv('S3_BUCKET_NAME')
        try:
            s3_client = boto3.client(
                's3',
                region_name=os.getenv('AWS_REGION', 'eu-west-3'),
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            logger.info(f"Initialized S3 client for bucket: {s3_bucket}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            s3_client = None

        # Database connection
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
             # Try building from individual components
            db_host = os.getenv('DB_HOST')
            db_port = os.getenv('DB_port', '5432')
            db_name = os.getenv('DB_NAME')
            db_user = os.getenv('DB_USER')
            db_password = os.getenv('DB_PASSWORD')
            if all([db_host, db_name, db_user, db_password]):
                db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        db = Database(db_url) if db_url else None
        if db:
            logger.info("Database connected")
        else:
            logger.warning("Database configuration missing, will not save to DB")

        await navigate_to_consultations(page)
        await select_services_category(page)
        await launch_search(page)
        
        # Process tenders with pagination
        MAX_TENDERS = 1800
        
        # Load saved state (or defaults if no state file exists)
        state = load_state()
        page_number = state['page_number']
        tender_index = state['tender_index']
        total_processed_count = state['total_processed_count']
        
        successful = 0
        failed = 0
        
        logger.info(f"Starting from: Page {page_number}, Tender {tender_index}, Total processed: {total_processed_count}")
        
        while total_processed_count < MAX_TENDERS:
            # If we need to be on a specific page > 1, navigate to it FIRST
            # (The "Return" logic resets us to Page 1, so we must re-navigate if needed)
            if page_number > 1:
                logger.info(f"Navigating to page {page_number}...")
                
                # Wait for pagination input with retry logic
                page_input = None
                try:
                    for retry in range(3):
                        try:
                            page_input = await page.query_selector('input#ctl0_CONTENU_PAGE_resultSearch_numPageTop')
                            if page_input:
                                break
                        except Exception as query_error:
                            logger.warning(f"Query error on retry {retry + 1}/3: {query_error}")
                        logger.warning(f"Pagination input not found, retry {retry + 1}/3...")
                        await human_delay(2, 3)
                    
                    if page_input:
                        await page_input.fill(str(page_number))
                        await page_input.press('Enter')
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        await human_delay(2, 3)
                    else:
                        logger.warning(f"Pagination input not found after retries. Skipping to next iteration.")
                        # Don't break - continue trying with current page
                        await human_delay(2, 3)
                except Exception as page_nav_error:
                    logger.error(f"Fatal error during page navigation: {page_nav_error}")
                    logger.warning("Page context may be destroyed. Will attempt to recover...")
                    # Try to reload the search page
                    try:
                        await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                                      wait_until='domcontentloaded', timeout=60000)
                        await select_services_category(page)
                        await launch_search(page)
                        logger.info("Successfully recovered from page context error")
                    except Exception as recovery_error:
                        logger.error(f"Could not recover from page error: {recovery_error}")
                        logger.error("Scraper will stop to prevent further errors")
                        break

            # Re-query tender links each iteration (fresh DOM elements)
            current_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
            
            # Check if we finished the current page
            if tender_index >= len(current_links):
                logger.info(f"Finished processing page {page_number}")
                
                # If we found no links on this page, verify we're actually on the search results page
                if len(current_links) == 0:
                    logger.warning("No tender links found on current page")
                    
                    # Check if we're on the search results page by looking for the category selector
                    category_selector = await page.query_selector('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie')
                    
                    if category_selector:
                        # We're on the search page but no results - likely end of tenders
                        logger.info("Verified on search page with no results. End of scraping.")
                        break
                    else:
                        # We're NOT on the search page - navigation failed
                        logger.warning("Not on search results page! Attempting recovery...")
                        
                        try:
                            # Try to recover by navigating back to search
                            logger.info("Recovering: Navigating to search page...")
                            await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                                          wait_until='domcontentloaded', timeout=60000)
                            await human_delay(2, 3)
                            
                            # Re-apply filters
                            await page.select_option('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', value='3')
                            await human_delay(1, 2)
                            
                            # Launch search
                            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche', timeout=30000)
                            await page.wait_for_load_state('networkidle', timeout=60000)
                            await human_delay(2, 3)
                            
                            logger.info("✅ Recovery successful - back on search page")
                            
                            # Navigate to the correct page if needed
                            if page_number > 1:
                                logger.info(f"Navigating to page {page_number}...")
                                page_input = await page.query_selector('input#ctl0_CONTENU_PAGE_resultSearch_numPageTop')
                                if page_input:
                                    await page_input.fill(str(page_number))
                                    await page_input.press('Enter')
                                    await page.wait_for_load_state('networkidle', timeout=30000)
                                    await human_delay(2, 3)
                            
                            # Retry getting tender links
                            continue
                            
                        except Exception as recovery_error:
                            logger.error(f"Recovery failed: {recovery_error}")
                            logger.error("Unable to recover. Stopping scraper.")
                            break
                
                # Move to next page
                page_number += 1
                tender_index = 0
                logger.info(f"Moving to page {page_number}...")
                continue
            
            total_tenders = len(current_links)
            tender_link = current_links[tender_index]
            
            try:
                logger.info(f"\nProcessing Page {page_number} - Tender {tender_index + 1}/{total_tenders} (Total: {total_processed_count + 1}/{MAX_TENDERS})...")
                
                # --- DATA EXTRACTION START ---
                try:
                    # Extract metadata using index-based selectors
                    # We assume all lists are aligned
                    
                    # 1. Category
                    categories = await page.query_selector_all('div[id*="panelBlocCategorie"]')
                    category_text = await categories[tender_index].inner_text() if tender_index < len(categories) else "N/A"
                    category_text = category_text.strip()
                    
                    # 2. Date of launch (div just under category)
                    # We use evaluate to get the next sibling's text
                    launch_date_text = "N/A"
                    if tender_index < len(categories):
                        launch_date_text = await categories[tender_index].evaluate('el => el.nextElementSibling ? el.nextElementSibling.innerText : "N/A"')
                        launch_date_text = launch_date_text.strip()

                    # 3. Reference
                    references = await page.query_selector_all('span[id*="reference"]')
                    reference_text = await references[tender_index].inner_text() if tender_index < len(references) else "N/A"
                    reference_text = reference_text.strip()
                    
                    # 4. Object
                    objects = await page.query_selector_all('div[id*="panelBlocObjet"]')
                    object_text = "N/A"
                    if tender_index < len(objects):
                        # Get inner text and clean it (remove "Objet :" prefix)
                        raw_object = await objects[tender_index].inner_text()
                        object_text = raw_object.replace("Objet :", "").strip()
                        # Remove newlines and extra spaces
                        object_text = " ".join(object_text.split())

                    # 5. Buyer
                    buyers = await page.query_selector_all('div[id*="panelBlocDenomination"]')
                    buyer_text = "N/A"
                    if tender_index < len(buyers):
                        raw_buyer = await buyers[tender_index].inner_text()
                        buyer_text = raw_buyer.replace("Acheteur public :", "").strip()
                        buyer_text = " ".join(buyer_text.split())

                    # 6. City
                    city_text = "N/A"
                    cities = await page.query_selector_all('div[id*="panelBlocLieuxExec"]')
                    if tender_index < len(cities):
                        raw_city = await cities[tender_index].inner_text()
                        # Extract first line (city name) before any <br> tags
                        city_lines = raw_city.split('\n')
                        if city_lines:
                            city_text = city_lines[0].strip()

                    # 7. Deadline - will be extracted from detail page
                    deadline_text = "..."  # Placeholder, will be updated from detail page

                    tender_data = {
                        "reference": reference_text, # Will be updated to composite
                        "original_reference": reference_text,
                        "category": category_text,
                        "launch_date": launch_date_text,
                        "object": object_text,
                        "buyer": buyer_text,
                        "city": city_text,
                        "deadline": deadline_text,
                        "scraped_at": datetime.now().isoformat()
                    }
                    
                    # Generate composite reference immediately
                    initials = generate_initials(buyer_text)
                    composite_ref = f"{reference_text}_{initials}"
                    tender_data["reference"] = composite_ref
                    
                    logger.info(f"Extracted Data: Ref={composite_ref} (Original={reference_text})")
                    
                    # Save into json as backup (keeping existing behavior)
                    # ... [snipped json logic]
                    
                    # Save to JSON file (append mode)
                    json_file = "tenders_services.json"
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except (FileNotFoundError, json.JSONDecodeError):
                        data = []
                    
                    data.append(tender_data)
                    
                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                        
                except Exception as e:
                    logger.error(f"Error extracting data for tender {tender_index + 1}: {e}")
                # --- DATA EXTRACTION END ---

                # Get the href before clicking (for logging)
                href = await tender_link.get_attribute('href')
                logger.info(f"Tender link: {href}")
                
                # Click the tender link to access detail page
                await tender_link.click()
                await page.wait_for_load_state('networkidle')
                await human_delay(1, 2)
                
                # Extract deadline from tender detail page
                try:
                    # Try multiple selectors for deadline
                    deadline_text = "N/A" # Initialize with N/A
                    
                    # Method 1: Look for "Date de clôture" or "Clôture" label
                    deadline_elements = await page.query_selector_all('div.cloture-line, div:has-text("Date de clôture"), div:has-text("Clôture")')
                    if deadline_elements:
                        for elem in deadline_elements:
                            text = await elem.inner_text()
                            if text and ("/" in text or ":" in text):  # Contains date/time
                                deadline_text = text.replace("Date de clôture :", "").replace("Clôture :", "").replace("\n", " ").strip()
                                break
                    
                    # Method 2: If still not found, try getting from any element containing date pattern
                    if deadline_text == "N/A": # Check against N/A now
                        all_text = await page.inner_text('body')
                        # Look for pattern like "DD/MM/YYYY HH:MM"
                        import re
                        date_pattern = r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}'
                        matches = re.findall(date_pattern, all_text)
                        if matches:
                            # Take the last match (usually the deadline)
                            deadline_text = matches[-1] if matches else "N/A"
                    
                    # Update tender_data with deadline from detail page
                    tender_data["deadline"] = deadline_text
                    
                    # Update JSON file with corrected deadline
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        # Update the last entry (the one we just added)
                        if data:
                            data[-1]["deadline"] = deadline_text
                        with open(json_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                    except Exception as update_error:
                        logger.warning(f"Could not update deadline in JSON: {update_error}")
                        
                except Exception as deadline_error:
                    logger.warning(f"Could not extract deadline from detail page: {deadline_error}")
                
                # Process this tender (DB save, download, upload, DB update)
                session = db.get_session() if db else None
                try:
                    success = await process_tender(page, tender_index + 1, total_tenders, tender_data, session, s3_client, s3_bucket)
                finally:
                    if session:
                        session.close()
                
                if success:
                    successful += 1
                else:
                    failed += 1
                
                # After returning to list, increment index and total count
                tender_index += 1
                total_processed_count += 1
                
                # Save state after each successful tender
                save_state(page_number, tender_index, total_processed_count)
                
                if total_processed_count >= MAX_TENDERS:
                    logger.info(f"Reached limit of {MAX_TENDERS} tenders. Stopping.")
                    break
                    
            except Exception as e:
                logger.error(f"Error with tender {tender_index + 1} on page {page_number}: {e}")
                failed += 1
                tender_index += 1
                continue
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("SCRAPING COMPLETE")
        logger.info("="*80)
        logger.info(f"Total pages processed: {page_number}")
        logger.info(f"Successfully downloaded: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"Fatal error during scraping: {e}", exc_info=True)
        
    finally:
        await browser.close()
        logger.info("Browser closed")


if __name__ == '__main__':
    asyncio.run(scrape_services())
