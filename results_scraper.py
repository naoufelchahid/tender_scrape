#!/usr/bin/env python3
"""
Tender Results Scraper
Identifies tenders past their deadline that lack results, scrapes them, and uploads to S3.
"""
import asyncio
import logging
import os
import boto3
import zipfile
import random
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

from playwright.async_api import Page, async_playwright
from playwright_stealth import stealth_async
from database.models import Database, Tender
from sqlalchemy import or_
from bs4 import BeautifulSoup

# Reuse utilities from Db_updater if possible, or redefine them here for standalone execution
# Assuming we can copy some helper functions or import them if they were in a shared module.
# Since Db_updater.py is a script, importing from it might execute it if not careful.
# It has a "if __name__ == '__main__':" block but also code at top level.
# Safer to redefine the helpers for now.

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('results_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

# Initial generation function
def generate_initials(name):
    """Generate initials from buyer name - Same logic as Db_updater"""
    if not name:
        return "UNK"
    
    ignore = ['LE', 'LA', 'LES', 'DE', 'DES', 'DU', 'ET', 'EN', 'AU', 'AUX', 'A']
    clean_name = name.upper().replace('-', ' ').replace('_', ' ').replace("'", " ")
    words = [w for w in clean_name.split() if w not in ignore and len(w) > 1]
    
    if not words:
        return name[:3].upper()
    
    if len(words) == 1:
        return words[0][:3]
    
    if 2 <= len(words) <= 3:
        return "".join(words)
    else:
        return "".join([w[:3] for w in words])

class ResultsScraper:
    def __init__(self, database_url: Optional[str] = None):
        self.downloads_dir = Path("download_results")
        self.downloads_dir.mkdir(exist_ok=True)
        
        # Database
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
             # Try building from individual components (fallback same as Db_updater)
            db_host = os.getenv('DB_HOST')
            db_port = os.getenv('DB_PORT', '5432')
            db_name = os.getenv('DB_NAME')
            db_user = os.getenv('DB_USER')
            db_password = os.getenv('DB_PASSWORD')
            if all([db_host, db_name, db_user, db_password]):
                self.database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            else:
                raise ValueError("Database configuration not found.")
                
        self.db = Database(self.database_url)
        
        # S3 Config
        self.aws_region = os.getenv('AWS_REGION', 'eu-west-3')
        self.s3_bucket = os.getenv('S3_BUCKET_NAME')
        
        if not self.s3_bucket:
            logger.warning("S3_BUCKET_NAME not set.")
            
        self.s3_client = boto3.client(
            's3', 
            region_name=self.aws_region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )

    def get_pending_tenders(self) -> List[Tender]:
        """
        Get tenders where:
        1. is_results is False
        2. deadline is older than 4 days OR deadline is NULL
        """
        session = self.db.get_session()
        try:
            four_days_ago = datetime.now() - timedelta(days=4)
            
            tenders = session.query(Tender).filter(
                Tender.is_results == False,
                or_(
                    Tender.deadline < four_days_ago,
                    Tender.deadline == None
                )
            ).all()
            
            logger.info(f"Found {len(tenders)} tenders pending results.")
            return tenders
        finally:
            session.close()

    async def search_and_download(self, page: Page, tender: Tender) -> bool:
        """
        Search for the tender and download results file if available.
        """
        logger.info(f"Processing tender: {tender.reference}")
        
        # Extract original reference from composite reference
        # Composite is like "11/2025_DPMS" -> Original "11/2025"
        # Assumption: The original reference is everything before the last underscore, 
        # BUT initials logic might be complex. 
        # Better strategy: Reference field in DB IS the composite. 
        # We need the original reference to search.
        # If we stored raw_data, we might have it there.
        if tender.raw_data and isinstance(tender.raw_data, dict):
            # Db_updater saves 'original_reference' in raw_data
            original_ref = tender.raw_data.get('original_reference')
            
            # If not found, check if 'reference' is distinct or if we need to split
            if not original_ref:
                ref_in_data = tender.raw_data.get('reference')
                if ref_in_data and '_' in ref_in_data:
                     # It's likely the composite
                    pass
                else:
                    # Maybe it is the original?
                    pass

        if not original_ref:
            # Fallback: try splitting by the *last* underscore
            # Composite format: "{original}_{initials}"
            # Warning: Original ref might contain underscores too (e.g. "12_2025")
            # But Initials are appended at the end.
            if '_' in tender.reference:
                original_ref = tender.reference.rsplit('_', 1)[0]
            else:
                original_ref = tender.reference
        
        logger.info(f"Searching with original reference: {original_ref}")

        try:
            await page.goto(
                'https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AllAnn',
                wait_until='domcontentloaded',
                timeout=60000
            )
            
            await human_delay(1, 2)
            
            # Fill reference
            ref_input = await page.query_selector('input#ctl0_CONTENU_PAGE_AdvancedSearch_reference')
            if ref_input:
                await ref_input.fill(original_ref)
                
                # Select "Annonce d'extrait de PV" (value="5")
                # Wait for the select to be available
                await page.wait_for_selector('select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType')
                await page.select_option('select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType', '5')
                logger.info("Selected 'Annonce d'extrait de PV'")
                
                await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
                await page.wait_for_load_state('networkidle')
                await human_delay(2, 3)
            else:
                logger.error("Could not find reference input field.")
                return False

            # ------------------------------------------------------------------
            # Multi-page Search Logic (Adapted from Db_updater.py)
            # ------------------------------------------------------------------
            
            # Change page size to 500 if available
            page_size_select = await page.query_selector('select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop')
            if page_size_select:
                logger.info("Setting page size to 500...")
                await page.select_option('select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop', '500')
                await page.wait_for_load_state('networkidle')
                await human_delay(2, 3)
            
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
                
                # Find all rows that contain the tenders by looking for buyer divs
                buyer_divs = soup.find_all('div', id=lambda x: x and 'panelBlocDenomination' in x)
                tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
                
                found_tender_on_page = False
                
                for idx, buyer_div in enumerate(buyer_divs):
                    if idx >= len(tender_links):
                        break
                        
                    # 1. Verify it's the right tender (Composite Match)
                    buyer_text = buyer_div.get_text(strip=True).replace("Acheteur public :", "").strip()
                    buyer_text = " ".join(buyer_text.split())
                    initials = generate_initials(buyer_text)
                    composite_ref = f"{original_ref}_{initials}"
                    
                    if composite_ref == tender.reference:
                        found_tender_on_page = True
                        logger.info(f"Found matched tender row: {composite_ref}")
                        
                        # Click match: Look for the specific image "picto-acces-consultation.gif"
                        # The user said: "clikck on <img src="themes/images/picto-acces-consultation.gif" ...> of the matched elements"
                        # This image is usually inside the 'a' tag (tender_links[idx]).
                        # We can just click the link as before, as it is the access link.
                        # But to be precise, let's verify if we need to click specifically an icon.
                        # Usually tender_links[idx] wraps the whole title or action. 
                        # Let's assume clicking the main link is still correct, likely it contains the image.
                        # Wait, user said "click on <img ...>". If the image is inside an anchor, clicking the anchor works.
                        # Let's verify if the image is indeed in the link we grabbed.
                        
                        await tender_links[idx].click()
                        await page.wait_for_load_state('networkidle')
                        await human_delay(2, 3)
                        
                        # Find download link: "Fichier joint - ..."
                        # User example: <a ... href="index.php?page=entreprise.EntrepriseDownloadAvisJAL...">Fichier joint - ...</a>
                        # Selector: a containing text "Fichier joint" or href containing "DownloadAvis"
                        download_link = await page.query_selector('a:has-text("Fichier joint"), a[href*="EntrepriseDownloadAvisJAL"]')
                        
                        if download_link:
                            logger.info("Found 'Fichier joint' download link.")
                            # Download flow
                            async with page.expect_download() as download_info:
                                await download_link.click()
                            
                            download = await download_info.value
                            
                            # Fix extension
                            suggested = download.suggested_filename
                            ext = Path(suggested).suffix or ".zip"
                            filename = f"{tender.reference}_results{ext}"
                            
                            filepath = self.downloads_dir / filename
                            await download.save_as(str(filepath))
                            logger.info(f"Downloaded: {filepath}")
                            return str(filepath)
                        else:
                            logger.warning("Entered detail page but could not find 'Fichier joint' link.")
                            await page.go_back()
                            await page.wait_for_load_state('networkidle')
                            # Need to re-set page size if we go back? 
                            # Usually session keeps it, but safer to assume we might need to handle it if we lost state.
                            # But typically we just break and return False if not found here for now.
                        break # Stop checking rows if we matched the tender
                
                if found_tender_on_page:
                    break # Stop pagination if we found our tender
                
                # Navigate to next page if not found
                if current_page < total_pages:
                    logger.info(f"Match not found on page {current_page}, navigating to next page...")
                    next_page_link = await page.query_selector(f'a[href*="numPageEnCours={current_page + 1}"]')
                    if next_page_link:
                        await next_page_link.click()
                        await page.wait_for_load_state('networkidle')
                        await human_delay(2, 3)
                    else:
                        logger.warning(f"Could not find link to page {current_page + 1}")
                        break

        except Exception as e:
            logger.error(f"Error processing {tender.reference}: {e}")
            return False

        return False

    def unzip_and_upload(self, file_path: str, tender: Tender):
        """
        Process downloaded file:
        1. Extract (if zip) to memory or use directly.
        2. Identify PDF and DOCX files ONLY.
        3. Save strictly to downloads_dir (no subfolders).
        4. Upload to S3 (flat structure).
        5. Ensure uniqueness via MD5 cache (per run/tender).
        """
        if not file_path or not os.path.exists(file_path):
            return

        import shutil
        import hashlib
        
        path_obj = Path(file_path)
        processed_hashes = set()
        
        # Helper to calc hash
        def get_file_hash(params_path):
            hasher = hashlib.md5()
            with open(params_path, 'rb') as afile:
                buf = afile.read()
                hasher.update(buf)
            return hasher.hexdigest()

        try:
            # We will collect (source_path, original_filename) tuples to process
            # source_path might be the temp extracted file or the original file
            
            # Since we must NOT create folders, if it's a zip, we need to extract files one by one 
            # and process them, or extract them to the MAIN downloads dir temporarily (risky if name collision)
            # OR better: use a temporary file for extraction to avoid folder creation?
            # The user said "remove any folder cration logic".
            # So we extract directly to `self.downloads_dir` but flatten the path?
            # Or better, just extract to a temp file, process, then delete.
            
            if path_obj.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        # Iterate over files in zip
                        for member in zip_ref.infolist():
                            if member.is_dir():
                                continue
                            
                            filename = os.path.basename(member.filename)
                            ext = os.path.splitext(filename)[1].lower()
                            
                            if ext not in ['.pdf', '.docx']:
                                continue
                                
                            # Extract to a temp unique name in downloads_dir
                            # We use read() to avoid extracting directory structure
                            source_content = zip_ref.read(member)
                            
                            # Check hash for uniqueness
                            content_hash = hashlib.md5(source_content).hexdigest()
                            if content_hash in processed_hashes:
                                logger.info(f"Skipping duplicate file in zip: {filename}")
                                continue
                            processed_hashes.add(content_hash)
                            
                            # Determine final filename
                            clean_ref = self._sanitize_filename(tender.reference)
                            # Use count of processed valid files to determine index
                            idx = len(processed_hashes)
                            if idx == 1:
                                new_filename = f"result_{clean_ref}{ext}"
                            else:
                                new_filename = f"result_{clean_ref}_{idx}{ext}"
                            
                            dest_path = self.downloads_dir / new_filename
                            
                            # Write directly
                            with open(dest_path, 'wb') as f:
                                f.write(source_content)
                                
                            logger.info(f"Extracted and saved: {dest_path.name}")
                            
                            # Upload to S3 (Flat key under tender_results/)
                            # Key: tender_results/result_REF_1.pdf
                            s3_key = f"tender_results/{new_filename}"
                            self.upload_file_to_s3(dest_path, s3_key)
                            
                except zipfile.BadZipFile:
                    logger.error(f"Bad zip file: {file_path}")
            else:
                # Single file
                ext = path_obj.suffix.lower()
                if ext in ['.pdf', '.docx']:
                    # Hash check
                    current_hash = get_file_hash(path_obj)
                    if current_hash not in processed_hashes:
                        clean_ref = self._sanitize_filename(tender.reference)
                        new_filename = f"result_{clean_ref}{ext}"
                        
                        dest_path = self.downloads_dir / new_filename
                        
                        # Move/Rename
                        shutil.move(str(path_obj), str(dest_path))
                        logger.info(f"Processed file: {dest_path.name}")
                        
                        s3_key = f"tender_results/{new_filename}"
                        self.upload_file_to_s3(dest_path, s3_key)
                    else:
                         logger.info(f"Skipping duplicate file: {path_obj.name}")

        except Exception as e:
            logger.error(f"Error processing files for {tender.reference}: {e}")
        finally:
            # Cleanup: If it was a zip, remove it. If it was single file and moved, it's gone.
            # If it was single file and NOT moved (wrong extension), remove it.
            if path_obj.exists():
                os.remove(path_obj)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize string for filename use"""
        # Replace slashes and other dangerous chars
        return name.replace('/', '_').replace('\\', '_')

    def upload_file_to_s3(self, file_path: Path, s3_key: str):
        """
        Upload file to S3.
        For PDF files: Upload to both tender_results/ and results_lambda_ocr/
        For DOCX files: Upload only to tender_results/
        """
        if not self.s3_bucket:
            return
            
        try:
            # Upload to the original location (tender_results/)
            logger.info(f"Uploading {s3_key}")
            self.s3_client.upload_file(str(file_path), self.s3_bucket, s3_key)
            
            # If it's a PDF, also copy to results_lambda_ocr/ for Lambda processing
            if file_path.suffix.lower() == '.pdf':
                # Create the Lambda OCR key by replacing tender_results/ with results_lambda_ocr/
                lambda_ocr_key = s3_key.replace('tender_results/', 'results_lambda_ocr/', 1)
                logger.info(f"Copying PDF to Lambda OCR folder: {lambda_ocr_key}")
                self.s3_client.upload_file(str(file_path), self.s3_bucket, lambda_ocr_key)
                
        except Exception as e:
            logger.error(f"S3 Upload failed: {e}")

    def update_tender_status(self, tender: Tender):
        # User requested to REMOVE DB update
        # Keeping method structure but disabling logic
        pass
        # session = self.db.get_session()
        # try:
        #     t = session.query(Tender).get(tender.id)
        #     if t:
        #         t.is_results = True
        #         session.commit()
        #         logger.info(f"Updated status is_results=True for {tender.reference}")
        # except Exception as e:
        #     logger.error(f"DB Update failed: {e}")
        # finally:
        #     session.close()

    async def run(self):
        tenders = self.get_pending_tenders()
        if not tenders:
            logger.info("No pending tenders found.")
            return

        async with async_playwright() as p:
            # Launch browser with robust args from browser_config.py
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--window-position=0,0',
                    '--ignore-certificate-errors',
                    '--ignore-certificate-errors-spki-list',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--allow-running-insecure-content',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-default-apps',
                    '--no-default-browser-check',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-hang-monitor',
                    '--disable-prompt-on-repost',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--password-store=basic',
                    '--use-mock-keychain',
                    '--lang=fr-FR'
                ]
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            
            # Stealth not strictly necessary if just navigating, but good practice
            # await stealth_async(page) 
            
            page = await context.new_page()
            
            for tender in tenders:
                file_path = await self.search_and_download(page, tender)
                if file_path:
                    self.unzip_and_upload(file_path, tender)
                    
            await browser.close()

if __name__ == "__main__":
    scraper = ResultsScraper()
    asyncio.run(scraper.run())
