#!/usr/bin/env python3
"""
Phase 3: Knowledge Graph Builder

Reads processed_tenders.json from Db_updater.py, builds RDF triples following
tender_structure.owl, validates with SHACL constraints, and uploads the
resulting N-Triples file to S3.

Usage:
    python3 kg_builder.py --input-file processed_tenders.json

Environment variables required:
    - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME
    - (Optional) JENA_ENDPOINT, JENA_UPDATE_ENDPOINT for validation
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, RDF, RDFS, SKOS, XSD, URIRef

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Namespace definitions
TS      = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
ACTIVITY = Namespace("http://www.tenderintelligence.io/ontology/activity-domains#")
REGIONS = Namespace("http://www.tenderintelligence.io/ontology/morocco-regions#")
QUALIF  = Namespace("http://www.tenderintelligence.io/ontology/qualification#")

# Top-level category → SKOS concept URI
CATEGORY_TOP = {
    'travaux':     ACTIVITY.Travaux,
    'fournitures': ACTIVITY.Fournitures,
    'services':    ACTIVITY.Services,
}


def generate_initials(name: str) -> str:
    """
    Generate initials from buyer name.
    This logic is duplicated from Db_updater.py - MUST stay in sync.
    
    Rules:
    - 2-3 words: use full words joined together
    - 4+ words: take first 3 letters from ALL words
    - 1 word: first 3 letters
    - Empty/ignore words: return first 3 chars of original name
    """
    if not name:
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
    
    # 2-3 words: use full words joined together
    # 4+ words: take first 3 letters from ALL words
    if 2 <= len(words) <= 3:
        return "".join(words)
    else:
        return "".join([w[:3] for w in words])


def slugify(text: str) -> str:
    """Convert text to a slug-friendly format for URI construction."""
    if not text:
        return ""
    
    # Normalize unicode and remove accents
    nfkd_form = unicodedata.normalize('NFKD', text)
    without_accents = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    
    # Replace spaces and special chars with underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', without_accents)
    
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    return sanitized.strip('_').upper()


def parse_date(date_str) -> Optional[str]:
    """
    Parse date string to ISO 8601 xsd:dateTime.
    Tries: fromisoformat → dd/mm/yyyy HH:MM → dd/mm/yyyy
    Handles malformed format: dd/mm/yyyyHH:MM (missing space).
    """
    if not date_str:
        return None
    date_str = str(date_str).strip()
    # Try ISO format first (e.g., "2026-05-12T10:00:00")
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
    except ValueError:
        pass
    # Fix malformed dates (e.g., "03/02/202610:00" → "03/02/2026 10:00")
    date_str = re.sub(r'(\d{2}/\d{2}/\d{4})(\d{2}:\d{2})', r'\1 \2', date_str)
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        except ValueError:
            continue
    logger.warning(f"Could not parse date: {date_str!r}")
    return None


def get_tender_uri(reference: str) -> URIRef:
    """Generate tender URI from composite reference."""
    slug = slugify(reference)
    return TS[f"Tender_{slug}"]


def get_buyer_uri(buyer_name: str) -> URIRef:
    """Generate buyer URI from buyer name."""
    slug = slugify(buyer_name)
    return TS[f"Buyer_{slug}"]


def parse_fr_decimal(value) -> Optional[Decimal]:
    """Parse French-formatted decimal string ('114 956 868,00') to Decimal."""
    if value is None:
        return None
    s = str(value).strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_bool_str(value) -> Optional[bool]:
    """Convert 'Oui'/'Non'/bool/None to bool or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('oui', 'true', '1', 'yes'):
        return True
    if s in ('non', 'false', '0', 'no'):
        return False
    return None


def parse_buyer_name(buyer_raw: str) -> str:
    """Extract display name: 'CODE / CODE - FULL NAME' → 'FULL NAME'."""
    if ' - ' in buyer_raw:
        return buyer_raw.split(' - ', 1)[1].strip()
    return buyer_raw.strip()


