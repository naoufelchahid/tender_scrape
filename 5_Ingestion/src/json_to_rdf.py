from rdflib import Graph, Literal, RDF, XSD
from typing import List, Dict, Any, Optional
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


from .models import AvisMetadata, LotMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from .uri_builder import (
    get_tender_uri, get_bordereau_uri,
    get_article_uri, get_specification_uri, get_reglement_uri,
    get_lot_uri, get_spec_chunk_uri, get_admin_chunk_uri,
    TS
)


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
    # Avis mapping                                                         #
    # ------------------------------------------------------------------ #

    def map_avis(self, metadata: AvisMetadata):
        """Map Avis supplemental data properties to the existing Tender node.

        Does NOT re-create core tender data (type, buyer, category, region, deadline)
        that already exists in the KB from the migration container.
        """
        if metadata.objet:
            self.graph.add((self.tender_uri, TS.Has_Object, Literal(metadata.objet, datatype=XSD.string)))

        # Mode properties
        if metadata.mode_de_soumission:
            self.graph.add((self.tender_uri, TS.Has_Mode_Soumission, Literal(metadata.mode_de_soumission, datatype=XSD.string)))
        if metadata.mode_de_passation:
            self.graph.add((self.tender_uri, TS.Has_Mode_Passation, Literal(metadata.mode_de_passation, datatype=XSD.string)))

        # Multilot flag
        try:
            lot_num = int(metadata.lot_number)
        except (ValueError, TypeError):
            lot_num = 1 if str(metadata.lot_number).lower() in ("lot unique", "0") else 0

        is_multilot = lot_num > 1
        self.graph.add((self.tender_uri, TS.Has_Multilot, Literal(is_multilot, datatype=XSD.boolean)))

        if metadata.budget:
            val = float(metadata.budget) if isinstance(metadata.budget, (int, float)) else metadata.budget
            self.graph.add((self.tender_uri, TS.Has_Budget, Literal(val, datatype=XSD.float)))

        # Parse dates — launch and deadline already exist from migration, not re-added here
        d_launch = parse_date(metadata.launch_date)
        d_deadline = parse_date(metadata.deadline)
        d_adj = parse_date(metadata.adjudication_date)
        d_exec = parse_date(metadata.execution_start_date)

        # Avis-specific dates (not in migration)
        if d_adj:
            self.graph.add((self.tender_uri, TS.hasAdjudicationDate, Literal(d_adj, datatype=XSD.date)))
        if d_exec:
            self.graph.add((self.tender_uri, TS.hasExecutionStartDate, Literal(d_exec, datatype=XSD.date)))

        # Duration calculations (enrichment computed fields)
        if d_launch and d_deadline:
            duration = (d_deadline - d_launch).days
            if duration >= 0:
                self.graph.add((self.tender_uri, TS.durationLaunchToDeadlineDays, Literal(duration, datatype=XSD.integer)))
            else:
                logger.warning(f"Negative launch-deadline duration for {self.tender_ref}")

        if d_deadline and d_adj:
            duration = (d_adj - d_deadline).days
            if duration >= 0:
                self.graph.add((self.tender_uri, TS.durationDeadlineToAdjudicationDays, Literal(duration, datatype=XSD.integer)))

        if d_adj and d_exec:
            duration = (d_exec - d_adj).days
            if duration >= 0:
                self.graph.add((self.tender_uri, TS.durationAdjudicationToExecutionDays, Literal(duration, datatype=XSD.integer)))

        if metadata.caution:
            val = float(metadata.caution) if isinstance(metadata.caution, (int, float)) else metadata.caution
            self.graph.add((self.tender_uri, TS.Has_Caution, Literal(val, datatype=XSD.float)))

        # Single-lot qualifications
        if not is_multilot and metadata.qualifications:
            self.graph.add((self.tender_uri, TS.Has_Qualifications, Literal(metadata.qualifications, datatype=XSD.string)))

        # Multi-lot nodes
        if is_multilot and metadata.lots:
            self._map_lots(metadata.lots)

    # ------------------------------------------------------------------ #
    # Lot mapping                                                          #
    # ------------------------------------------------------------------ #

    def _map_lots(self, lots_data: Dict[str, Any]):
        """Create Lot nodes for each entry in lots_data."""
        for idx, (lot_label, lot_raw) in enumerate(lots_data.items(), start=1):
            lot_uri = get_lot_uri(self.tender_ref, idx)
            self.graph.add((lot_uri, RDF.type, TS.Lots))
            self.graph.add((lot_uri, TS.Has_Lot_ID, Literal(lot_label, datatype=XSD.string)))

            # Parse into LotMetadata (flexible — extra fields allowed)
            if isinstance(lot_raw, dict):
                try:
                    lot = LotMetadata(**lot_raw)
                except Exception:
                    lot = LotMetadata()
            else:
                lot = LotMetadata()

            if lot.description:
                self.graph.add((lot_uri, TS.Has_Lot_Description, Literal(lot.description, datatype=XSD.string)))
            if lot.estimation_dhs is not None:
                self.graph.add((lot_uri, TS.Has_Budget, Literal(float(lot.estimation_dhs), datatype=XSD.float)))
            if lot.caution_provisoire is not None:
                self.graph.add((lot_uri, TS.Has_Caution, Literal(float(lot.caution_provisoire), datatype=XSD.float)))
            if lot.qualifications:
                self.graph.add((lot_uri, TS.Has_Qualifications, Literal(lot.qualifications, datatype=XSD.string)))
            if lot.agrements:
                self.graph.add((lot_uri, TS.Has_Agrements, Literal(lot.agrements, datatype=XSD.string)))
            if lot.prospectus_documents:
                self.graph.add((lot_uri, TS.Has_Prospectus_Documents, Literal(lot.prospectus_documents, datatype=XSD.string)))
            if lot.reunion_details:
                self.graph.add((lot_uri, TS.Has_Reunion_Details, Literal(lot.reunion_details, datatype=XSD.string)))
            if lot.visite_lieux_details:
                self.graph.add((lot_uri, TS.Has_Visite_Details, Literal(lot.visite_lieux_details, datatype=XSD.string)))
            if lot.variante is not None:
                self.graph.add((lot_uri, TS.Has_Variante, Literal(lot.variante, datatype=XSD.boolean)))
            if lot.environmental_considerations:
                self.graph.add((lot_uri, TS.Has_Environmental_Considerations, Literal(lot.environmental_considerations, datatype=XSD.string)))
            if lot.reserved_pme is not None:
                self.graph.add((lot_uri, TS.Reserved_For_PME, Literal(lot.reserved_pme, datatype=XSD.boolean)))

            # Bidirectional link
            self.graph.add((self.tender_uri, TS.Has_Lot, lot_uri))
            self.graph.add((lot_uri, TS.Is_Lot_Of, self.tender_uri))

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
            if product.designation:
                self.graph.add((article_uri, TS.Has_Designation, Literal(product.designation, datatype=XSD.string)))
            if product.quantity is not None:
                val = float(product.quantity) if isinstance(product.quantity, (int, float)) else product.quantity
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
        return self.graph.serialize(format="ntriples")

    def get_turtle(self) -> str:
        return self.graph.serialize(format="turtle")
