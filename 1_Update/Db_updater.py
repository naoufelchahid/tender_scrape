#!/usr/bin/env python3
"""
Tender Downloader and S3 Uploader Script
Reads new_references.json, extracts full metadata, downloads ALL available files,
uploads docs to S3 (tender_doc_final/), saves per-tender JSON to tenders_metadata/,
and outputs processed_tenders.json for kg_builder.py.

Pipeline steps handled here:
  5. Extract ALL metadata (18 taxonomy fields) BEFORE download
  6. Detect and download ALL files in #panelPieces (not just first)
  7. Skip to next tender if download=False (no files available)
  8. Save metadata JSON to tenders_metadata/{ref}.json; upload docs to S3 tender_doc_final/
"""
import asyncio
import random
import logging
import json
import os
import boto3
import unicodedata
import zipfile
import shutil
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import Page
from playwright_stealth import Stealth
from browser_config import create_browser
from bs4 import BeautifulSoup

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


def sanitize_for_s3(text: str) -> str:
    """Sanitize text for S3-compatible filenames and folder names"""
    if not text:
        return ""
    
    # Normalize unicode
    nfkd_form = unicodedata.normalize('NFKD', text)
    without_accents = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    
    # Replace spaces and special chars with underscores
    # Allow: alphanumeric, dash, underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', without_accents)
    
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    
    return sanitized


