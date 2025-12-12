"""
Production scraper for marchespublics.gov.ma - Fournitures category
Follows exact navigation steps with human-like behavior
"""
import asyncio
import random
import logging
from playwright.async_api import Page
from typing import List, Dict, Optional
from datetime import datetime
from scraper.browser_config import create_browser
import json
from faker import Faker
from playwright_stealth import stealth_async

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
    'Tazi', 'Fassi', 'Lazrak', 'Bensouda', 'El Kettani',
    'Chraibi', 'Sefrioui', 'Lahlou', 'Belkadi', 'Benjelloun',
    'Tahiri', 'Zniber', 'Amor', 'Bensaid', 'El Harti'
]

MOROCCAN_FIRST_NAMES = [
    'Ahmed', 'Mohamed', 'Fatima', 'Aicha', 'Youssef', 'Hassan',
    'Omar', 'Salma', 'Karim', 'Laila', 'Rachid', 'Samira',
    'Hamza', 'Nadia', 'Said', 'Zineb', 'Khalid', 'Amina',
    'Mehdi', 'Imane', 'Tarik', 'Khadija', 'Anas', 'Leila'
]

EMAIL_PROVIDERS = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com']


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
    """Step 1: Navigate to 'Consultations en cours' page"""
    logger.info("Step 1: Navigating to Consultations en cours...")
    
    # Go directly to the advanced search page (increased timeout)
    await page.goto('http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons', 
                    wait_until='domcontentloaded', timeout=60000)
    logger.info("Loaded Consultations page")
    
    await human_delay(2, 4)
    await human_scroll(page)


async def select_fournitures_category(page: Page):
    """Step 2: Select 'Fournitures' category"""
    logger.info("Step 2: Selecting 'Fournitures' category...")
    
    # Scroll to the category dropdown
    await human_scroll(page)
    
    # Select Fournitures (value="2")
    await page.select_option(
        'select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie',
        value='2'
    )
    logger.info("Selected 'Fournitures' category")
    
    await human_delay(1, 2)


async def launch_search(page: Page):
    """Step 3: Click search button"""
    logger.info("Step 3: Launching search...")
    
    # Scroll to search button
    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    await human_delay(0.5, 1)
    
    # Click search button
    await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
    logger.info("Clicked 'Lancer la recherche'")
    
    await page.wait_for_load_state('networkidle')
    await human_delay(3, 5)


async def get_tender_rows(page: Page) -> List:
    """Step 4: Get all tender access links"""
    logger.info("Step 4: Getting tender access links...")
    
    # Find all links with href containing "EntrepriseDetailConsultation"
    # These are the "Accéder à la consultation" links
    tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
    logger.info(f"Found {len(tender_links)} tender links")
    
    return tender_links


async def process_tender(page: Page, tender_index: int, total_tenders: int, tender_reference: str = "unknown"):
    """Process a single tender: download document and return to list"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Processing Tender {tender_index}/{total_tenders} - Ref: {tender_reference}")
    logger.info(f"{'='*80}")
    
    try:
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
            
            # Sanitize reference for filename
            safe_ref = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in tender_reference])
            filename = f"{safe_ref}.zip"
            filepath = f"./downloads/{filename}"
            
            await download.save_as(filepath)
            logger.info(f"✅ Downloaded: {filepath}")
            
            # Wait for download to fully complete
            await human_delay(2, 3)
            return True
        else:
            logger.warning("Download button not found")
            return False
        
    except Exception as e:
        logger.error(f"Error processing tender {tender_index}: {e}")
        return False
        
    finally:
        await human_delay(2, 3)
        
        # Navigate back to search results using menu system
        logger.info("Navigating back to tender list via menu...")
        
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
            
            # Re-apply search filters (Fournitures category)
            logger.info("Re-applying Fournitures filter...")
            # Wait for selector explicitly with long timeout
            await page.wait_for_selector('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', state='visible', timeout=60000)
            await page.select_option('select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie', value='2', timeout=60000)
            await human_delay(1, 2)
            
            # Click search button
            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
            await page.wait_for_load_state('networkidle')
            await human_delay(2, 3)
            logger.info("Returned to search results")


async def scrape_fournitures():
    """Main scraping function"""
    logger.info("\n" + "="*80)
    logger.info("STARTING PRODUCTION SCRAPER - FOURNITURES CATEGORY")
    logger.info("="*80 + "\n")
    
    # Create browser in VISIBLE mode for debugging
    browser = await create_browser(headless=False)
    
    try:
        page = await browser.new_page()
        
        # Execute scraping steps
        await stealth_async(page)
        await page.set_viewport_size({"width": 1920, "height": 1080})
        
        # Increase default timeout for all operations
        page.set_default_timeout(90000)
        
        await navigate_to_consultations(page)
        await select_fournitures_category(page)
        await launch_search(page)
        
        # Get all tender access links
        tender_links = await get_tender_rows(page)
        
        if not tender_links:
            logger.warning("No tenders found!")
            return
        
        # Process tenders with pagination
        MAX_TENDERS = 40
        total_processed_count = 0
        successful = 0
        failed = 0
        page_number = 1
        tender_index = 0
        
        while total_processed_count < MAX_TENDERS:
            # If we need to be on a specific page > 1, navigate to it
            # (The "Return" logic resets us to Page 1, so we must re-navigate if needed)
            if page_number > 1:
                logger.info(f"Navigating to page {page_number}...")
                page_input = await page.query_selector('input#ctl0_CONTENU_PAGE_resultSearch_numPageTop')
                if page_input:
                    await page_input.fill(str(page_number))
                    await page_input.press('Enter')
                    await page.wait_for_load_state('networkidle')
                    await human_delay(2, 3)
                else:
                    logger.warning("Pagination input not found, stopping.")
                    break

            # Re-query tender links each iteration (fresh DOM elements)
            current_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
            
            # Check if we finished the current page
            if tender_index >= len(current_links):
                logger.info(f"Finished processing page {page_number}")
                
                # If we found no links on this page, it means we reached the end
                if len(current_links) == 0:
                    logger.info("No tenders found on this page. End of scraping.")
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

                    # 6. Deadline
                    deadlines = await page.query_selector_all('div.cloture-line')
                    deadline_text = await deadlines[tender_index].inner_text() if tender_index < len(deadlines) else "N/A"
                    deadline_text = deadline_text.replace("\n", " ").strip()

                    tender_data = {
                        "reference": reference_text,
                        "category": category_text,
                        "launch_date": launch_date_text,
                        "object": object_text,
                        "buyer": buyer_text,
                        "deadline": deadline_text,
                        "scraped_at": datetime.now().isoformat()
                    }
                    
                    logger.info(f"Extracted Data: {tender_data}")
                    
                    # Save to JSON file (append mode)
                    json_file = "tenders.json"
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
                
                # Click the tender link
                await tender_link.click()
                await page.wait_for_load_state('networkidle')
                await human_delay(1, 2)
                
                # Process this tender
                success = await process_tender(page, tender_index + 1, total_tenders, reference_text)
                
                if success:
                    successful += 1
                else:
                    failed += 1
                
                # After returning to list, increment index and total count
                tender_index += 1
                total_processed_count += 1
                
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
    asyncio.run(scrape_fournitures())
