#!/usr/bin/env python3
"""
Missing Files Downloader
Downloads tender ZIP files that are missing from S3 by searching by reference number
"""
import asyncio
import random
import logging
import json
import os
import boto3
from pathlib import Path
from datetime import datetime
import unicodedata
from playwright.async_api import Page
from typing import List, Dict, Optional
from dotenv import load_dotenv
from database.models import Database, Tender, Buyer, Category
from scraper.browser_config import create_browser
from playwright_stealth import stealth_async

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('missing_files_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Moroccan names for form filling (same as scraper_fournitures.py)
MOROCCAN_FAMILY_NAMES = [
    'Bennani', 'ElAmrani', 'Alaoui', 'Idrissi', 'Berrada',
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


async def human_delay(min_sec=1, max_sec=3):
    """Random delay to mimic human behavior"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def human_scroll(page: Page):
    """Scroll page like a human"""
    for _ in range(random.randint(2, 4)):
        scroll_amount = random.randint(200, 500)
        await page.evaluate(f'window.scrollBy(0, {scroll_amount})')
        await human_delay(0.5, 1.5)
    
    if random.random() > 0.5:
        await page.evaluate(f'window.scrollBy(0, -{random.randint(100, 300)})')
        await human_delay(0.3, 0.8)


async def generate_moroccan_identity():
    """Generate random Moroccan identity for form"""
    first_name = random.choice(MOROCCAN_FIRST_NAMES)
    family_name = random.choice(MOROCCAN_FAMILY_NAMES)
    email_provider = random.choice(EMAIL_PROVIDERS)
    
    email = f"{first_name.lower()}.{family_name.lower()}{random.randint(100, 999)}@{email_provider}"
    
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


class MissingFilesDownloader:
    """Downloads missing tender files by searching by reference"""
    
    def __init__(self, downloads_dir='healer_downloads'):
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)
        
        # AWS Configuration
        self.aws_region = os.getenv('AWS_REGION', 'eu-west-3')
        self.s3_bucket = os.getenv('S3_BUCKET_NAME')
        
        # Database Configuration
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            db_host = os.getenv('DB_HOST')
            db_port = os.getenv('DB_PORT', '5432')
            db_name = os.getenv('DB_NAME')
            db_user = os.getenv('DB_USER')
            db_password = os.getenv('DB_PASSWORD')
            if all([db_host, db_name, db_user, db_password]):
                self.db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        if self.db_url:
            self.db = Database(self.db_url)
        else:
            logger.error("Database configuration missing!")
            raise ValueError("Database configuration missing")

        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            region_name=self.aws_region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        # Statistics
        self.stats = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'uploaded_to_s3': 0,
            'cleaned_up': 0
        }
        
        logger.info(f"MissingFilesDownloader initialized")
        logger.info(f"S3 Bucket: {self.s3_bucket}")
        logger.info(f"Downloads directory: {self.downloads_dir}")
    
    def fetch_missing_tenders_from_db(self) -> List[Tender]:
        """Fetch tenders from database where is_documents is False"""
        logger.info("Fetching missing tenders from database...")
        
        session = self.db.get_session()
        try:
            tenders = session.query(Tender).filter(Tender.is_documents == False).all()
            logger.info(f"Found {len(tenders)} tenders with missing documents")
            # Detach objects so we can use them after session close if needed, 
            # but better to keep session open or re-query. 
            # For simplicity in this script structure, we'll keep IDs and re-fetch or use a session per process.
            # Actually, let's return the list of IDs and references to be safe and simple.
            return [{'id': t.id, 'reference': t.reference} for t in tenders]
        except Exception as e:
            logger.error(f"Error fetching from database: {e}")
            return []
        finally:
            session.close()
    
    async def search_by_reference(
        self,
        page: Page,
        original_reference: str,
        target_composite_reference: str
    ) -> bool:
        """
        Search for tender by original reference and navigate to the correct one
        
        Args:
            page: Playwright page object
            original_reference: Reference without initials (e.g., "11/2025")
            target_composite_reference: Full reference with initials (e.g., "11/2025_DPMS")
            
        Returns:
            True if tender found and navigated to, False otherwise
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
            
            # Click search button with retry logic
            search_btn_selector = 'input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche'
            try:
                # Wait for button to be visible
                await page.wait_for_selector(search_btn_selector, state='visible', timeout=10000)
                await page.click(search_btn_selector, force=True)
                logger.info("Clicked search button")
            except Exception as e:
                logger.warning(f"Standard click failed: {e}. Trying JS click...")
                try:
                    await page.evaluate(f"document.querySelector('{search_btn_selector}').click()")
                    logger.info("Clicked search button via JS")
                except Exception as js_e:
                    logger.error(f"JS click failed: {js_e}")
                    return False
            
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
            
            # Read the number of pages from the span element using Playwright
            total_pages = 1
            try:
                page_count_element = await page.query_selector('span#ctl0_CONTENU_PAGE_resultSearch_nombrePageTop')
                if page_count_element:
                    text = await page_count_element.inner_text()
                    total_pages = int(text.strip())
                    logger.info(f"Total pages to search: {total_pages}")
            except Exception as e:
                logger.warning(f"Could not parse page count: {e}")
            
            # Search through all pages
            for current_page in range(1, total_pages + 1):
                logger.info(f"Searching page {current_page}/{total_pages}")
                
                # Get fresh HTML content for current page
                html_content = await page.content()
                from bs4 import BeautifulSoup
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
                    
                    # Use input box navigation for reliability
                    try:
                        next_page_num = current_page + 1
                        page_input = await page.query_selector('input#ctl0_CONTENU_PAGE_resultSearch_numPageTop')
                        if page_input:
                            await page_input.fill(str(next_page_num))
                            await page_input.press('Enter')
                            await page.wait_for_load_state('networkidle')
                            await human_delay(2, 3)
                        else:
                            # Fallback to link click if input not found
                            logger.warning("Page input not found, trying link...")
                            next_page_link = await page.query_selector(f'a[href*="numPageEnCours={next_page_num}"]')
                            if next_page_link:
                                await next_page_link.click()
                                await page.wait_for_load_state('networkidle')
                                await human_delay(2, 3)
                            else:
                                logger.error("Could not find method to navigate to next page")
                                break
                    except Exception as e:
                        logger.error(f"Navigation error: {e}")
                        break
            
            # No match found across all pages
            logger.error(f"❌ No match found for composite reference: {target_composite_reference} across {total_pages} page(s)")
            logger.warning("⚠️ Skipping download - no matching tender found")
            return False
            
        except Exception as e:
            logger.error(f"Error searching for reference {original_reference}: {e}")
            return False
    
    async def download_tender_file(self, page: Page, reference: str, expected_filename: str) -> Optional[str]:
        """Download tender ZIP file"""
        logger.info(f"Attempting to download file for: {reference}")
        
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
                async with page.expect_download(timeout=60000) as download_info:
                    await download_button.click(force=True)
                    logger.info("Clicked download button")
                
                download = await download_info.value
                
                # Use expected filename
                filepath = self.downloads_dir / expected_filename
                
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
            logger.error(f"Error downloading file for {reference}: {e}")
            return None
    
    def upload_to_s3(self, file_path: str, reference: str) -> bool:
        """Upload file to S3 bucket"""
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                logger.error(f"File not found: {file_path}")
                return False
            
            s3_key = f"tender-documents/{file_path_obj.name}"
            
            # Check if already exists
            try:
                self.s3_client.head_object(Bucket=self.s3_bucket, Key=s3_key)
                logger.info(f"File already exists in S3: {s3_key}")
                return True
            except:
                pass
            
            # Normalize metadata value to ASCII
            safe_reference = unicodedata.normalize('NFKD', reference).encode('ascii', 'ignore').decode('ascii')
            
            # Upload
            logger.info(f"Uploading {file_path_obj.name} to S3...")
            self.s3_client.upload_file(
                str(file_path),
                self.s3_bucket,
                s3_key,
                ExtraArgs={
                    'Metadata': {
                        'tender_reference': safe_reference,
                        'uploaded_at': datetime.now().isoformat()
                    }
                }
            )
            
            self.stats['uploaded_to_s3'] += 1
            logger.info(f"✅ Uploaded to S3: s3://{self.s3_bucket}/{s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            return False
    
    def cleanup_local_file(self, file_path: str) -> bool:
        """Delete local file after successful S3 upload"""
        try:
            file_path_obj = Path(file_path)
            if file_path_obj.exists():
                os.remove(file_path)
                self.stats['cleaned_up'] += 1
                logger.info(f"🗑️  Cleaned up local file: {file_path_obj.name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")
            return False
    


    async def process_missing_file(self, page: Page, tender_info: Dict) -> bool:
        """Process a single missing file"""
        tender_id = tender_info['id']
        reference = tender_info['reference']
        
        # Sanitize reference to create filename
        clean_ref = reference.replace('/', '_').replace("'", "_").replace(' ', '_')
        # Ensure we just use alphanumeric and standard separators
        clean_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in reference])
        expected_filename = f"{clean_ref}.zip"
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {reference} (ID: {tender_id})")
        logger.info(f"{'='*80}")
        
        try:
            # Search for tender
            # We assume the reference format is ORIGINAL_REF_INITIALS
            search_ref = reference.rsplit('_', 1)[0]
            found = await self.search_by_reference(page, search_ref, reference)
            if not found:
                logger.error(f"❌ Failed to find tender: {reference}")
                return False
            
            # Download file
            file_path = await self.download_tender_file(page, reference, expected_filename)
            if not file_path:
                logger.error(f"❌ Failed to download: {reference}")
                return False
            
            # Upload to S3
            uploaded = self.upload_to_s3(file_path, reference)
            if not uploaded:
                logger.error(f"❌ Failed to upload to S3: {reference}")
                return False
            
            # Update Database - Logic handled by Lambda
            logger.info("File uploaded to S3. DB update will be handled by Lambda.")
            
            # Cleanup local file
            self.cleanup_local_file(file_path)
            
            logger.info(f"✅ Successfully processed: {reference}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {reference}: {e}")
            return False
            
        finally:
            # Always navigate back to search page for next iteration
            await human_delay(2, 3)
            
            try:
                logger.info("Navigating back to search page via menu...")
                
                # Step 1: Click "Annonces" menu to activate it
                annonces_menu = await page.query_selector('a[onclick*="toggleMenu"][accesskey="a"]')
                if annonces_menu:
                    await annonces_menu.click()
                    logger.info("Clicked 'Annonces' menu")
                    await human_delay(0.5, 1)
                
                # Step 2: Click "Consultations en cours" link
                consultations_link = await page.query_selector('a[href="?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons"]')
                if consultations_link:
                    await consultations_link.click()
                    logger.info("Clicked 'Consultations en cours'")
                    await page.wait_for_load_state('networkidle')
                    await human_delay(2, 3)
                    logger.info("Returned to search page")
                else:
                    logger.warning("Could not find Consultations link, will try direct navigation on next iteration")
                    
            except Exception as nav_error:
                logger.warning(f"Error during return navigation: {nav_error}")
    
    async def run(self):
        """Main execution method"""
        logger.info("="*80)
        logger.info("MISSING FILES DOWNLOADER - STARTING")
        logger.info("="*80)
        
        # Fetch missing tenders from DB
        missing_tenders = self.fetch_missing_tenders_from_db()
        if not missing_tenders:
            logger.warning("No missing files found in database.")
            return
        
        self.stats['total'] = len(missing_tenders)
        
        # Create browser
        browser = await create_browser(headless=False)
        
        try:
            page = await browser.new_page()
            await stealth_async(page)
            await page.set_viewport_size({"width": 1920, "height": 1080})
            page.set_default_timeout(90000)
            
            # Process each missing file
            for idx, tender_info in enumerate(missing_tenders, 1):
                logger.info(f"\n[{idx}/{len(missing_tenders)}] Processing next tender...")
                
                success = await self.process_missing_file(page, tender_info)
                
                if success:
                    self.stats['successful'] += 1
                else:
                    self.stats['failed'] += 1
                
                # Progress update
                if idx % 5 == 0:
                    logger.info(f"Progress: {idx}/{len(missing_tenders)} | Success: {self.stats['successful']} | Failed: {self.stats['failed']}")
                
                await human_delay(2, 4)
            
        finally:
            await browser.close()
            logger.info("Browser closed")
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print execution summary"""
        logger.info("\n" + "="*80)
        logger.info("MISSING FILES DOWNLOADER - SUMMARY")
        logger.info("="*80)
        logger.info(f"Total files to process: {self.stats['total']}")
        logger.info(f"Successfully downloaded: {self.stats['successful']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Uploaded to S3: {self.stats['uploaded_to_s3']}")
        logger.info(f"Local files cleaned up: {self.stats['cleaned_up']}")
        logger.info("="*80)


async def main():
    """Main entry point"""
    # Remove older dependencies on args if any
    try:
        downloader = MissingFilesDownloader()
        await downloader.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")


if __name__ == '__main__':
    asyncio.run(main())