class TenderDownloader:
    """Downloads tender files and uploads to S3 with metadata"""
    
    def __init__(
        self,
        input_file: str = 'new_references.json',
        output_file: str = 'processed_tenders.json',
        downloads_dir: str = 'downloads',
        metadata_dir: str = 'tenders_metadata'
    ):
        """
        Initialize TenderDownloader
        
        Args:
            input_file: Path to new_references.json file
            output_file: Path to output JSON with processed tenders
            downloads_dir: Directory to save downloaded ZIP files
            metadata_dir: Directory to save per-tender JSON metadata files
        """
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)
        self.metadata_dir = Path(metadata_dir)
        self.metadata_dir.mkdir(exist_ok=True)
        
        # AWS Configuration
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

        # S3 prefix for tender document uploads
        self.s3_doc_prefix = 'tender_doc_final'

        # Storage for processed tenders (successful downloads with metadata)
        self.processed_tenders: List[Dict] = []
        
        # Statistics
        self.stats = {
            'total_references': 0,
            'files_downloaded': 0,
            'files_failed': 0,
            'skipped_no_download': 0,
            's3_uploaded': 0,
            's3_failed': 0
        }
        
        logger.info(f"TenderDownloader initialized")
        logger.info(f"Input file: {self.input_file}")
        logger.info(f"Output file: {self.output_file}")
        logger.info(f"Downloads directory: {self.downloads_dir}")
        logger.info(f"Metadata directory: {self.metadata_dir}")
    
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
    
    async def _open_infos_panel(self, page: Page) -> None:
        """
        Click the 'infosPrincipales' toggle link so the div becomes visible.
        The toggle button is: <a class="title-toggle" onclick="togglePanel(this,'infosPrincipales');">
        The panel is initially display:none; after click it becomes display:block.
        """
        try:
            # Wait for the toggle link
            toggle = await page.query_selector("a.title-toggle[onclick*='infosPrincipales']")
            if not toggle:
                logger.warning("Toggle link for infosPrincipales not found")
                return
            # Check if panel is already open
            panel = await page.query_selector("div#infosPrincipales")
            if panel:
                style = await panel.get_attribute("style")
                if style and "display: none" not in style and "display:none" not in style:
                    logger.info("infosPrincipales panel already visible")
                    return
            await toggle.click()
            # Wait for panel to become visible
            await page.wait_for_selector("div#infosPrincipales", state="visible", timeout=10000)
            logger.info("✅ infosPrincipales panel opened")
        except Exception as e:
            logger.warning(f"Could not open infosPrincipales panel: {e}")

    async def extract_all_metadata(self, page: Page) -> Dict:
        """
        Step 5 — Extract ALL 18 taxonomy fields from the tender detail page
        BEFORE any download.

        Strategy: parse raw HTML with BeautifulSoup, using exact IDs provided
        in the target scheme. Every taxonomy field MUST appear in the returned dict;
        absent values are `None` (never omitted).

        Sections covered:
          1. Core       – reference, object, buyer, city, deadline
          2. Procedure  – consultation_type, mode_passation, main_category,
                          allotissement, activity_domains, is_sme_reserved
          3. Submission – retrait_address, depot_address, mode_soumission,
                          opening_location, contacts
          4. Financials – estimated_value, plan_cost, provisional_deposit
        """
        logger.info("── Step 5: Extracting all metadata fields (BeautifulSoup ID-based) ──")

        # ── Helpers ──────────────────────────────────────────────────────────
        def _clean_val(tag) -> Optional[str]:
            """Return stripped innerText of a BS4 tag, or None if blank."""
            if tag is None:
                return None
            txt = tag.get_text(separator=' ', strip=True)
            txt = ' '.join(txt.split())        # collapse internal whitespace
            return txt if txt and txt != '-' else None

        def _parse_list(tag) -> Optional[List[str]]:
            """Parse ul/li list into an array of strings."""
            if tag is None:
                return None
            items = [li.get_text(strip=True) for li in tag.find_all('li') if li.get_text(strip=True)]
            return items if items else None

        def _clean_money(raw: Optional[str]) -> Optional[str]:
            """Strip currency labels; return None for zero/blank values."""
            if not raw:
                return None
            cleaned = re.sub(r'[^\d.,\s]', '', raw).strip()
            # Treat '0.00', '0,00', '0' as None
            if not cleaned or re.match(r'^0[.,]?0*$', cleaned.replace(' ', '')):
                return None
            return cleaned

        # ── Parse page HTML ──────────────────────────────────────────────────
        try:
            html_content = await page.content()
        except Exception as e:
            logger.error(f"Failed to get page content: {e}")
            return self._null_metadata()

        soup = BeautifulSoup(html_content, 'html.parser')

        # Map IDs to fields
        ids = {
            'deadline': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_dateHeureLimiteRemisePlis',
            'reference': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_reference',
            'buyer': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_entiteAchat',
            'objet': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_objet',
            'category': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_categoriePrincipale',
            'city': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_lieuxExecutions',
            'estimation': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_idReferentielZoneText_RepeaterReferentielZoneText_ctl0_labelReferentielZoneText',
            'mode_passation': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_modePassation',
            'procedure_type': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_typeProcedure',
            'allotissement': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_nbrLots',
            'activity_domains': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_domainesActivite',
            'retrait_address': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_adresseRetraitDossiers',
            'depot_address': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_adresseDepotOffres',
            'opening_location': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_lieuOuverturePlis',
            'mode_soumission_img': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_pictCertificat',
            'plan_cost': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_prixAcquisitionPlan',
            'caution': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_cautionProvisoire',
            'qualifications': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_qualification',
            'agrements': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_agrements',
            'contact_name': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_contactAdministratif',
            'email': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_email',
            'telephone': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_telephone',
            'telecopieur': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_telecopieur',
            'variante': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_varianteValeur',
            'reunion': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_dateReunion',
            'site_visit': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_panelPasVisitelieu',
            'samples': 'ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_dateEchantillons'
        }

        # ── Extract values by ID ─────────────────────────────────────────────
        extracted = {k: soup.find(id=v) for k, v in ids.items()}

        # ── Core Metadata ────────────────────────────────────────────────────
        reference_raw = _clean_val(extracted['reference'])
        object_raw    = _clean_val(extracted['objet'])
        buyer_raw     = _clean_val(extracted['buyer'])
        category_raw  = _clean_val(extracted['category'])
        city_raw      = _clean_val(extracted['city'])
        deadline_raw  = _clean_val(extracted['deadline'])

        # ── Section 2 – Procedure & Requirements ─────────────────────────────
        mode_passation_raw = _clean_val(extracted['mode_passation'])
        procedure_type_raw = _clean_val(extracted['procedure_type'])
        allotissement_raw  = _clean_val(extracted['allotissement'])
        
        # Activity Domains (List)
        activity_domains = _parse_list(extracted['activity_domains'])
        
        # sme classification - extract from domains or dedicated text
        is_sme_raw = soup.find(string=re.compile(r'réservé', re.I))
        is_sme_reserved = None
        if is_sme_raw:
            is_sme_reserved = 'oui' in is_sme_raw.parent.get_text().lower()

        # ── Section 3 – Submission & Logistics ───────────────────────────────
        retrait_address  = _clean_val(extracted['retrait_address'])
        depot_address    = _clean_val(extracted['depot_address'])
        opening_location = _clean_val(extracted['opening_location'])
        
        # Mode soumission (from image)
        mode_soumission = None
        if extracted['mode_soumission_img']:
            src = extracted['mode_soumission_img'].get('src', '').lower()
            if 'non' in src:
                mode_soumission = 'Electronique'
            else:
                mode_soumission = 'Physique/Hybride' # Adjusted logic: usually non-elec means paper

        # Contacts
        contacts = {
            'name': _clean_val(extracted['contact_name']),
            'email': _clean_val(extracted['email']),
            'phone': _clean_val(extracted['telephone']),
            'fax': _clean_val(extracted['telecopieur'])
        }

        # ── Section 4 – Financials ───────────────────────────────────────────
        estimated_value     = _clean_money(_clean_val(extracted['estimation']))
        plan_cost           = _clean_money(_clean_val(extracted['plan_cost']))
        provisional_deposit = _clean_money(_clean_val(extracted['caution']))

        # ── Additional Fields ────────────────────────────────────────────────
        qualifications = _parse_list(extracted['qualifications'])
        agrements      = _parse_list(extracted['agrements'])
        variante       = _clean_val(extracted['variante'])
        reunion        = _clean_val(extracted['reunion'])
        site_visit     = _clean_val(extracted['site_visit'])
        samples        = _clean_val(extracted['samples'])

        # ── Post-processing ──────────────────────────────────────────────────
        
        # object: strip leading "Objet :"
        object_clean = None
        if object_raw:
            object_clean = re.sub(r'^[Oo]bjet\s*:+\s*', '', object_raw).strip(': ')
            object_clean = ' '.join(object_clean.split()) or None

        # city: split and cleanup
        city_clean = None
        all_cities = None
        if city_raw:
            parts = [c.strip() for c in re.split(r'[,/\n]+', city_raw) if c.strip()]
            seen: list = []
            for p in parts:
                if p not in seen:
                    seen.append(p)
            city_clean = seen[0] if seen else city_raw
            all_cities = seen if len(seen) > 1 else None

        # deadline: ISO format
        deadline_iso = None
        if deadline_raw:
            parsed_dt = self.parse_date(deadline_raw)
            deadline_iso = parsed_dt.isoformat() if parsed_dt else deadline_raw

        # ── Build structured output ──────────────────────────────────────────
        metadata: Dict = {
            # Section 1 – Core
            'reference':     reference_raw,
            'object':        object_clean,
            'buyer':         buyer_raw,
            'city':          city_clean,
            'all_cities':    all_cities,
            'deadline':      deadline_iso,
            # Section 2 – Procedure
            'mode_passation':   mode_passation_raw,
            'procedure_type':   procedure_type_raw,
            'main_category':    category_raw,
            'allotissement':    allotissement_raw,
            'activity_domains': activity_domains,
            'is_sme_reserved':  is_sme_reserved,
            # Section 3 – Submission
            'retrait_address':  retrait_address,
            'depot_address':    depot_address,
            'mode_soumission':  mode_soumission,
            'opening_location': opening_location,
            'contacts':         contacts,
            # Section 4 – Financials
            'estimated_value':     estimated_value,
            'plan_cost':           plan_cost,
            'provisional_deposit': provisional_deposit,
            # Section 5 - Details
            'qualifications': qualifications,
            'agrements':      agrements,
            'variante':       variante,
            'reunion':        reunion,
            'site_visit':     site_visit,
            'samples_info':   samples
        }

        populated = sum(1 for v in metadata.values() if v is not None)
        logger.info(f"✅ Extracted {populated}/{len(metadata)} metadata fields")
        return metadata

    def _null_metadata(self) -> Dict:
        """Return a fully null metadata dict matching the expanded taxonomy schema."""
        return {
            'reference': None, 'object': None, 'buyer': None, 'city': None, 'all_cities': None, 'deadline': None,
            'mode_passation': None, 'procedure_type': None, 'main_category': None, 'allotissement': None,
            'activity_domains': None, 'is_sme_reserved': None, 'retrait_address': None, 'depot_address': None,
            'mode_soumission': None, 'opening_location': None, 'contacts': None, 'estimated_value': None,
            'plan_cost': None, 'provisional_deposit': None, 'qualifications': None, 'agrements': None,
            'variante': None, 'reunion': None, 'site_visit': None, 'samples_info': None
        }

    async def extract_lot_metadata(self, lot_text: str) -> List[Dict]:
        """
        Extract detailed metadata for each lot by splitting the popup content
        using <!--Debut Lot X--> delimiters.
        """
        logger.info("── Extracting detailed lot metadata ──")
        lots_data = []
        
        # Split by <!--Debut Lot X-->
        lot_blocks = re.split(r'<!--Debut Lot \d+-->', lot_text)
        lot_blocks = [b for b in lot_blocks if b.strip()]
        
        for i, block in enumerate(lot_blocks, 1):
            soup = BeautifulSoup(block, 'html.parser')
            
            def _get_txt(selector, is_id=True):
                if is_id:
                    tag = soup.find(id=re.compile(selector))
                else:
                    tag = soup.select_one(selector)
                
                if tag:
                    txt = tag.get_text(separator=' ', strip=True)
                    return txt if txt and txt != '-' else None
                return None

            def _clean_money(raw: Optional[str]) -> Optional[str]:
                if not raw: return None
                cleaned = re.sub(r'[^\d.,\s]', '', raw).strip()
                if not cleaned or re.match(r'^0[.,]?0*$', cleaned.replace(' ', '')):
                    return None
                return cleaned

            # Extract lot number from title span (e.g. "Lot 1 :")
            title_tag = soup.select_one('div.intitule-150 span.blue.bold')
            if not title_tag:
                continue

            title_txt = title_tag.get_text(strip=True)
            match = re.search(r'Lot\s*(\d+)', title_txt, re.I)
            lot_num_val = int(match.group(1)) if match else i

            # Composite field for prospectus and samples
            ps_parts = []
            ps_label = _get_txt(r'labelDateHeureLimiteEchantillon')
            ps_date = _get_txt(r'dateEchantillons')
            ps_addr = _get_txt(r'adresseEchantillons')
            if ps_label: ps_parts.append(ps_label)
            if ps_date: ps_parts.append(ps_date)
            if ps_addr: ps_parts.append(ps_addr)
            prospectus_info = " | ".join(ps_parts) if ps_parts else None

            # Map fields according to user request (replacing X with lot number)
            lot_info = {
                "lot number": lot_num_val,
                f"lot{lot_num_val}_object": _get_txt('div.d-flex', is_id=False),
                f"Lot{lot_num_val}_estimation": _clean_money(_get_txt(r'labelReferentielZoneText')),
                f"Lot{lot_num_val}_caution":    _clean_money(_get_txt(r'cautionProvisoire')),
                f"Lot{lot_num_val}_qualification": _get_txt(r'qualification'),
                f"Lot{lot_num_val}_agreement":    _get_txt(r'qualification'), # User requested same for agreement
                "Procpectus_et_echantillons": prospectus_info,
                "Reunion":        _get_txt(r'dateReunion'),
                "visite_des_lieux": _get_txt(r'panelPasVisitelieu'),
                "variante":       _get_txt(r'varianteValeur'),
                "Env_consideration": _get_txt(r'consEnvValeur'),
                "Reserve_TPE_PME":   _get_txt(r'labelReferentielRadio')
            }
            
            # Fallback for object if div.d-flex misses it
            if not lot_info[f"lot{lot_num_val}_object"]:
                lot_info[f"lot{lot_num_val}_object"] = _get_txt(r'labelIntitule')

            lots_data.append(lot_info)
            logger.info(f"  Processed Lot {lot_num_val}")

        return lots_data

    async def detect_downloadable_files(self, page: Page) -> List[Dict]:
        """
        Step 6: Detect ALL downloadable file links in div#ctl0_CONTENU_PAGE_panelPieces.

        Scans every <li style=\"display:block\"> inside the panel and returns a list of:
            [{'label': 'Dossier de consultation', 'link_id': '...linkDownloadDce', 'href': '...'}]

        Returns empty list when no files are available (step 7: skip trigger).
        """
        files: List[Dict] = []
        try:
            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            panel = soup.find('div', id=re.compile(r'panelPieces'))
            if not panel:
                logger.info("No #panelPieces panel found — no downloadable files")
                return files

            for li in panel.find_all('li', class_='picto-link'):
                # Only consider visible items
                style = li.get('style', '')
                if 'display:none' in style.replace(' ', '').lower() or \
                   'display: none' in style.lower():
                    continue

                link = li.find('a', href=True)
                if not link:
                    continue

                label = link.get_text(strip=True) or \
                        li.find('img', alt=True).get('alt', 'document') if li.find('img') else 'document'
                link_id = link.get('id', '')
                href = link.get('href', '')

                files.append({
                    'label': label,
                    'link_id': link_id,
                    'href': href
                })
                logger.info(f"  Found downloadable: [{link_id}] {label}")

        except Exception as e:
            logger.error(f"Error detecting downloadable files: {e}")

        logger.info(f"Detected {len(files)} downloadable file(s)")
        return files

    async def search_by_reference_and_buyer(
        self, 
        page: Page, 
        original_reference: str,
        buyer_name: str
    ) -> bool:
        """
        Search for tender by original reference AND buyer name
        
        Args:
            page: Playwright page object
            original_reference: Reference without initials (e.g., "11/2025")
            buyer_name: Buyer organization name
            
        Returns:
            bool: True if found and navigated to tender detail page
        """
        logger.info(f"Searching for reference: {original_reference}")
        logger.info(f"Buyer name: {buyer_name}")
        
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
            
            # Fill buyer name input (orgName)
            buyer_input = await page.query_selector('input#ctl0_CONTENU_PAGE_AdvancedSearch_orgName')
            if not buyer_input:
                logger.error("Buyer name input field not found")
                return False
            
            await buyer_input.fill(buyer_name)
            logger.info(f"Filled buyer name: {buyer_name}")
            await human_delay(1, 2)
            
            # Scroll to search button
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await human_delay(0.5, 1)
            
            # Click search button
            await page.click('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
            logger.info("Clicked search button")
            
            # Wait for page load
            await page.wait_for_load_state('load', timeout=30000)
            await human_delay(3, 5)
            
            # Check if tender was found
            tender_links = await page.query_selector_all('a[href*="EntrepriseDetailConsultation"]')
            if not tender_links:
                logger.warning(f"No tender found for reference: {original_reference} and buyer: {buyer_name}")
                return False
            
            logger.info(f"Found {len(tender_links)} tender(s), navigating to first result")
            
            # Navigate to first tender (should be unique with ref + buyer)
            await tender_links[0].click()
            await page.wait_for_load_state('load', timeout=30000)
            await human_delay(2, 3)
            
            logger.info("✅ Successfully navigated to tender detail page")
            return True
            
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
            
            await page.wait_for_load_state('load', timeout=30000)
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
                    await page.wait_for_load_state('load', timeout=30000)
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
                safe_ref = sanitize_for_s3(composite_reference)
                filename = f"{safe_ref}.zip"
                filepath = self.downloads_dir / filename
                
                async with page.expect_download(timeout=120000) as download_info:
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
    
    def unzip_and_prepare_folder(self, zip_path: str, composite_reference: str) -> Optional[Path]:
        """
        Unzip file and rename folder with S3-safe composite reference
        
        Args:
            zip_path: Path to downloaded ZIP file
            composite_reference: Composite reference for folder name
            
        Returns:
            Path to prepared folder, or None if failed
        """
        try:
            logger.info(f"Unzipping {zip_path}...")
            
            zip_path_obj = Path(zip_path)
            
            # Create temp extraction directory
            temp_extract_dir = self.downloads_dir / f"temp_extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            temp_extract_dir.mkdir(exist_ok=True)
            
            # Unzip
            with zipfile.ZipFile(zip_path_obj, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
            
            logger.info(f"Extracted to {temp_extract_dir}")
            
            # Find the root folder in extracted content
            extracted_items = list(temp_extract_dir.iterdir())
            
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                # Single folder inside
                extracted_folder = extracted_items[0]
            else:
                # Multiple items or files directly in zip
                extracted_folder = temp_extract_dir
            
            # Rename folder with S3-safe composite reference
            safe_ref = sanitize_for_s3(composite_reference)
            target_folder = self.downloads_dir / safe_ref
            
            # Remove target if exists
            if target_folder.exists():
                shutil.rmtree(target_folder)
            
            # Move/rename
            shutil.move(str(extracted_folder), str(target_folder))
            
            # Cleanup temp directory if different
            if temp_extract_dir.exists() and temp_extract_dir != extracted_folder:
                shutil.rmtree(temp_extract_dir)
            
            # Delete original ZIP
            zip_path_obj.unlink()
            
            logger.info(f"✅ Prepared folder: {target_folder}")
            return target_folder
            
        except Exception as e:
            logger.error(f"Error unzipping and preparing folder: {e}")
            return None
    
    def _sanitize_metadata(self, metadata: Dict) -> Dict:
        """Ensure metadata values are ASCII-safe for S3"""
        sanitized = {}
        if not metadata:
            return sanitized
            
        for k, v in metadata.items():
            if v:
                try:
                    # Try to encode as is first
                    str(v).encode('ascii')
                    sanitized[k] = str(v)
                except UnicodeEncodeError:
                    # Normalize unicode characters
                    nfkd_form = unicodedata.normalize('NFKD', str(v))
                    # Remove accents (combining characters)
                    without_accents = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
                    # Force ASCII encoding, ignoring any remaining non-ASCII chars
                    ascii_val = without_accents.encode('ascii', 'ignore').decode('ascii')
                    sanitized[k] = ascii_val
        return sanitized

    def upload_folder_to_s3(self, folder_path: Path, tender_metadata: Dict) -> bool:
        """
        Step 8b: Upload ALL files in folder to S3 under tender_doc_final/{ref}/

        Args:
            folder_path: Path to folder containing downloaded tender docs
            tender_metadata: Full metadata dict to attach as S3 object metadata

        Returns:
            bool: True if at least one file was uploaded successfully
        """
        if not self.s3_bucket:
            logger.error("Cannot upload: S3_BUCKET_NAME not set")
            return False

        try:
            folder_name = folder_path.name
            logger.info(f"Uploading folder '{folder_name}' to s3://{self.s3_bucket}/{self.s3_doc_prefix}/")

            # Sanitize metadata for S3 object tagging (ASCII only)
            s3_metadata = self._sanitize_metadata({
                'tender_reference': tender_metadata.get('reference', ''),
                'buyer': tender_metadata.get('buyer', ''),
                'category': tender_metadata.get('category', ''),
                'deadline': tender_metadata.get('deadline', ''),
                'uploaded_at': datetime.now().isoformat()
            })

            uploaded_count = 0
            for file_path in folder_path.rglob('*'):
                if file_path.is_file():
                    relative_path = file_path.relative_to(folder_path)
                    # Step 8b: use tender_doc_final/ prefix
                    s3_key = f"{self.s3_doc_prefix}/{folder_name}/{relative_path}"

                    self.s3_client.upload_file(
                        str(file_path),
                        self.s3_bucket,
                        s3_key,
                        ExtraArgs={'Metadata': s3_metadata}
                    )
                    uploaded_count += 1

            if uploaded_count == 0:
                logger.warning("No files found to upload in folder")
                return False

            logger.info(f"✅ Uploaded {uploaded_count} file(s) to s3://{self.s3_bucket}/{self.s3_doc_prefix}/{folder_name}/")

            # Cleanup local folder after successful upload
            shutil.rmtree(folder_path)
            logger.info(f"Cleaned up local folder: {folder_path}")

            return True

        except Exception as e:
            logger.error(f"Error uploading folder to S3: {e}")
            return False
    
    def save_metadata_json(self, composite_reference: str, metadata: Dict) -> bool:
        """
        Step 8a: Save per-tender metadata JSON to tenders_metadata/{ref}.json.

        The filename is the S3-safe composite reference so kg_builder.py can
        glob the directory independently.

        Args:
            composite_reference: e.g. '003_2026_SRMCS_SOCREGMULCASSETSA'
            metadata: Full metadata dict (taxonomy fields + lots)

        Returns:
            bool: True if file written successfully
        """
        try:
            safe_ref = sanitize_for_s3(composite_reference)
            output_path = self.metadata_dir / f"{safe_ref}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Saved metadata JSON: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving metadata JSON for {composite_reference}: {e}")
            return False

    def save_processed_tenders(self):
        """Save all processed tenders list to output JSON file"""
        try:
            output_data = {
                'processed_date': datetime.now().isoformat(),
                'total_processed': len(self.processed_tenders),
                'tenders': self.processed_tenders
            }
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Saved {len(self.processed_tenders)} processed tenders to {self.output_file}")
        except Exception as e:
            logger.error(f"Error saving processed tenders: {e}")
    
    async def process_tender(self, page: Page, tender_data: Dict) -> bool:
        """
        Strict 8-step orchestration for a single tender.

        ┌─────────────────────────────────────────────────────────────┐
        │ Step 1  Navigate to tender detail page                       │
        │ Step 2  Click #infosPrincipales toggle (panel is hidden)     │
        │ Step 3  Extract ALL metadata from infosPrincipales           │
        │ Step 4  Check for lot details link → if found: navigate,     │
        │          extract lot metadata, return to detail page          │
        │ Step 5  Navigate back to detail page (if lot nav happened)   │
        │ Step 6  Detect downloadable files in #panelPieces            │
        │ Step 7  SKIP (no JSON) if no downloadable files              │
        │ Step 8  Download each file; SKIP (no JSON) if all fail       │
        │         Upload folder to S3                                   │
        │         Write tenders_metadata/{ref}.json ONLY on success    │
        └─────────────────────────────────────────────────────────────┘
        """
        composite_reference = tender_data['reference']
        original_reference = tender_data['original_reference']
        buyer_name = tender_data.get('buyer', '')

        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {composite_reference}")
        logger.info(f"Original ref: {original_reference}")
        logger.info(f"Buyer: {buyer_name}")
        logger.info(f"{'='*80}")

    async def search_by_reference_and_buyer(
        self, 
        page: Page, 
        original_reference: str,
        buyer_name: str
    ) -> bool:
        """
        Search for tender and navigate to the consultation access (DOWNLOAD) page.
        """
        logger.info(f"Searching for reference: {original_reference}")
        
        try:
            await page.goto(
                'http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                wait_until='domcontentloaded',
                timeout=60000
            )
            await human_delay(1, 2)

            # Fill reference
            ref_input = await page.query_selector('input#ctl0_CONTENU_PAGE_AdvancedSearch_reference')
            if not ref_input:
                logger.error("Reference input field not found")
                return False
            await ref_input.fill(original_reference)

            # Search - Updated ID
            search_btn = await page.query_selector('input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche')
            if not search_btn:
                logger.error("Search button (#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche) not found")
                # Fallback to any submit button in search area
                search_btn = await page.query_selector('input[type="submit"][id*="Search"]')
                if not search_btn: return False

            await search_btn.click()
            await page.wait_for_load_state('load', timeout=30000)
            await human_delay(2, 3)
            
            # Find result and click download icon (Step 3 user request: picto-acces-consultation.gif)
            # Selector from browser subagent: a[href*="EntrepriseDetailConsultation"]
            download_icon = await page.query_selector('a[href*="EntrepriseDetailConsultation"]')
            if not download_icon:
                logger.error("Download (consultation access) link not found in results")
                return False

            await download_icon.click()
            await page.wait_for_load_state('load', timeout=30000)
            logger.info("✅ Navigated to consultation download page")
            return True
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return False

    async def process_tender(self, page: Page, tender_data: Dict) -> bool:
        """
        Refactored orchestration for a single tender on the download page.
        """
        composite_reference = tender_data['reference']
        original_reference = tender_data['original_reference']
        buyer_name = tender_data.get('buyer', '')

        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {composite_reference}")
        logger.info(f"{'='*80}")

        try:
            # ── Step 1: Reach download page ──────────────────────
            if not await self.search_by_reference_and_buyer(page, original_reference, buyer_name):
                self.stats['files_failed'] += 1
                return False

            detail_url = page.url

            # ── Step 2: Open metadata panel ───────────────────
            await self._open_infos_panel(page)

            # ── Step 3: Extract authorize metadata ───────────────
            page_metadata = await self.extract_all_metadata(page)
            
            # Build full metadata
            full_metadata: Dict = {
                'reference': composite_reference,
                'original_reference': original_reference,
                'buyer': buyer_name,
                'category': tender_data.get('category', ''),
                'launch_date': tender_data.get('launch_date', ''),
                **page_metadata
            }

            # ── Step 4: Lot details (popup) ────────────────────────────────
            lots_navigated = False
            lots_link = await page.query_selector('a#ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_linkDetailLots')

            if lots_link:
                is_visible = await lots_link.is_visible()
                href = await lots_link.get_attribute('href') or ""

                if is_visible and 'PopUpDetailLots' in href:
                    logger.info("Opening lots popup...")
                    # Retry logic with page refresh for frozen pages
                    for attempt in range(1, 3):
                        try:
                            async with page.expect_popup(timeout=60000) as popup_info:
                                await lots_link.click(force=True)
                            popup = await popup_info.value
                            # Use 'load' instead of 'networkidle' + shorter timeout to avoid hanging
                            await popup.wait_for_load_state('load', timeout=30000)

                            popup_html = await popup.content()
                            lots_data = await self.extract_lot_metadata(popup_html)
                            full_metadata['lots'] = lots_data

                            await popup.close()
                            lots_navigated = True
                            logger.info(f"✅ Successfully extracted metadata for {len(lots_data)} lots")
                            break  # Success, exit retry loop
                        except Exception as lot_err:
                            await popup.close() if 'popup' in locals() else None
                            if attempt < 2:
                                logger.warning(f"Attempt {attempt} failed: {lot_err}. Refreshing page and retrying...")
                                await page.reload(wait_until='domcontentloaded')
                                await human_delay(2, 3)
                                # Re-query the lots link after page refresh
                                lots_link = await page.query_selector('a#ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_linkDetailLots')
                            else:
                                logger.error(f"Failed to extract lots after {attempt} attempts: {lot_err}")
                else:
                    logger.info("Lots link present but not active/visible for detail view")
            else:
                logger.info("No lots link element (#ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_linkDetailLots) found")

            # ── Step 5: Save AUTHORITATIVE metadata to JSON immediately ──
            self.save_metadata_json(composite_reference, full_metadata)

            # ── Step 6: Return to detail page if lot popup was visited ───────
            if lots_navigated:
                if page.url != detail_url:
                    await page.goto(detail_url, wait_until='domcontentloaded')
                    await human_delay(2, 3)

            # ── Step 7: Detect ALL downloadable files ───────────────────────
            downloadable_files = await self.detect_downloadable_files(page)

            # ── Step 8: SKIP (no S3 upload) if no downloadable files ────────
            if not downloadable_files:
                logger.warning(f"⏭  No downloadable files — skipping {composite_reference} (no S3/Ingestion)")
                self.stats['skipped_no_download'] += 1
                return False

            full_metadata['download_available'] = True
            full_metadata['downloadable_files'] = [f['label'] for f in downloadable_files]

            # ── Step 9: Download EACH visible file ───────────────────────────
            safe_ref = sanitize_for_s3(composite_reference)
            tender_folder = self.downloads_dir / safe_ref
            tender_folder.mkdir(parents=True, exist_ok=True)

            any_downloaded = False
            for file_info in downloadable_files:
                link_id = file_info.get('link_id', '')
                label = file_info.get('label', 'document')
                label_safe = re.sub(r'[^\w]+', '_', label)[:40]

                try:
                    # Locate the download link in the live DOM
                    if link_id:
                        dl_link = await page.query_selector(f'a#{link_id}')
                    else:
                        href = file_info.get('href', '')
                        dl_link = await page.query_selector(f'a[href="{href}"]')

                    if not dl_link:
                        logger.warning(f"Link not found in DOM: {link_id!r}")
                        continue

                    await human_scroll(page)
                    await dl_link.click()
                    await page.wait_for_load_state('load', timeout=30000)
                    await human_delay(2, 3)

                    # Fill identity form if download requires it
                    needs_form = await page.query_selector(
                        'input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions'
                    )
                    if needs_form:
                        for attempt in range(3):
                            identity = await generate_moroccan_identity()
                            checkbox = await page.query_selector(
                                'input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions'
                            )
                            if checkbox and not await checkbox.is_checked():
                                await checkbox.check()
                            nom_input = await page.query_selector(
                                'input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_nom'
                            )
                            if nom_input:
                                await nom_input.fill(identity['family_name'])
                            prenom_input = await page.query_selector(
                                'input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_prenom'
                            )
                            if prenom_input:
                                await prenom_input.fill(identity['first_name'])
                            email_input = await page.query_selector(
                                'input#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_email'
                            )
                            if email_input:
                                await email_input.fill(identity['email'])
                            valider = await page.query_selector(
                                'input[type="submit"][value="Valider"], input[name*="valider"]'
                            )
                            if valider:
                                await valider.click()
                                await page.wait_for_load_state('load', timeout=30000)
                                await human_delay(3, 5)
                            err = await page.query_selector('div#divValidationSummary')
                            if err and await err.is_visible():
                                continue
                            break

                    # Trigger the actual file download
                    download_btn = await page.query_selector(
                        'a#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload'
                    ) or await page.query_selector('a.bouton-telecharger-long230')

                    if download_btn:
                        filename = f"{label_safe}.zip"
                        filepath = tender_folder / filename
                        async with page.expect_download(timeout=120000) as dl_info:
                            await download_btn.click(force=True)
                        download = await dl_info.value
                        try:
                            await asyncio.wait_for(download.save_as(str(filepath)), timeout=180)
                            logger.info(f"✅ Downloaded [{label}]: {filepath}")
                            with zipfile.ZipFile(str(filepath), 'r') as zf:
                                zf.extractall(tender_folder)
                            filepath.unlink()   # remove zip; keep extracted files
                            any_downloaded = True
                            self.stats['files_downloaded'] += 1
                        except asyncio.TimeoutError:
                            logger.error(f"❌ Download timed out for [{label}]")
                    else:
                        logger.warning(f"No download button found after form for [{label}]")

                    # Return to detail page for the next file
                    await page.goto(detail_url, wait_until='domcontentloaded')
                    await human_delay(2, 3)

                except Exception as file_err:
                    logger.error(f"Error downloading [{label}]: {file_err}")
                    try:
                        await page.goto(detail_url, wait_until='domcontentloaded')
                        await human_delay(2, 3)
                    except Exception:
                        pass

            # ── S3 upload ────────────────────────────────────────────────────
            if any_downloaded:
                s3_folder = f"{self.s3_doc_prefix}/{safe_ref}/"
                success = self.upload_folder_to_s3(tender_folder, full_metadata)
                if success:
                    self.stats['s3_uploaded'] += 1
                    full_metadata['s3_folder'] = s3_folder
                else:
                    self.stats['s3_failed'] += 1
            
            # Final save and append
            full_metadata['processed_at'] = datetime.now().isoformat()
            self.save_metadata_json(composite_reference, full_metadata)
            self.processed_tenders.append(full_metadata)

            logger.info(f"✅ Successfully processed: {composite_reference}")
            return True


        finally:
            await human_delay(2, 3)
            try:
                logger.info("Returning to search page...")
                await page.goto(
                    'http://www.marchespublics.gov.ma/?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons',
                    wait_until='domcontentloaded',
                    timeout=60000
                )
                await human_delay(2, 3)
            except Exception as nav_error:
                logger.warning(f"Error navigating back to search: {nav_error}")


    async def run(self, max_tenders: Optional[int] = None):
        """Main execution method"""
        logger.info("=" * 80)
        logger.info("STARTING TENDER DOWNLOAD AND S3 UPLOAD")
        logger.info("=" * 80)
        
        # Load new references
        new_references = self.load_new_references()
        if not new_references:
            logger.warning("No new references to process")
            return
        
        # Limit number of tenders if specified
        if max_tenders:
            new_references = new_references[:max_tenders]
            logger.info(f"Limited to {max_tenders} tenders")
        
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
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
            page.set_default_timeout(120000)
            
            # Process each tender
            for idx, tender_data in enumerate(new_references, 1):
                logger.info(f"\n{'#'*80}")
                logger.info(f"Progress: {idx}/{len(new_references)}")
                logger.info(f"{'#'*80}")
                
                await self.process_tender(page, tender_data)
                
                # Log progress every 5 tenders
                if idx % 5 == 0:
                    self.print_progress()
                
        finally:
            await browser.close()
        
        # Save processed tenders to output JSON
        self.save_processed_tenders()
        
        # Print final summary
        self.print_summary()
    
    def print_progress(self):
        """Print current progress"""
        logger.info("=" * 80)
        logger.info("PROGRESS UPDATE")
        logger.info("=" * 80)
        logger.info(f"Total References: {self.stats['total_references']}")
        logger.info(f"Files Downloaded: {self.stats['files_downloaded']}")
        logger.info(f"S3 Uploaded: {self.stats['s3_uploaded']}")
        logger.info(f"Failed: {self.stats['files_failed']}")
        logger.info("=" * 80)
    
    def print_summary(self):
        """Print execution summary"""
        logger.info("=" * 80)
        logger.info("TENDER DOWNLOAD SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total References: {self.stats['total_references']}")
        logger.info(f"Successfully Processed: {len(self.processed_tenders)}")
        logger.info("")
        logger.info("Download Statistics:")
        logger.info(f"  Files Downloaded: {self.stats['files_downloaded']}")
        logger.info(f"  Skipped (no download): {self.stats['skipped_no_download']}")
        logger.info(f"  Failed Downloads: {self.stats['files_failed']}")
        logger.info("")
        logger.info("S3 Upload Statistics:")
        logger.info(f"  Uploaded to tender_doc_final/: {self.stats['s3_uploaded']}")
        logger.info(f"  Failed: {self.stats['s3_failed']}")
        logger.info("=" * 80)


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Download tender files, extract metadata, and upload to S3'
    )
    parser.add_argument(
        '--input-file',
        default='new_references.json',
        help='Input JSON file with new references (default: new_references.json)'
    )
    parser.add_argument(
        '--output-file',
        default='processed_tenders.json',
        help='Output JSON file with processed tenders (default: processed_tenders.json)'
    )
    parser.add_argument(
        '--downloads-dir',
        default='downloads',
        help='Directory to save ZIP files (default: downloads)'
    )
    parser.add_argument(
        '--metadata-dir',
        default='tenders_metadata',
        help='Directory for per-tender metadata JSON files (default: tenders_metadata)'
    )
    parser.add_argument(
        '--max-tenders',
        type=int,
        help='Maximum number of tenders to process (default: all)'
    )

    args = parser.parse_args()

    # Create and run downloader
    downloader = TenderDownloader(
        input_file=args.input_file,
        output_file=args.output_file,
        downloads_dir=args.downloads_dir,
        metadata_dir=args.metadata_dir
    )

    try:
        await downloader.run(max_tenders=args.max_tenders)
    except KeyboardInterrupt:
        logger.info("\nDownload interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    asyncio.run(main())