class SkosResolver:
    """
    Parses the OWL ontology once and builds normalized-label → URIRef
    lookup dicts for five SKOS schemes. Used by KGBuilder to resolve
    string fields to SKOS concept URIs.
    """

    def __init__(self, ontology_path: Path):
        self._g = Graph()
        self._g.parse(str(ontology_path), format="xml")
        logger.info(f"SkosResolver: loaded {len(self._g)} triples from {ontology_path.name}")
        self.regions        = self._build_scheme_index(REGIONS.Scheme)
        self.activity       = self._build_activity_index()
        self.mode_passation = self._build_scheme_index(TS.ModeDePassationScheme)
        self.qualifications = self._build_subtree_index(QUALIF.QualificationCategory)
        self.agrements      = self._build_subtree_index(QUALIF.Agrement)
        logger.info(
            f"SkosResolver: regions={len(self.regions)}, activity={len(self.activity)}, "
            f"mode_passation={len(self.mode_passation)}, "
            f"qualifications={len(self.qualifications)}, agrements={len(self.agrements)}"
        )

    @staticmethod
    def _normalize(s: str) -> str:
        """Strip accents, lowercase, collapse whitespace."""
        s = unicodedata.normalize('NFKD', s)
        s = ''.join(c for c in s if not unicodedata.combining(c))
        return ' '.join(s.lower().split())

    def _build_scheme_index(self, scheme_uri: URIRef) -> Dict[str, URIRef]:
        """Index all concepts in a scheme by normalized prefLabel."""
        idx: Dict[str, URIRef] = {}
        for concept in self._g.subjects(SKOS.inScheme, scheme_uri):
            for label in self._g.objects(concept, SKOS.prefLabel):
                idx[self._normalize(str(label))] = concept
        return idx

    def _build_activity_index(self) -> Dict[str, URIRef]:
        """Combine all three activity domain schemes into one index."""
        idx: Dict[str, URIRef] = {}
        for scheme in [
            ACTIVITY.SchemeTravaux,
            ACTIVITY.SchemeFournitures,
            ACTIVITY.SchemeServices,
        ]:
            idx.update(self._build_scheme_index(scheme))
        return idx

    def _build_subtree_index(self, root: URIRef) -> Dict[str, URIRef]:
        """Walk narrowerTransitive from root, index every node by prefLabel."""
        idx: Dict[str, URIRef] = {}
        seen: set = set()
        queue = [root]
        while queue:
            node = queue.pop()
            if node in seen:
                continue
            seen.add(node)
            for label in self._g.objects(node, SKOS.prefLabel):
                idx[self._normalize(str(label))] = node
            for child in self._g.objects(node, SKOS.narrowerTransitive):
                queue.append(child)
        return idx

    def resolve(self, scheme: str, label: str) -> Optional[URIRef]:
        """Return the URIRef for `label` in `scheme`, or None if not found."""
        idx = {
            'regions':        self.regions,
            'activity':       self.activity,
            'mode_passation': self.mode_passation,
            'qualifications': self.qualifications,
            'agrements':      self.agrements,
        }.get(scheme)
        if idx is None:
            logger.warning(f"SkosResolver: unknown scheme '{scheme}'")
            return None
        return idx.get(self._normalize(label))


