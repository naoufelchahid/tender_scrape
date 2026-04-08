from rdflib import Graph, Literal, RDF, XSD
from typing import List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def parse_date(date_str: str):
    if not date_str:
        return None
    try:
        from dateutil.parser import parse
        return parse(date_str).date()
    except Exception:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except ValueError:
            return None


from .models import ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from .uri_builder import (
    get_tender_uri, get_bordereau_uri,
    get_article_uri, get_specification_uri, get_reglement_uri,
    get_spec_chunk_uri, get_admin_chunk_uri,
    TS
)

import re

def parse_float_safely(val: Any) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 0.0
    clean_val = re.sub(r'\s+', '', str(val))
    clean_val = clean_val.replace(',', '.')
    try:
        return float(clean_val)
    except ValueError:
        logger.warning(f"Could not parse '{val}' as float, defaulting to 0.0")
        return 0.0


class JsonToRdfMapper:
    def __init__(self, tender_ref: str, tender_iri: Optional[str] = None):
        """
        Args:
            tender_ref: the tender folder reference (e.g. '003_2026_SRMCS').
            tender_iri: the IRI of the existing tender node in Jena KB.
                        If provided, it overrides the computed URI.
        """
        self.tender_ref = tender_ref
        if tender_iri:
            from rdflib import URIRef
            self.tender_uri = URIRef(tender_iri)
        else:
            self.tender_uri = get_tender_uri(tender_ref)
        self.graph = Graph()
        self.graph.bind("ts", TS)

    # ------------------------------------------------------------------ #
    # Avis vector key                                                      #
    # ------------------------------------------------------------------ #

    def map_avis_vector_key(self, vector_key: str):
        """Write the avis embedding vector S3 key onto the existing tender node."""
        self.graph.add((self.tender_uri, TS.Has_Avis_Vector_Key, Literal(vector_key, datatype=XSD.string)))

    # ------------------------------------------------------------------ #
    # Product mapping                                                      #
    # ------------------------------------------------------------------ #

    def map_products(self, products: List[ProductChunkMetadata], bordereau_content: Optional[str] = None):
        """Map a list of products to a Bordereau and Articles."""
        if not products:
            return

        bordereau_uri = get_bordereau_uri(self.tender_ref)
        self.graph.add((bordereau_uri, RDF.type, TS.Bordereaux))

        if bordereau_content:
            self.graph.add((bordereau_uri, TS.Has_Bordereau_Content, Literal(bordereau_content, datatype=XSD.string)))

        self.graph.add((self.tender_uri, TS.Has_Bordereau, bordereau_uri))
        self.graph.add((bordereau_uri, TS.Is_Bordereau_of, self.tender_uri))

        for i, product in enumerate(products):
            article_uri = get_article_uri(self.tender_ref, i)
            self.graph.add((article_uri, RDF.type, TS.Articles))

            if product.product_header:
                self.graph.add((article_uri, TS.Has_Product_Header, Literal(product.product_header, datatype=XSD.string)))
            
            # SHACL requires Has_Designation. Use product_header or chunk_index as fallback.
            designation = product.designation or product.product_header or f"Article {i+1}"
            self.graph.add((article_uri, TS.Has_Designation, Literal(designation, datatype=XSD.string)))
            if product.quantity is not None:
                val = parse_float_safely(product.quantity)
                self.graph.add((article_uri, TS.Has_quantity, Literal(val, datatype=XSD.float)))
            if product.unit:
                self.graph.add((article_uri, TS.Has_Unit, Literal(product.unit, datatype=XSD.string)))

            self.graph.add((bordereau_uri, TS.Has_Article, article_uri))
            self.graph.add((article_uri, TS.Is_Article_of, bordereau_uri))

    # ------------------------------------------------------------------ #
    # Specification mapping — chunk-as-node                               #
    # ------------------------------------------------------------------ #

    def map_specification(self, chunks: List[ChunkItem], s3_uri: str, chunk_vector_keys: Optional[List[str]] = None):
        """
        Map specification chunks using the chunk-as-node architecture.

        Each chunk becomes a new TenderSpecifications node:
          - URI: ts:SpecChunk_{slug}_{index}
          - ts:Has_Chunk_Identifier = H3 header text
          - ts:Has_Vector_Key = vector store S3 key
          - linked to parent spec via ts:Has_Chunk
        """
        spec_uri = get_specification_uri(self.tender_ref)
        self.graph.add((spec_uri, RDF.type, TS.TenderSpecifications))
        self.graph.add((spec_uri, TS.Has_CPS_Doc, Literal(s3_uri, datatype=XSD.string)))

        self.graph.add((self.tender_uri, TS.Has_specifications, spec_uri))
        self.graph.add((spec_uri, TS.Is_specifications_of, self.tender_uri))

        for i, chunk in enumerate(chunks):
            chunk_uri = get_spec_chunk_uri(self.tender_ref, i)
            self.graph.add((chunk_uri, RDF.type, TS.TenderSpecifications))

            # H3 header as identifier
            h3_header = None
            if hasattr(chunk.metadata, 'title') and chunk.metadata.title:
                h3_header = chunk.metadata.title
            elif isinstance(chunk.metadata, dict):
                h3_header = chunk.metadata.get('title')

            if h3_header:
                self.graph.add((chunk_uri, TS.Has_Chunk_Identifier, Literal(h3_header, datatype=XSD.string)))
            else:
                # Fallback identifier using index
                self.graph.add((chunk_uri, TS.Has_Chunk_Identifier, Literal(f"chunk_{i}", datatype=XSD.string)))

            # Vector Key
            if chunk_vector_keys and i < len(chunk_vector_keys) and chunk_vector_keys[i]:
                self.graph.add((chunk_uri, TS.Has_Vector_Key, Literal(chunk_vector_keys[i], datatype=XSD.string)))

            # Connect chunk to parent spec node
            self.graph.add((spec_uri, TS.Has_Chunk, chunk_uri))

    # ------------------------------------------------------------------ #
    # Administrative mapping — chunk-as-node                             #
    # ------------------------------------------------------------------ #

    def map_administrative(self, chunks: List[ChunkItem], s3_uri: str, chunk_vector_keys: Optional[List[str]] = None):
        """
        Map administrative (reglement) chunks using the chunk-as-node architecture.

        Each chunk becomes a new TenderReglement node:
          - URI: ts:RCChunk_{slug}_{index}
          - ts:Has_Chunk_Identifier = H3 header text
          - ts:Has_Vector_Key = vector store S3 key
          - linked to parent RC via ts:Has_Chunk
        """
        reg_uri = get_reglement_uri(self.tender_ref)
        self.graph.add((reg_uri, RDF.type, TS.TenderReglement))
        self.graph.add((reg_uri, TS.Has_RC_Doc, Literal(s3_uri, datatype=XSD.string)))

        self.graph.add((self.tender_uri, TS.Has_Reglement_Consultation, reg_uri))
        self.graph.add((reg_uri, TS.Is_Reglement_Consultation_Of, self.tender_uri))

        for i, chunk in enumerate(chunks):
            chunk_uri = get_admin_chunk_uri(self.tender_ref, i)
            self.graph.add((chunk_uri, RDF.type, TS.TenderReglement))

            # H3 header as identifier
            h3_header = None
            if hasattr(chunk.metadata, 'title') and chunk.metadata.title:
                h3_header = chunk.metadata.title
            elif isinstance(chunk.metadata, dict):
                h3_header = chunk.metadata.get('title')

            if h3_header:
                self.graph.add((chunk_uri, TS.Has_Chunk_Identifier, Literal(h3_header, datatype=XSD.string)))
            else:
                self.graph.add((chunk_uri, TS.Has_Chunk_Identifier, Literal(f"chunk_{i}", datatype=XSD.string)))

            # Vector Key
            if chunk_vector_keys and i < len(chunk_vector_keys) and chunk_vector_keys[i]:
                self.graph.add((chunk_uri, TS.Has_Vector_Key, Literal(chunk_vector_keys[i], datatype=XSD.string)))

            # Connect chunk to parent reglement node
            self.graph.add((reg_uri, TS.Has_Chunk, chunk_uri))

    # ------------------------------------------------------------------ #
    # Serialization                                                        #
    # ------------------------------------------------------------------ #

    def get_ntriples(self) -> str:
        """Serialize as N-Triples (no @prefix headers) for SPARQL INSERT DATA compatibility."""
        return self.graph.serialize(format="nt")

    def get_turtle(self) -> str:
        return self.graph.serialize(format="turtle")
