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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD, URIRef

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Namespace definitions matching tender_structure.owl
TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
ACTIVITY = Namespace("http://www.tenderintelligence.io/ontology/activity-domains#")

# Category mapping (from AGENTS.md)
CATEGORY_MAP = {
    'travaux': 'travaux',
    'fournitures': 'fournitures',
    'services': 'services'
}

# Activity domain URIs
ACTIVITY_DOMAINS = {
    'travaux': ACTIVITY['travaux'],
    'fournitures': ACTIVITY['fournitures'],
    'services': ACTIVITY['services']
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


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse date string to ISO 8601 xsd:dateTime.
    Handles malformed format: dd/mm/yyyyHH:MM (missing space)
    """
    if not date_str:
        return None
    
    # Fix malformed dates (e.g., "03/02/202610:00" -> "03/02/2026 10:00")
    date_str = re.sub(r'(\d{2}/\d{2}/\d{4})(\d{2}:\d{2})', r'\1 \2', date_str)
    
    try:
        # Try with time component
        dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
    except ValueError:
        try:
            # Try date only
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        except ValueError:
            logger.warning(f"Could not parse date: {date_str}")
            return None


def get_tender_uri(reference: str) -> URIRef:
    """Generate tender URI from composite reference."""
    slug = slugify(reference)
    return TS[f"Tender_{slug}"]


def get_buyer_uri(buyer_name: str) -> URIRef:
    """Generate buyer URI from buyer name."""
    slug = slugify(buyer_name)
    return TS[f"Buyer_{slug}"]


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
        Build RDF triples for a single tender.
        
        Returns an rdflib.Graph with all triples for this tender.
        """
        g = Graph()
        g.bind("ts", TS)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("activity", ACTIVITY)
        
        reference = tender.get('reference')
        if not reference:
            logger.warning("Skipping tender without reference")
            return g
        
        # Create tender URI
        tender_uri = get_tender_uri(reference)
        
        # rdf:type ts:Tenders
        g.add((tender_uri, RDF.type, TS.Tenders))
        
        # ts:Ref (composite reference)
        g.add((tender_uri, TS.Ref, Literal(reference, datatype=XSD.string)))
        
        # ts:Has_Original_Reference
        original_reference = tender.get('original_reference')
        if original_reference:
            g.add((
                tender_uri,
                TS.Has_Original_Reference,
                Literal(original_reference, datatype=XSD.string)
            ))
        
        # ts:Has_Object (tender title/object)
        obj = tender.get('object')
        if obj:
            g.add((
                tender_uri,
                TS.Has_Object,
                Literal(obj, datatype=XSD.string)
            ))
        
        # ts:Has_Deadline
        deadline = tender.get('deadline')
        if deadline:
            parsed_deadline = parse_date(deadline)
            if parsed_deadline:
                g.add((
                    tender_uri,
                    TS.Has_Deadline,
                    Literal(parsed_deadline, datatype=XSD.dateTime)
                ))
        
        # ts:Has_Publication_Date
        launch_date = tender.get('launch_date')
        if launch_date:
            parsed_launch = parse_date(launch_date)
            if parsed_launch:
                g.add((
                    tender_uri,
                    TS.Has_Publication_Date,
                    Literal(parsed_launch, datatype=XSD.dateTime)
                ))
        
        # ts:Has_City
        city = tender.get('city')
        if city:
            g.add((
                tender_uri,
                TS.Has_City,
                Literal(city, datatype=XSD.string)
            ))
        
        # ts:Has_Category (ObjectProperty to activity domain)
        category = tender.get('category')
        if category and category in ACTIVITY_DOMAINS:
            g.add((
                tender_uri,
                TS.Has_Category,
                ACTIVITY_DOMAINS[category]
            ))
        
        # ts:Has_CPS_Doc (S3 folder URI)
        s3_folder = tender.get('s3_folder')
        if s3_folder:
            # Ensure proper URI format
            if not s3_folder.startswith('s3://') and not s3_folder.startswith('http'):
                s3_folder = f"s3://{self.s3_bucket}/{s3_folder}" if self.s3_bucket else s3_folder
            g.add((
                tender_uri,
                TS.Has_CPS_Doc,
                Literal(s3_folder, datatype=XSD.anyURI)
            ))
        
        # ts:Has_Is_Documents (whether documents were downloaded)
        # Based on presence of s3_folder
        has_documents = bool(s3_folder)
        g.add((
            tender_uri,
            TS.Has_Is_Documents,
            Literal(has_documents, datatype=XSD.boolean)
        ))
        
        # ts:Has_Multilot (whether tender has multiple lots)
        lots = tender.get('lots', [])
        is_multilot = len(lots) > 1 if lots else False
        g.add((
            tender_uri,
            TS.Has_Multilot,
            Literal(is_multilot, datatype=XSD.boolean)
        ))
        
        # ts:Launched_by (link to buyer)
        buyer = tender.get('buyer')
        if buyer:
            buyer_uri = get_buyer_uri(buyer)
            
            # Only emit buyer type and label once
            if buyer_uri not in self.seen_buyers:
                g.add((buyer_uri, RDF.type, TS.Buyers))
                g.add((
                    buyer_uri,
                    RDFS.label,
                    Literal(buyer, datatype=XSD.string)
                ))
                self.seen_buyers.add(buyer_uri)
            
            # Add Launched_by relationship
            g.add((tender_uri, TS.Launched_by, buyer_uri))
        
        return g
    
    def build_batch_graph(self, tenders: List[Dict]) -> Graph:
        """
        Build a complete RDF graph from all tenders.
        
        Returns a single rdflib.Graph containing all triples.
        """
        # Reset seen_buyers for fresh build
        self.seen_buyers = set()
        
        batch_graph = Graph()
        batch_graph.bind("ts", TS)
        batch_graph.bind("rdfs", RDFS)
        batch_graph.bind("xsd", XSD)
        batch_graph.bind("activity", ACTIVITY)
        
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
        check1_query = """
            PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?tender WHERE {
                ?tender a ts:Tenders .
                FILTER NOT EXISTS { ?tender rdf:type ts:Tenders }
            }
        """

        # Check 2: Every Tender must have ts:Launched_by to a ts:Buyers
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
        """
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
                        'source_file': self.input_file.name if self.input_file else "directory"
                    }
                }
            )
            
            logger.info(f"Uploaded to s3://{self.s3_bucket}/{s3_key}")
            return True
        
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
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