class KGBuilder:
    """
    Knowledge Graph Builder for Phase 3 of the tender pipeline.
    
    Reads processed_tenders.json, builds RDF triples, validates with SHACL,
    and uploads to S3.
    """
    
    def __init__(
        self,
        input_file: Optional[str] = None,
        input_dir: Optional[str] = None,
        output_dir: str = "output",
        s3_bucket: Optional[str] = None,
        s3_prefix: str = "knowledge_Base/Daybatch/",
        ontology_file: str = "tender_structure.owl",
        shacl_file: Optional[str] = None
    ):
        # Step 9: support both --input-file (legacy) and --input-dir (new per-tender JSONs)
        if input_dir:
            self.input_dir = Path(input_dir)
            self.input_file = None
        elif input_file:
            self.input_file = Path(input_file)
            self.input_dir = None
        else:
            raise ValueError("Either input_file or input_dir must be provided")

        self.output_dir = Path(output_dir)
        self.s3_bucket = s3_bucket or os.getenv("S3_BUCKET_NAME")
        self.s3_prefix = s3_prefix
        self.ontology_file = Path(ontology_file)
        self.shacl_file = Path(shacl_file) if shacl_file else None

        # Track seen buyers for deduplication
        self.seen_buyers: set = set()

        # Create output directory if needed
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # SKOS concept resolver — built once from OWL at init time
        if self.ontology_file.exists():
            self.resolver = SkosResolver(self.ontology_file)
        else:
            logger.warning(f"Ontology not found: {self.ontology_file} — SKOS resolution disabled")
            self.resolver = None

        # Initialize S3 client
        if self.s3_bucket:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
        else:
            self.s3_client = None
            logger.warning("S3 bucket not configured - upload will be skipped")

        # Initialize SQS client for posting to OCR_QUEUE
        self.sqs_client = boto3.client(
            'sqs',
            region_name=os.getenv('AWS_REGION', 'eu-west-3'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        self.ocr_queue_url = os.getenv('OCR_QUEUE_URL')

        # Jena connection for direct updates (Step 14)
        self.jena_endpoint = os.getenv('JENA_ENDPOINT')
        self.jena_update_endpoint = os.getenv('JENA_UPDATE_ENDPOINT') # e.g. http://fuseki:3030/tender/update
        self.jena_auth = (os.getenv('JENA_USER', 'admin'), os.getenv('JENA_PASSWORD', 'admin'))

    
    def load_processed_tenders(self) -> List[Dict]:
        """Load processed tenders from JSON file."""
        if not self.input_file or not self.input_file.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

        with open(self.input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        tenders = data.get('tenders', [])
        logger.info(f"Loaded {len(tenders)} tenders from {self.input_file}")
        return tenders

    def load_from_dir(self) -> List[Dict]:
        """
        Step 9: Load per-tender JSONs from tenders_metadata/ directory.

        Reads every *.json file in self.input_dir and skips tenders with
        download_available=False so the KG only contains downloadable tenders
        that also have full metadata.
        """
        if not self.input_dir or not self.input_dir.exists():
            raise FileNotFoundError(f"Input directory not found: {self.input_dir}")

        tenders: List[Dict] = []
        json_files = sorted(self.input_dir.glob('*.json'))

        if not json_files:
            logger.warning(f"No JSON files found in {self.input_dir}")
            return tenders

        for json_path in json_files:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tender = json.load(f)
                # Only include tenders where download succeeded
                if tender.get('download_available') is False:
                    logger.info(f"Skipping (not downloaded): {json_path.stem}")
                    continue
                tenders.append(tender)
            except Exception as e:
                logger.warning(f"Skipping malformed JSON {json_path.name}: {e}")

        logger.info(f"Loaded {len(tenders)} downloadable tenders from {self.input_dir}")
        return tenders

    
    def build_tender_triples(self, tender: Dict) -> Graph:
        """
        Build RDF triples for a single tender from per-tender JSON format.
        Lot triples are included via _build_lot_triples().
        """
        g = Graph()
        g.bind("ts", TS)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("activity", ACTIVITY)
        g.bind("skos", SKOS)
        g.bind("regions", REGIONS)
        g.bind("qualif", QUALIF)

        reference = tender.get('reference')
        if not reference:
            logger.warning("Skipping tender without reference")
            return g

        tender_uri = get_tender_uri(reference)
        g.add((tender_uri, RDF.type, TS.Tenders))

        # ── Core data properties ──────────────────────────────────────────
        g.add((tender_uri, TS.Ref, Literal(reference, datatype=XSD.string)))

        orig_ref = tender.get('original_reference')
        if orig_ref:
            g.add((tender_uri, TS.Has_Original_Reference,
                   Literal(orig_ref, datatype=XSD.string)))

        obj = tender.get('object')
        if obj:
            g.add((tender_uri, TS.Has_Object, Literal(obj, datatype=XSD.string)))

        deadline = tender.get('deadline')
        if deadline:
            parsed = parse_date(deadline)
            if parsed:
                g.add((tender_uri, TS.Has_Deadline,
                       Literal(parsed, datatype=XSD.dateTime)))

        launch_date = tender.get('launch_date')
        if launch_date:
            parsed = parse_date(launch_date)
            if parsed:
                g.add((tender_uri, TS.launch_date,
                       Literal(parsed, datatype=XSD.dateTime)))

        # ── SKOS: main_category → top concept ────────────────────────────
        main_cat = (tender.get('main_category') or '').strip().lower()
        cat_uri = CATEGORY_TOP.get(main_cat)
        if cat_uri:
            g.add((tender_uri, TS.Has_Category, cat_uri))

        # ── SKOS: city / all_cities → Is_Located_In ──────────────────────
        def _add_city(city_str: str):
            if not city_str:
                return
            city_uri = self.resolver.resolve('regions', city_str) if self.resolver else None
            if city_uri:
                g.add((tender_uri, TS.Is_Located_In, city_uri))
                g.add((tender_uri, SKOS.exactMatch, city_uri))
            else:
                g.add((tender_uri, TS.city, Literal(city_str, datatype=XSD.string)))

        city = tender.get('city')
        if city:
            _add_city(city)

        all_cities = tender.get('all_cities') or []
        if isinstance(all_cities, list):
            for c in all_cities:
                if c and c != city:
                    _add_city(c)

        # ── SKOS: mode_passation ──────────────────────────────────────────
        mode_raw = tender.get('mode_passation') or ''
        mode_clean = mode_raw.lstrip('|').strip()
        if mode_clean:
            mode_uri = self.resolver.resolve('mode_passation', mode_clean) if self.resolver else None
            if mode_uri:
                g.add((tender_uri, TS.Has_Mode_Passation, mode_uri))
                g.add((tender_uri, SKOS.exactMatch, mode_uri))
            else:
                g.add((tender_uri, TS.mode_passation,
                       Literal(mode_clean, datatype=XSD.string)))

        # ── SKOS: activity_domains (last segment each) ────────────────────
        for domain_str in (tender.get('activity_domains') or []):
            if not domain_str:
                continue
            last_seg = domain_str.split(' / ')[-1].strip()
            act_uri = self.resolver.resolve('activity', last_seg) if self.resolver else None
            if act_uri:
                g.add((tender_uri, TS.Has_Activity_Domain, act_uri))
                g.add((tender_uri, SKOS.exactMatch, act_uri))
            else:
                g.add((tender_uri, TS.activity_domains,
                       Literal(last_seg, datatype=XSD.string)))

        # ── SKOS: is_sme_reserved ─────────────────────────────────────────
        if tender.get('is_sme_reserved') is True:
            g.add((TS.IsSmeReserved, RDF.type, SKOS.Concept))
            g.add((tender_uri, TS.Is_SME_Reserved, TS.IsSmeReserved))
            g.add((tender_uri, SKOS.exactMatch, TS.IsSmeReserved))

        # ── Plain string data properties ──────────────────────────────────
        for field, prop in [
            ('retrait_address',  TS.retrait_address),
            ('depot_address',    TS.depot_address),
            ('mode_soumission',  TS.mode_soumission),
            ('opening_location', TS.opening_location),
            ('plan_cost',        TS.plan_cost),
            ('reunion',          TS.reunionDetails),
            ('site_visit',       TS.visiteLieuxDetails),
            ('samples_info',     TS.samples_info),
        ]:
            val = tender.get(field)
            if val:
                g.add((tender_uri, prop, Literal(str(val), datatype=XSD.string)))

        # ── Decimal properties ────────────────────────────────────────────
        est_val = parse_fr_decimal(tender.get('estimated_value'))
        if est_val is not None:
            g.add((tender_uri, TS.estimated_value,
                   Literal(est_val, datatype=XSD.decimal)))

        prov_dep = parse_fr_decimal(tender.get('provisional_deposit'))
        if prov_dep is not None:
            g.add((tender_uri, TS.provisional_deposit,
                   Literal(prov_dep, datatype=XSD.decimal)))

        # ── SKOS: qualifications (3rd segment each) ───────────────────────
        for qual_str in (tender.get('qualifications') or []):
            if not qual_str:
                continue
            parts = qual_str.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else qual_str.strip()
            qual_uri = self.resolver.resolve('qualifications', seg) if self.resolver else None
            if qual_uri:
                g.add((tender_uri, TS.Has_Qualification, qual_uri))
                g.add((tender_uri, SKOS.exactMatch, qual_uri))
            else:
                g.add((tender_uri, TS.Has_Qualifications,
                       Literal(seg, datatype=XSD.string)))

        # ── SKOS: agrements (3rd segment each) ────────────────────────────
        for agr_str in (tender.get('agrements') or []):
            if not agr_str:
                continue
            parts = agr_str.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else agr_str.strip()
            agr_uri = self.resolver.resolve('agrements', seg) if self.resolver else None
            if agr_uri:
                g.add((tender_uri, TS.Has_Agrement, agr_uri))
                g.add((tender_uri, SKOS.exactMatch, agr_uri))
            else:
                g.add((tender_uri, TS.requiredAgrements,
                       Literal(seg, datatype=XSD.string)))

        # ── Boolean: variante ─────────────────────────────────────────────
        variante = parse_bool_str(tender.get('variante'))
        if variante is not None:
            g.add((tender_uri, TS.hasVariante,
                   Literal(variante, datatype=XSD.boolean)))

        # ── Documents ─────────────────────────────────────────────────────
        download_available = tender.get('download_available')
        g.add((tender_uri, TS.Has_Is_Documents,
               Literal(bool(download_available), datatype=XSD.boolean)))

        s3_folder = tender.get('s3_folder')
        if s3_folder:
            if not s3_folder.startswith('s3://') and not s3_folder.startswith('http'):
                s3_folder = f"s3://{self.s3_bucket}/{s3_folder}" if self.s3_bucket else s3_folder
            g.add((tender_uri, TS.Has_CPS_Doc,
                   Literal(s3_folder, datatype=XSD.anyURI)))

        # ── Multilot ──────────────────────────────────────────────────────
        lots = tender.get('lots') or []
        g.add((tender_uri, TS.Has_Multilot,
               Literal(len(lots) > 1, datatype=XSD.boolean)))

        # ── Buyer node ────────────────────────────────────────────────────
        buyer_raw = tender.get('buyer') or ''
        if buyer_raw:
            buyer_name = parse_buyer_name(buyer_raw)
            buyer_uri = get_buyer_uri(buyer_name)
            if buyer_uri not in self.seen_buyers:
                g.add((buyer_uri, RDF.type, TS.Buyers))
                g.add((buyer_uri, RDFS.label,
                       Literal(buyer_name, datatype=XSD.string)))
                contacts = tender.get('contacts') or {}
                if contacts.get('name'):
                    g.add((buyer_uri, TS.Has_Contact,
                           Literal(contacts['name'], datatype=XSD.string)))
                if contacts.get('email'):
                    g.add((buyer_uri, TS.Has_Mail,
                           Literal(contacts['email'], datatype=XSD.string)))
                if contacts.get('phone'):
                    g.add((buyer_uri, TS.Has_Phone,
                           Literal(contacts['phone'], datatype=XSD.string)))
                opening_loc = tender.get('opening_location')
                if opening_loc:
                    g.add((buyer_uri, TS.Has_Adress,
                           Literal(opening_loc, datatype=XSD.string)))
                self.seen_buyers.add(buyer_uri)
            g.add((tender_uri, TS.Launched_by, buyer_uri))

        # ── Lot nodes ─────────────────────────────────────────────────────
        for lot in lots:
            self._build_lot_triples(g, tender_uri, reference, lot)

        return g

    def _build_lot_triples(
        self, g: Graph, tender_uri: URIRef, reference: str, lot: Dict
    ) -> None:
        """Add lot triples to graph g. Called once per lot dict."""
        lot_n = lot.get('lot number')
        if lot_n is None:
            return
        lot_id = str(lot_n)
        lot_uri = TS[f"Lot_{slugify(reference)}_{lot_id}"]
        g.add((lot_uri, RDF.type, TS.Lots))
        g.add((lot_uri, TS.lotID, Literal(lot_id, datatype=XSD.string)))
        g.add((tender_uri, TS.Has_lot, lot_uri))

        lot_desc = lot.get(f'lot{lot_id}_object')
        if lot_desc:
            g.add((lot_uri, TS.lot_description,
                   Literal(lot_desc, datatype=XSD.string)))

        lot_est = parse_fr_decimal(lot.get(f'Lot{lot_id}_estimation'))
        if lot_est is not None:
            g.add((lot_uri, TS.lot_estimated_value,
                   Literal(lot_est, datatype=XSD.decimal)))

        lot_caut = parse_fr_decimal(lot.get(f'Lot{lot_id}_caution'))
        if lot_caut is not None:
            g.add((lot_uri, TS.lot_provisional_deposit,
                   Literal(lot_caut, datatype=XSD.decimal)))

        lot_qual = lot.get(f'Lot{lot_id}_qualification')
        if lot_qual:
            parts = lot_qual.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else lot_qual.strip()
            qual_uri = self.resolver.resolve('qualifications', seg) if self.resolver else None
            if qual_uri:
                g.add((lot_uri, TS.Has_Qualification, qual_uri))
                g.add((lot_uri, SKOS.exactMatch, qual_uri))
            else:
                g.add((lot_uri, TS.lot_qualifications,
                       Literal(seg, datatype=XSD.string)))

        lot_agr = lot.get(f'Lot{lot_id}_agreement')
        if lot_agr:
            parts = lot_agr.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else lot_agr.strip()
            agr_uri = self.resolver.resolve('agrements', seg) if self.resolver else None
            if agr_uri:
                g.add((lot_uri, TS.Has_Agrement, agr_uri))
                g.add((lot_uri, SKOS.exactMatch, agr_uri))
            else:
                g.add((lot_uri, TS.lot_agrements,
                       Literal(seg, datatype=XSD.string)))

        samples = lot.get('Procpectus_et_echantillons')
        if samples:
            g.add((lot_uri, TS.samples_info,
                   Literal(str(samples), datatype=XSD.string)))

        reunion = lot.get('Reunion')
        if reunion:
            parsed = parse_date(reunion)
            if parsed:
                g.add((lot_uri, TS.lot_meeting_date,
                       Literal(parsed, datatype=XSD.dateTime)))

        visite = lot.get('visite_des_lieux')
        if visite:
            parsed = parse_date(visite)
            if parsed:
                g.add((lot_uri, TS.lot_site_visit,
                       Literal(parsed, datatype=XSD.dateTime)))

        lot_var = parse_bool_str(lot.get('variante'))
        if lot_var is not None:
            g.add((lot_uri, TS.lot_variant_allowed,
                   Literal(lot_var, datatype=XSD.boolean)))

        env = lot.get('Env_consideration')
        if env:
            g.add((lot_uri, TS.lot_env_considerations,
                   Literal(str(env), datatype=XSD.string)))

        if parse_bool_str(lot.get('Reserve_TPE_PME')) is True:
            g.add((TS.IsSmeReserved, RDF.type, SKOS.Concept))
            g.add((lot_uri, TS.Is_SME_Reserved, TS.IsSmeReserved))
            g.add((lot_uri, SKOS.exactMatch, TS.IsSmeReserved))
    
    def build_batch_graph(self, tenders: List[Dict]) -> Graph:
        """
        Build a complete RDF graph from all tenders.
        
        Returns a single rdflib.Graph containing all triples.
        """
        # Reset seen_buyers for fresh build
        self.seen_buyers = set()
        
        batch_graph = Graph()
        batch_graph.bind("ts",       TS)
        batch_graph.bind("rdfs",     RDFS)
        batch_graph.bind("xsd",      XSD)
        batch_graph.bind("activity", ACTIVITY)
        batch_graph.bind("skos",     SKOS)
        batch_graph.bind("regions",  REGIONS)
        batch_graph.bind("qualif",   QUALIF)
        
        for tender in tenders:
            tender_graph = self.build_tender_triples(tender)
            # Merge all triples into batch graph
            for triple in tender_graph:
                batch_graph.add(triple)
        
        logger.info(f"Built graph with {len(batch_graph)} triples for {len(tenders)} tenders")
        return batch_graph
    
    def validate_consistency(self, graph: Graph) -> List[str]:
        """
        Perform ontology-based consistency checks using SPARQL ASK queries.
        
        Returns list of error messages. Empty list means consistency passed.
        """
        errors = []
        
        # Check 1: Every Tender must have rdf:type ts:Tenders
        check1 = graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            ASK {
                ?tender a ts:Tenders .
                FILTER NOT EXISTS { ?tender rdf:type ts:Tenders }
            }
        """)
        
        # Check 2: Every Tender must have ts:Launched_by to a ts:Buyers
        check2_query = """
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            
            ASK {
                ?tender a ts:Tenders .
                FILTER NOT EXISTS { ?tender ts:Launched_by ?buyer }
            }
        """
        # We need to check this differently - find tenders without Launched_by
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?tender WHERE {
                ?tender rdf:type ts:Tenders .
                FILTER NOT EXISTS { ?tender ts:Launched_by ?buyer }
            }
        """))
        if result:
            errors.append(f"Found {len(result)} tenders without ts:Launched_by relationship")
        
        # Check 3: Every Tender must have ts:Has_Object
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?tender WHERE {
                ?tender rdf:type ts:Tenders .
                FILTER NOT EXISTS { ?tender ts:Has_Object ?obj }
            }
        """))
        if result:
            errors.append(f"Found {len(result)} tenders without ts:Has_Object")
        
        # Check 4: Every Tender must have ts:Ref
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?tender WHERE {
                ?tender rdf:type ts:Tenders .
                FILTER NOT EXISTS { ?tender ts:Ref ?ref }
            }
        """))
        if result:
            errors.append(f"Found {len(result)} tenders without ts:Ref")
        
        # Check 5: Every Buyer must have rdf:type ts:Buyers
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            
            SELECT ?buyer WHERE {
                ?buyer rdfs:label ?label .
                FILTER NOT EXISTS { ?buyer rdf:type ts:Buyers }
            }
        """))
        if result:
            errors.append(f"Found {len(result)} buyers without rdf:type ts:Buyers")
        
        # Check 6: Every Buyer must have rdfs:label
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?buyer WHERE {
                ?buyer rdf:type ts:Buyers .
                FILTER NOT EXISTS { ?buyer rdfs:label ?label }
            }
        """))
        if result:
            errors.append(f"Found {len(result)} buyers without rdfs:label")
        
        # Check 7 (NEW — Step 10): Every Tender that has s3_folder must have Has_CPS_Doc
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            SELECT ?tender WHERE {
                ?tender rdf:type ts:Tenders .
                ?tender ts:Has_Is_Documents "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .
                FILTER NOT EXISTS { ?tender ts:Has_CPS_Doc ?doc }
            }
        """))
        if result:
            errors.append(
                f"Found {len(result)} tenders with Has_Is_Documents=true but no ts:Has_CPS_Doc"
            )

        # Check 8 (NEW — Step 10): Launched_by must point to a ts:Buyers node
        result = list(graph.query("""
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            SELECT ?tender ?buyer WHERE {
                ?tender rdf:type ts:Tenders .
                ?tender ts:Launched_by ?buyer .
                FILTER NOT EXISTS { ?buyer rdf:type ts:Buyers }
            }
        """))
        if result:
            errors.append(
                f"Found {len(result)} Launched_by links to non-ts:Buyers nodes"
            )

        if errors:
            logger.error("Consistency validation failed:")
            for err in errors:
                logger.error(f"  - {err}")
        else:
            logger.info("Consistency validation passed (8 checks)")

        return errors

    
    def validate_shacl(self, graph: Graph) -> Tuple[bool, str]:
        """
        Validate graph against SHACL shapes.

        Returns (conforms, results_text) tuple.

        NOTE: pyshacl.validate() with large ontologies (8000+ triples) can hang indefinitely
        due to infinite loops in the reasoning engine. Setting SKIP_SHACL=1 env var bypasses this.
        """
        import os

        # Allow skipping SHACL validation via environment variable
        if os.getenv('SKIP_SHACL'):
            logger.warning("SHACL validation skipped (SKIP_SHACL=1)")
            return True, "Skipped via SKIP_SHACL env var"

        try:
            from pyshacl import validate
        except ImportError:
            logger.warning("pyshacl not installed - skipping SHACL validation")
            return True, "pyshacl not available"

        if not self.shacl_file or not self.shacl_file.exists():
            logger.info("No SHACL shapes file - skipping validation")
            return True, "No SHACL file"

        # Load SHACL shapes
        shacl_graph = Graph()
        shacl_graph.parse(self.shacl_file, format="turtle")

        # Load ontology
        ontology_graph = Graph()
        if self.ontology_file.exists():
            ontology_graph.parse(self.ontology_file, format="xml")

        # Validate
        conforms, results_graph, results_text = validate(
            graph,
            shacl_graph=shacl_graph,
            ont_graph=ontology_graph,
            inference='none',
            abort_on_first=False
        )

        if conforms:
            logger.info("SHACL validation passed")
        else:
            logger.error("SHACL validation failed:")
            logger.error(results_text)

        return conforms, results_text
    
    def serialize_ntriples(self, graph: Graph) -> Path:
        """Serialize graph to N-Triples file."""
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"batch_{timestamp}.nt"
        
        # Serialize to N-Triples
        graph.serialize(format="nt", destination=str(output_file))
        
        logger.info(f"Serialized {len(graph)} triples to {output_file}")
        return output_file
    
    def upload_to_s3(self, nt_file_path: Path, tender_count: int) -> bool:
        """Upload N-Triples file to S3."""
        if not self.s3_client or not self.s3_bucket:
            logger.warning("S3 not configured - skipping upload")
            return False
        
        try:
            s3_key = f"{self.s3_prefix}{nt_file_path.name}"
            
            self.s3_client.upload_file(
                str(nt_file_path),
                self.s3_bucket,
                s3_key,
                ExtraArgs={
                    'ContentType': 'application/n-triples',
                    'Metadata': {
                        'batch_date': datetime.now().isoformat(),
                        'tender_count': str(tender_count),
                        'source_file': self.input_file.name if self.input_file else str(self.input_dir)
                    }
                }
            )
            
            logger.info(f"Uploaded to s3://{self.s3_bucket}/{s3_key}")
            return True
        
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            return False
    
    def post_tenders_to_ocr_queue(self, tenders: List[Dict]) -> bool:
        """
        Post tender references to SQS OCR_QUEUE for microservices pipeline.

        Args:
            tenders: List of processed tender dictionaries

        Returns:
            True if successful, False otherwise
        """
        if not self.ocr_queue_url:
            logger.warning("OCR_QUEUE_URL not configured - skipping SQS posting")
            return True  # Don't fail if queue not configured

        try:
            posted_count = 0
            failed_count = 0

            for tender in tenders:
                tender_ref = tender.get('reference')
                s3_folder = tender.get('s3_folder')

                if not tender_ref or not s3_folder:
                    logger.warning(f"Skipping tender missing reference or s3_folder: {tender_ref}")
                    failed_count += 1
                    continue

                # Prepare message for OCR_QUEUE
                message_body = {
                    'tender_ref': tender_ref,
                    's3_paths': [s3_folder]  # 2_Ocr can handle folder paths
                }

                try:
                    self.sqs_client.send_message(
                        QueueUrl=self.ocr_queue_url,
                        MessageBody=json.dumps(message_body)
                    )
                    posted_count += 1
                    logger.info(f"Posted to OCR_QUEUE: {tender_ref}")
                except Exception as e:
                    logger.error(f"Failed to post {tender_ref} to OCR_QUEUE: {e}")
                    failed_count += 1

            logger.info(f"OCR_QUEUE posting: {posted_count} succeeded, {failed_count} failed")
            return failed_count == 0

        except Exception as e:
            logger.error(f"Error posting to OCR_QUEUE: {e}")
            return False

    def insert_triples_to_jena(self, graph: Graph) -> bool:
        """
        Push graph triples directly to Jena Fuseki via SPARQL UPDATE.
        
        Args:
            graph: rdflib.Graph containing triples to insert
            
        Returns:
            True if update succeeded or wasn't configured, False on error
        """
        if not self.jena_update_endpoint:
            logger.info("JENA_UPDATE_ENDPOINT not configured - skipping Jena update")
            return True

        if len(graph) == 0:
            return True

        try:
            import requests
            
            # Serialize to N-Triples for the update payload
            nt_data = graph.serialize(format="nt")
            
            # Build SPARQL Update query
            update_query = f"INSERT DATA {{ {nt_data} }}"
            
            logger.info(f"Pushing {len(graph)} triples to Jena: {self.jena_update_endpoint}")
            
            response = requests.post(
                self.jena_update_endpoint,
                data={'update': update_query},
                auth=self.jena_auth if self.jena_auth[0] else None,
                timeout=30
            )
            
            if response.status_code >= 400:
                logger.error(f"Jena update failed ({response.status_code}): {response.text}")
                return False
                
            logger.info("✅ Successfully pushed shell triples to Jena")
            return True

        except Exception as e:
            logger.error(f"Error pushing triples to Jena: {e}")
            return False

    def run(self) -> int:
        """
        Main orchestrator for Phase 3.
        
        Returns exit code:
            0 - Success
            1 - Input error
            2 - Consistency check failed
            3 - SHACL validation failed
            4 - S3 upload failed
        """
        logger.info("=" * 60)
        logger.info("PHASE 3: KNOWLEDGE GRAPH BUILDER")
        logger.info("=" * 60)

        # Step 9: Load tenders from dir (per-tender JSONs) or legacy single file
        try:
            if self.input_dir:
                tenders = self.load_from_dir()
                source_label = str(self.input_dir)
            else:
                tenders = self.load_processed_tenders()
                source_label = str(self.input_file)
        except FileNotFoundError as e:
            logger.error(f"Input error: {e}")
            return 1
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            return 1
        
        if not tenders:
            logger.warning("No tenders found in input file")
            return 1
        
        # Step 2: Build batch graph
        batch_graph = self.build_batch_graph(tenders)
        
        if len(batch_graph) == 0:
            logger.error("No triples built - aborting")
            return 1
        
        # Step 3: Consistency check
        consistency_errors = self.validate_consistency(batch_graph)
        if consistency_errors:
            logger.error("Consistency check failed - aborting")
            return 2
        
        # Step 4: SHACL validation
        conforms, shacl_results = self.validate_shacl(batch_graph)
        if not conforms:
            logger.error("SHACL validation failed - aborting")
            logger.error(shacl_results)
            return 3
        
        # Step 5: Serialize to N-Triples
        nt_file = self.serialize_ntriples(batch_graph)
        
        # Step 5b: Push to local Jena (Step 14)
        self.insert_triples_to_jena(batch_graph)

        # Step 6: Upload to S3
        if self.s3_client:
            success = self.upload_to_s3(nt_file, len(tenders))
            if not success:
                logger.error("S3 upload failed")
                return 4
        
        logger.info("=" * 60)
        logger.info("PHASE 3 COMPLETED SUCCESSFULLY")
        logger.info(f"Source: {source_label}")
        logger.info(f"Tenders processed: {len(tenders)}")
        logger.info(f"Triples generated: {len(batch_graph)}")
        logger.info(f"Output file: {nt_file}")
        if self.s3_client:
            logger.info(f"S3 prefix: s3://{self.s3_bucket}/{self.s3_prefix}")
        logger.info("=" * 60)

        # Post tender references to OCR_QUEUE to start microservices pipeline
        logger.info("Posting tenders to OCR_QUEUE for microservices pipeline...")
        if self.post_tenders_to_ocr_queue(tenders):
            logger.info("Successfully posted all tenders to OCR_QUEUE")
        else:
            logger.warning("Some tenders failed to post to OCR_QUEUE (pipeline may be delayed)")

        return 0



def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Phase 3: Knowledge Graph Builder — Build RDF from processed tenders"
    )
    # Step 9: --input-dir replaces --input-file when reading from tenders_metadata/
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--input-file',
        help='Legacy: single processed_tenders.json from Db_updater.py'
    )
    input_group.add_argument(
        '--input-dir',
        help='Directory of per-tender JSON files (tenders_metadata/) — preferred'
    )
    parser.add_argument(
        '--output-dir',
        default='output',
        help='Output directory for N-Triples files (default: output/)'
    )
    parser.add_argument(
        '--s3-bucket',
        default=os.getenv('S3_BUCKET_NAME'),
        help='S3 bucket name (default: from S3_BUCKET_NAME env var)'
    )
    parser.add_argument(
        '--s3-prefix',
        default='knowledge_Base/Daybatch/',
        help='S3 key prefix (default: knowledge_Base/Daybatch/)'
    )
    parser.add_argument(
        '--ontology',
        default='tender_structure.owl',
        help='Path to OWL ontology file (default: tender_structure.owl)'
    )
    parser.add_argument(
        '--shacl-shapes',
        default='tender_shacl_shapes.ttl',
        help='Path to SHACL shapes file (default: tender_shacl_shapes.ttl)'
    )

    args = parser.parse_args()

    builder = KGBuilder(
        input_file=args.input_file,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        ontology_file=args.ontology,
        shacl_file=args.shacl_shapes
    )

    exit_code = builder.run()
    sys.exit(exit_code)



if __name__ == "__main__":
    main()
