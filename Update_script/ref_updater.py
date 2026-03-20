#!/usr/bin/env python3
"""
Reference Updater Script - New Approach
Gets HTML content of results page with 500 tenders and parses it efficiently
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set
from dotenv import load_dotenv
from playwright.async_api import Page
from database.models import Database, Tender
from scraper.browser_config import create_browser
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ref_updater.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ReferenceUpdater:
    """Compares database references with website references using HTML parsing"""
    
    def __init__(
        self,
        category: str = 'fournitures',
        output_file: str = 'new_references.json',
        database_url: str = None
    ):
        """
        Initialize ReferenceUpdater
        
        Args:
            category: Category to check ('travaux', 'fournitures', etc.)
            output_file: Output JSON file for new references
            database_url: Database connection URL
        """
        self.category = category.lower()
        self.output_file = Path(output_file)
        
        # Category mapping
        self.category_values = {
            'travaux': '1',
            'fournitures': '2',
            'services': '3'
        }
        
        if self.category not in self.category_values:
            raise ValueError(f"Invalid category: {category}. Must be one of {list(self.category_values.keys())}")
        
        self.category_value = self.category_values[self.category]
        
        # Initialize Database
        self.database_url = database_url or self._build_database_url()
        self.db = Database(self.database_url)
        
        # Storage for references
        self.db_references: Set[str] = set()
        self.website_references: Set[str] = set()
        self.new_references: List[Dict] = []
        
        logger.info(f"ReferenceUpdater initialized for category: {self.category}")
    
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
    
    def fetch_database_references(self) -> Set[str]:
        """Fetch all tender references from the database"""
        logger.info("Fetching references from database...")
        
        session = self.db.get_session()
        try:
            # Query all tender references for the specific category
            # Join with Category table to filter by category name
            from database.models import Category
            tenders = session.query(Tender.reference).join(
                Category, Tender.category_id == Category.id
            ).filter(
                Category.name.ilike(f'%{self.category}%')  # Case-insensitive partial match
            ).all()
            
            # Extract references from query results
            references = {ref[0] for ref in tenders if ref[0]}
            
            logger.info(f"Found {len(references)} references in database for category '{self.category}'")
            return references
            
        except Exception as e:
            logger.error(f"Error fetching database references: {e}")
            return set()
        finally:
            session.close()
    
    async def navigate_to_search_page(self, page: Page):
        """Navigate to the consultations search page"""
        logger.info("Navigating to consultations page...")
        
        try:
            await page.goto(
                'http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                wait_until='domcontentloaded',
                timeout=60000
            )
            logger.info("Successfully loaded consultations page")
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Error navigating to search page: {e}")
            raise
    
    async def select_category(self, page: Page):
        """Select the specified category"""
        logger.info(f"Selecting category: {self.category}...")
        
        try:
            await page.select_option(
                'select#ctl0_CONTENU_PAGE_AdvancedSearch_categorie',
                value=self.category_value
            )
            logger.info(f"Selected '{self.category}' category")
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error selecting category: {e}")
            raise
    
    async def launch_search(self, page: Page):
        """Click the search button"""
        logger.info("Launching search...")
        
        try:
            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche', timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=90000)
            await asyncio.sleep(3)
            logger.info("Search completed")
            
        except Exception as e:
            logger.error(f"Error launching search: {e}")
            raise
    
    async def set_results_per_page(self, page: Page, results_per_page: int = 500):
        """Set the number of results displayed per page"""
        logger.info(f"Setting results per page to {results_per_page}...")
        
        try:
            # Wait for the results per page selector to be available
            await page.wait_for_selector(
                'select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop',
                state='visible',
                timeout=30000
            )
            
            # Select the desired number of results per page
            await page.select_option(
                'select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop',
                value=str(results_per_page)
            )
            logger.info(f"Selected {results_per_page} results per page")
            
            # Wait for page to reload with new results count
            await page.wait_for_load_state('networkidle', timeout=120000)
            await asyncio.sleep(5)
            logger.info("Page reloaded with new results count")
            
        except Exception as e:
            logger.error(f"Error setting results per page: {e}")
            raise
    
    async def get_page_html(self, page: Page) -> str:
        """Get the HTML content of the current page"""
        logger.info("Getting page HTML content...")
        
        try:
            html_content = await page.content()
            logger.info(f"Retrieved HTML content ({len(html_content)} bytes)")
            return html_content
            
        except Exception as e:
            logger.error(f"Error getting page HTML: {e}")
            raise
    
    def generate_initials(self, name: str) -> str:
        """
        Generate initials from buyer name - New logic provided by user
        Matches logic in Db_Healer.py
        """
        if not name or name == "N/A":
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
    
    def parse_html_for_references(self, html_content: str) -> List[Dict]:
        """Parse HTML content to extract tender references using BeautifulSoup"""
        logger.info("Parsing HTML content for tender references...")
        
        try:
            import re
            soup = BeautifulSoup(html_content, 'html.parser')
            references_data = []
            
            # Find all reference spans
            reference_spans = soup.find_all('span', id=lambda x: x and 'reference' in x)
            total_refs = len(reference_spans)
            logger.info(f"Found {total_refs} reference elements in HTML")
            
            # Find all related data containers
            category_divs = soup.find_all('div', id=lambda x: x and 'panelBlocCategorie' in x)
            object_divs = soup.find_all('div', id=lambda x: x and 'panelBlocObjet' in x)
            buyer_divs = soup.find_all('div', id=lambda x: x and 'panelBlocDenomination' in x)
            deadline_divs = soup.find_all('div', class_='cloture-line')
            city_divs = soup.find_all('div', id=lambda x: x and 'panelBlocLieuxExec' in x)
            
            # Track composite references to detect true duplicates (same ref + same buyer)
            seen_composite_refs = set()
            
            # Extract data for each reference
            for idx, ref_span in enumerate(reference_spans):
                try:
                    # Reference (as shown on website)
                    original_reference = ref_span.get_text(strip=True)
                    
                    # Category
                    category_text = "N/A"
                    if idx < len(category_divs):
                        category_text = category_divs[idx].get_text(strip=True)
                    
                    # Launch date (next sibling of category)
                    launch_date_text = "N/A"
                    if idx < len(category_divs):
                        next_sibling = category_divs[idx].find_next_sibling()
                        if next_sibling:
                            launch_date_text = next_sibling.get_text(strip=True)
                    
                    # Object
                    object_text = "N/A"
                    if idx < len(object_divs):
                        raw_object = object_divs[idx].get_text(strip=True)
                        object_text = raw_object.replace("Objet :", "").strip()
                        object_text = " ".join(object_text.split())
                    
                    # Buyer
                    if idx < len(buyer_divs):
                        raw_buyer = buyer_divs[idx].get_text(strip=True)
                        # Robust cleanup of prefix using regex
                        buyer_text = re.sub(r'(?i)^Acheteur\s+public\s*[:\s]*', '', raw_buyer).strip()
                        # Fallback simple replace if regex doesn't match (unlikely but safe)
                        if "Acheteur public" in buyer_text:
                             buyer_text = buyer_text.replace("Acheteur public", "").replace(":", "").strip()
                        buyer_text = " ".join(buyer_text.split())
                    
                    # Deadline
                    deadline_text = "N/A"
                    if idx < len(deadline_divs):
                        deadline_raw = deadline_divs[idx].get_text(strip=True)
                        deadline_text = " ".join(deadline_raw.split())
                    
                    # City
                    city_text = "N/A"
                    if idx < len(city_divs):
                        city_raw = city_divs[idx].get_text(strip=True)
                        # Get first line
                        city_lines = city_raw.split('\n')
                        if city_lines:
                            city_text = city_lines[0].strip()
                    
                    # ALWAYS create composite reference to match database format
                    # Database stores as: original_reference_buyer_initials
                    buyer_initials = self.generate_initials(buyer_text)
                    composite_reference = f"{original_reference}_{buyer_initials}"
                    
                    # Log first 3 examples for verification
                    if len(references_data) < 3:
                        logger.info(f"Example composite ref: '{original_reference}' + '{buyer_initials}' = '{composite_reference}'")
                    
                    # Check for true duplicates (same reference + same buyer = same composite ref)
                    if composite_reference in seen_composite_refs:
                        logger.warning(f"True duplicate found: '{composite_reference}' (ref: '{original_reference}', buyer: '{buyer_text}'). Skipping.")
                        continue
                    
                    # Track this composite reference
                    seen_composite_refs.add(composite_reference)
                    
                    references_data.append({
                        'reference': composite_reference,  # Use composite reference for DB matching
                        'original_reference': original_reference,  # Keep original for reference
                        'buyer_initials': buyer_initials,  # Store initials for reference
                        'category': category_text,
                        'launch_date': launch_date_text,
                        'object': object_text,
                        'buyer': buyer_text,
                        'deadline': deadline_text,
                        'city': city_text,
                        'scraped_at': datetime.now().isoformat()
                    })
                    
                except Exception as e:
                    logger.warning(f"Error parsing reference at index {idx}: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(references_data)} references from HTML")
            return references_data
            
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            return []
    
    async def get_total_pages(self, page: Page) -> int:
        """Get the total number of pages from the page counter"""
        try:
            total_pages_element = await page.query_selector('span#ctl0_CONTENU_PAGE_resultSearch_nombrePageTop')
            
            if total_pages_element:
                total_pages_text = await total_pages_element.inner_text()
                total_pages = int(total_pages_text.strip())
                logger.info(f"Total pages available: {total_pages}")
                return total_pages
            else:
                logger.warning("Could not find total pages element, defaulting to 1")
                return 1
                
        except Exception as e:
            logger.error(f"Error getting total pages: {e}")
            return 1
    
    async def navigate_to_page(self, page: Page, page_number: int):
        """Navigate to a specific page number"""
        logger.info(f"Navigating to page {page_number}...")
        
        try:
            page_input = await page.query_selector('input#ctl0_CONTENU_PAGE_resultSearch_numPageTop')
            if page_input:
                await page_input.fill(str(page_number))
                await page_input.press('Enter')
                await page.wait_for_load_state('networkidle', timeout=120000)
                await asyncio.sleep(5)
                logger.info(f"Navigated to page {page_number}")
            else:
                logger.warning("Pagination input not found")
                
        except Exception as e:
            logger.error(f"Error navigating to page {page_number}: {e}")
            raise
    
    async def fetch_website_references(self, max_pages: int = None) -> List[Dict]:
        """Fetch all tender references from the website using HTML parsing"""
        logger.info("Fetching references from website...")
        
        browser = await create_browser(headless=False)
        all_references = []
        
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
            
            # Navigate and search
            await self.navigate_to_search_page(page)
            await self.select_category(page)
            await self.launch_search(page)
            
            # Set results per page to 500
            await self.set_results_per_page(page, results_per_page=500)
            
            # Get total number of pages
            total_pages = await self.get_total_pages(page)
            logger.info(f"Will process up to {total_pages} pages (or {max_pages} if limit set)")
            
            # Determine actual max pages to process
            actual_max_pages = total_pages
            if max_pages:
                actual_max_pages = min(max_pages, total_pages)
                logger.info(f"Limited to {actual_max_pages} pages by user setting")
            
            # Process pages
            current_page = 1
            
            while current_page <= actual_max_pages:
                logger.info(f"Processing page {current_page}/{actual_max_pages}...")
                
                # Get HTML content of current page
                html_content = await self.get_page_html(page)
                
                # Parse HTML for references
                page_references = self.parse_html_for_references(html_content)
                
                if not page_references:
                    logger.info("No more references found. Ending pagination.")
                    break
                
                all_references.extend(page_references)
                
                # Check if we've reached the last page
                if current_page >= actual_max_pages:
                    logger.info(f"Reached last page ({actual_max_pages}). Stopping pagination.")
                    break
                
                # Navigate to next page
                try:
                    current_page += 1
                    await self.navigate_to_page(page, current_page)
                    
                except Exception as e:
                    logger.error(f"Error navigating to page {current_page}: {e}")
                    break
            
            logger.info(f"Total references fetched from website: {len(all_references)}")
            return all_references
            
        except Exception as e:
            logger.error(f"Error fetching website references: {e}")
            return all_references
            
        finally:
            await browser.close()
    
    def compare_references(self, website_refs: List[Dict]) -> List[Dict]:
        """Compare website references with database references"""
        logger.info("Comparing references...")
        
        new_refs = []
        
        for ref_data in website_refs:
            ref = ref_data['reference']
            if ref not in self.db_references:
                new_refs.append(ref_data)
                logger.info(f"New reference found: {ref}")
        
        logger.info(f"Found {len(new_refs)} new references")
        return new_refs
    
    def save_new_references(self, new_refs: List[Dict]):
        """Save new references to JSON file"""
        logger.info(f"Saving new references to {self.output_file}...")
        
        try:
            output_data = {
                'category': self.category,
                'scan_date': datetime.now().isoformat(),
                'total_website_references': len(self.website_references),
                'total_database_references': len(self.db_references),
                'new_references_count': len(new_refs),
                'new_references': new_refs
            }
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=4)
            
            logger.info(f"Successfully saved {len(new_refs)} new references to {self.output_file}")
            
        except Exception as e:
            logger.error(f"Error saving new references: {e}")
    
    async def run(self, max_pages: int = None):
        """Main execution method"""
        logger.info("=" * 80)
        logger.info(f"STARTING REFERENCE UPDATE CHECK - {self.category.upper()} CATEGORY")
        logger.info("=" * 80)
        
        # Step 1: Fetch database references
        self.db_references = self.fetch_database_references()
        
        # Step 2: Fetch website references
        website_refs_data = await self.fetch_website_references(max_pages=max_pages)
        self.website_references = {ref['reference'] for ref in website_refs_data}
        
        # Step 3: Compare and find new references
        self.new_references = self.compare_references(website_refs_data)
        
        # Step 4: Save new references to JSON
        self.save_new_references(self.new_references)
        
        # Step 5: Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print execution summary"""
        logger.info("=" * 80)
        logger.info("REFERENCE UPDATE SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Category: {self.category}")
        logger.info(f"Database References: {len(self.db_references)}")
        logger.info(f"Website References: {len(self.website_references)}")
        logger.info(f"New References: {len(self.new_references)}")
        logger.info(f"Output File: {self.output_file}")
        logger.info("=" * 80)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Compare database references with website and find new tenders'
    )
    parser.add_argument(
        '--category',
        default='travaux',
        choices=['travaux', 'fournitures', 'services'],
        help='Category to check (default: travaux)'
    )
    parser.add_argument(
        '--output',
        default='new_references.json',
        help='Output JSON file (default: new_references.json)'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        help='Maximum number of pages to scan (default: all pages)'
    )
    parser.add_argument(
        '--database-url',
        help='Database URL (defaults to env var DATABASE_URL)'
    )
    
    args = parser.parse_args()
    
    # Create and run updater
    updater = ReferenceUpdater(
        category=args.category,
        output_file=args.output,
        database_url=args.database_url
    )
    
    try:
        await updater.run(max_pages=args.max_pages)
    except KeyboardInterrupt:
        logger.info("\nReference update interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    asyncio.run(main())
