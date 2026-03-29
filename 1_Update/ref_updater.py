#!/usr/bin/env python3
"""
Reference Updater Script - Phase 1 of Pipeline
Fetches tender references from Apache Jena Fuseki and compares with website data.
Uses SPARQL queries to extract existing triples where buyer ==Has_Launched==> tender.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Tuple
from dotenv import load_dotenv
from playwright.async_api import Page
from browser_config import create_browser
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
import rdflib
from rdflib import URIRef, Literal, Namespace

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

# Define namespaces for TenderIntelligence ontology
TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
AD = Namespace("http://www.tenderintelligence.io/ontology/activity-domains#")
RDF = rdflib.RDF
RDFS = rdflib.RDFS


class JenaClient:
    """Client for interacting with Apache Jena Fuseki SPARQL endpoint"""
    
    def __init__(self, endpoint: str = None, update_endpoint: str = None, 
                 username: str = None, password: str = None):
        """
        Initialize Jena SPARQL client
        
        Args:
            endpoint: SPARQL query endpoint URL
            update_endpoint: SPARQL update endpoint URL
            username: Basic auth username
            password: Basic auth password
        """
        self.endpoint = endpoint or os.getenv('JENA_ENDPOINT')
        self.update_endpoint = update_endpoint or os.getenv('JENA_UPDATE_ENDPOINT')
        self.username = username or os.getenv('JENA_USERNAME')
        self.password = password or os.getenv('JENA_PASSWORD')
        
        # Check if running in Docker or locally
        # The .env may have 'fuseki:3030' in self.endpoint:
            # Check if we can resolve 'fuseki' hostname, if not fallback to localhost
            import socket
            try:
                socket.gethostbyname('fuseki')
            except socket.gaierror:
                logger.warning("Cannot resolve 'fuseki' hostname. Are you running outside Docker? Attempting localhost...")
                # Try to use localhost instead (for local development)
                self.endpoint = self.endpoint.replace('fuseki', 'localhost')
                if self.update_endpoint:
                    self.update_endpoint = self.update_endpoint.replace('fuseki', 'localhost')
        
        if not self.endpoint:
            raise ValueError("JENA_ENDPOINT not configured. Please set in .env")
        
        # Create authenticated session if credentials provided
        self.auth = None
        if self.username and self.password:
            import requests
            self.auth = (self.username, self.password)
            self.session = requests.Session()
            self.session.auth = self.auth
        else:
            self.session = requests.Session()
        
        logger.info(f"JenaClient initialized with endpoint: {self.endpoint}")
    
    def query(self, sparql: str) -> List[Dict]:
        """
        Execute SPARQL SELECT query
        
        Args:
            sparql: SPARQL query string
            
        Returns:
            List of result bindings
        """
        try:
            response = self.session.get(
                self.endpoint,
                params={'query': sparql},
                timeout=60
            )
            response.raise_for_status()
            
            # Parse JSON results
            data = response.json()
            return data.get('results', {}).get('bindings', [])
            
        except Exception as e:
            logger.error(f"SPARQL query error: {e}")
            return []
    
    def query_has_launched_relations(self, category: str = None) -> List[Tuple[str, str]]:
        """
        Query all tender-buyer relations where buyer has launched tender.
        Returns tuples of (tender_reference, buyer_name)
        
        Args:
            category: Optional category filter (travaux, fournitures, services)
            
        Returns:
            List of tuples (tender_reference, buyer_name)
        """
        logger.info("Querying Jena for Has_Launched relations...")
        
        # SPARQL query to get all buyer-tender relations
        # Uses the TenderIntelligence ontology: tender --Launched_by--> buyer
        sparql = f"""
        PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
        PREFIX ad: <http://www.tenderintelligence.io/ontology/activity-domains#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?tender ?buyer ?buyerName ?tenderRef
        WHERE {{
            ?tender rdf:type ts:Tenders .
            ?tender ts:Launched_by ?buyer .
            ?tender ts:Has_Original_Reference ?tenderRef .
            ?buyer rdfs:label ?buyerName .
        """
        
        if category:
            # Add category filter
            # Match capitalized category name (Travaux, Fournitures, Services)
            category_uri = f"ad:{category.capitalize()}"
            sparql += f"""
            ?tender ts:Has_Category {category_uri} .
            """
        
        sparql += "}"
        
        results = self.query(sparql)
        
        relations = []
        for row in results:
            tender_ref = row.get('tenderRef', {}).get('value', '')
            buyer_name = row.get('buyerName', {}).get('value', '')
            
            if tender_ref and buyer_name:
                relations.append((tender_ref, buyer_name))
        
        logger.info(f"Found {len(relations)} tender-buyer relations in Jena")
        return relations


class ReferenceUpdater:
    """Compares Jena database references with website references using HTML parsing"""
    
    def __init__(
        self,
        category: str = 'fournitures',
        output_file: str = 'new_references.json',
        jena_endpoint: str = None,
        jena_update_endpoint: str = None,
        jena_username: str = None,
        jena_password: str = None
    ):
        """
        Initialize ReferenceUpdater
        
        Args:
            category: Category to check ('travaux', 'fournitures', 'services')
            output_file: Output JSON file for new references
            jena_endpoint: Jena SPARQL query endpoint
            jena_update_endpoint: Jena SPARQL update endpoint
            jena_username: Jena basic auth username
            jena_password: Jena basic auth password
        """
        self.category = category.lower()
        self.output_file = Path(output_file)
        
        # Category mapping (matches website's <select> options)
        self.category_values = {
            'travaux': '1',
            'fournitures': '2',
            'services': '3'
        }
        
        if self.category not in self.category_values:
            raise ValueError(f"Invalid category: {category}. Must be one of {list(self.category_values.keys())}")
        
        self.category_value = self.category_values[self.category]
        
        # Initialize Jena client
        self.jena = JenaClient(
            endpoint=jena_endpoint,
            update_endpoint=jena_update_endpoint,
            username=jena_username,
            password=jena_password
        )
        
        # Storage for references - now using tuples (tender_reference, buyer_name)
        self.jena_references: Set[Tuple[str, str]] = set()
        self.website_references: Set[Tuple[str, str]] = set()
        self.new_references: List[Dict] = []
        
        logger.info(f"ReferenceUpdater initialized for category: {self.category}")
    
    def fetch_jena_references(self) -> Set[Tuple[str, str]]:
        """Fetch all tender-buyer tuples from Jena where buyer has launched tender"""
        logger.info("Fetching references from Apache Jena...")
        
        try:
            # Query Jena for all Has_Launched relations
            relations = self.jena.query_has_launched_relations(category=self.category)
            
            # Convert to set of tuples
            references = set(relations)
            
            logger.info(f"Found {len(references)} references in Jena for category '{self.category}'")
            return references
            
        except Exception as e:
            logger.error(f"Error fetching Jena references: {e}")
            return set()
    
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
        Generate initials from buyer name - matches logic in Db_updater.py
        """
        if not name or name == "N/A":
            return "UNK"
        
        # Common words to ignore (French articles)
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
    
    def parse_deadline(self, deadline_text: str) -> str:
        """
        Parse deadline text to extract date and hour as datetime stamp.
        Handles format: "DD/MM/YYYY<br>HH:MM" or "DD/MM/YYYY HH:MM"
        
        Args:
            deadline_text: Raw deadline text from HTML
            
        Returns:
            ISO format datetime string, None if no deadline, or original text if parsing fails
        """
        # Return None for empty, N/A, or placeholder values (no deadline)
        if not deadline_text or deadline_text in ("N/A", "..."):
            return None
        
        try:
            # Handle <br> tags in HTML
            text = deadline_text.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
            text = ' '.join(text.split())  # Normalize whitespace
            
            # Match pattern: DD/MM/YYYY HH:MM or DD/MM/YYYYHH:MM (no space)
            # The site bug produces: "03/02/202610:00" without space
            pattern = r'(\d{2}/\d{2}/\d{4})(?:\s*)(\d{2}:\d{2})?'
            match = re.match(pattern, text)
            
            if match:
                date_str = match.group(1)
                time_str = match.group(2) if match.group(2) else "00:00"
                
                # Parse as datetime
                dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                return dt.isoformat()
            
            # If pattern doesn't match, return None (no valid deadline)
            logger.warning(f"Could not parse deadline '{deadline_text}', returning None")
            return None
            
        except Exception as e:
            logger.warning(f"Error parsing deadline '{deadline_text}': {e}")
            return None
    
    def parse_html_for_references(self, html_content: str) -> List[Dict]:
        """
        Parse search results HTML to extract VALIDATION TUPLES ONLY.

        Purpose: fast comparison with Jena. Rich metadata (object, deadline,
        city, contacts, etc.) is extracted exclusively from each tender's
        detail page by Db_updater.py for data integrity.

        Extracted fields per row:
            original_reference  — the reference as shown on the site
            buyer               — buyer name (cleaned)
            buyer_initials      — generated initials used to build composite ref
            composite_reference — "{original_reference}_{buyer_initials}"
            category            — tender category (Travaux / Fournitures / Services)
            launch_date         — publication date string (raw, from search row)
        """
        logger.info("Parsing HTML for validation tuples (ref + buyer)...")

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            references_data = []

            # --- Locate per-row source elements ---------------------------------
            # Each tender row on the results page contains one of each:
            reference_spans = soup.find_all('span', id=lambda x: x and 'reference' in x)
            buyer_divs = soup.find_all('div', id=lambda x: x and 'panelBlocDenomination' in x)
            category_divs = soup.find_all('div', id=lambda x: x and 'panelBlocCategorie' in x)

            total = len(reference_spans)
            logger.info(f"Found {total} tender rows in results page")

            seen_composite_refs: set = set()

            for idx, ref_span in enumerate(reference_spans):
                try:
                    # ---- Reference ----
                    original_reference = ref_span.get_text(strip=True)
                    if not original_reference:
                        continue

                    # ---- Buyer (cleaned) ----
                    buyer_text = "N/A"
                    if idx < len(buyer_divs):
                        raw = buyer_divs[idx].get_text(strip=True)
                        buyer_text = re.sub(r'(?i)^Acheteur\s+public\s*[:\s]*', '', raw).strip()
                        if "Acheteur public" in buyer_text:
                            buyer_text = buyer_text.replace("Acheteur public", "").replace(":", "").strip()
                        buyer_text = " ".join(buyer_text.split())

                    # ---- Category & launch_date (from category div + sibling) ----
                    category_text = "N/A"
                    launch_date_text = "N/A"
                    if idx < len(category_divs):
                        category_text = category_divs[idx].get_text(strip=True)
                        sib = category_divs[idx].find_next_sibling()
                        if sib:
                            launch_date_text = sib.get_text(strip=True)

                    # ---- Composite reference for Jena matching ----
                    buyer_initials = self.generate_initials(buyer_text)
                    composite_reference = f"{original_reference}_{buyer_initials}"

                    # Deduplicate
                    if composite_reference in seen_composite_refs:
                        logger.warning(f"Duplicate skipped: {composite_reference}")
                        continue
                    seen_composite_refs.add(composite_reference)

                    references_data.append({
                        # Validation tuple
                        'reference': composite_reference,
                        'original_reference': original_reference,
                        'buyer': buyer_text,
                        'buyer_initials': buyer_initials,
                        # Lightweight context (not detail-page metadata)
                        'category': category_text,
                        'launch_date': launch_date_text,
                        'scraped_at': datetime.now().isoformat(),
                    })

                    if idx < 3:
                        logger.info(f"  Tuple: {composite_reference!r} // buyer={buyer_text!r}")

                except Exception as e:
                    logger.warning(f"Error at row {idx}: {e}")
                    continue

            logger.info(f"Parsed {len(references_data)} validation tuples")
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
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
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
        """
        Compare website references with Jena references using tuples.
        Compares (original_reference, buyer) from website with (tender_reference, buyer_name) from Jena.
        
        Note: Jena stores composite reference (original_ref + buyer_initials), 
        while website data has original_reference and buyer separately.
        """
        logger.info("Comparing references...")
        
        new_refs = []
        
        for ref_data in website_refs:
            # Create tuple from website data: (original_reference, buyer)
            # We need to match against Jena's format
            original_ref = ref_data['original_reference']
            buyer = ref_data['buyer']
            buyer_initials = ref_data['buyer_initials']
            
            # Jena stores composite reference: original_reference_buyer_initials
            jena_composite = f"{original_ref}_{buyer_initials}"
            
            # Also check with raw buyer name for more flexible matching
            # Create tuple format (composite_ref, buyer_name)
            website_tuple = (jena_composite, buyer)
            
            # Check if this tender exists in Jena
            # We need to check if any Jena tuple matches this tender
            found = False
            for jena_tender, jena_buyer in self.jena_references:
                # Check if tender reference matches (composite or original)
                if jena_tender == jena_composite or jena_tender == original_ref:
                    found = True
                    break
            
            if not found:
                new_refs.append(ref_data)
                logger.info(f"New reference found: {jena_composite}")
        
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
                'total_jena_references': len(self.jena_references),
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
        
        # Step 1: Fetch references from Apache Jena
        self.jena_references = self.fetch_jena_references()
        
        # Step 2: Fetch website references
        website_refs_data = await self.fetch_website_references(max_pages=max_pages)
        
        # Create set of tuples for comparison: (composite_reference, buyer)
        self.website_references = {
            (ref['reference'], ref['buyer']) for ref in website_refs_data
        }
        
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
        logger.info(f"Jena References: {len(self.jena_references)}")
        logger.info(f"Website References: {len(self.website_references)}")
        logger.info(f"New References: {len(self.new_references)}")
        logger.info(f"Output File: {self.output_file}")
        logger.info("=" * 80)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Compare Jena database references with website and find new tenders'
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
        '--jena-endpoint',
        help='Jena SPARQL endpoint (defaults to env var JENA_ENDPOINT)'
    )
    parser.add_argument(
        '--jena-update-endpoint',
        help='Jena SPARQL update endpoint (defaults to env var JENA_UPDATE_ENDPOINT)'
    )
    
    args = parser.parse_args()
    
    # Create and run updater
    updater = ReferenceUpdater(
        category=args.category,
        output_file=args.output,
        jena_endpoint=args.jena_endpoint,
        jena_update_endpoint=args.jena_update_endpoint
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
