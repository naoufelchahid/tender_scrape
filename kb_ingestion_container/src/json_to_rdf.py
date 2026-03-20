from rdflib import Graph, Literal, RDF, RDFS, XSD
from typing import List, Dict, Any
from .models import AvisMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from .uri_builder import (
    get_tender_uri, get_buyer_uri, get_bordereau_uri, 
    get_article_uri, get_specification_uri, get_reglement_uri,
    get_region_uri, TS, REGIONS, ACTIVITY
)

class JsonToRdfMapper:
    def __init__(self, tender_ref: str):
        self.tender_ref = tender_ref
        self.tender_uri = get_tender_uri(tender_ref)
        self.graph = Graph()
        self.graph.bind("ts", TS)
        self.graph.bind("regions", REGIONS)
        self.graph.bind("activity", ACTIVITY)

    def map_avis(self, metadata: AvisMetadata):
        """Map Avis metadata to the existing Tender node and its Buyer."""
        # The Tender node is expected to exist, we enrich it.
        self.graph.add((self.tender_uri, RDF.type, TS.Tenders))
        
        if metadata.objet:
            self.graph.add((self.tender_uri, TS.Has_Object, Literal(metadata.objet, datatype=XSD.string)))
        
        if metadata.budget:
            # Handle float or string
            val = float(metadata.budget) if isinstance(metadata.budget, (int, float)) else metadata.budget
            self.graph.add((self.tender_uri, TS.Has_Budget, Literal(val, datatype=XSD.float)))
        
        if metadata.deadline:
            self.graph.add((self.tender_uri, TS.Has_Deadline, Literal(metadata.deadline, datatype=XSD.string)))
            
        if metadata.caution:
            val = float(metadata.caution) if isinstance(metadata.caution, (int, float)) else metadata.caution
            self.graph.add((self.tender_uri, TS.Has_Caution, Literal(val, datatype=XSD.float)))

        if metadata.contact:
            # Create Buyer
            buyer_uri = get_buyer_uri(metadata.contact)
            self.graph.add((buyer_uri, RDF.type, TS.Buyers))
            self.graph.add((buyer_uri, RDFS.label, Literal(metadata.contact, datatype=XSD.string)))
            
            # Link Tender -> Buyer
            self.graph.add((self.tender_uri, TS.Launched_by, buyer_uri))
            self.graph.add((buyer_uri, TS.Launched, self.tender_uri))

        if metadata.location:
            # Map location string to region hierarchy (placeholder logic)
            region_uri = get_region_uri(metadata.location)
            self.graph.add((self.tender_uri, TS.Is_Located_In, region_uri))

    def map_products(self, products: List[ProductChunkMetadata]):
        """Map a list of products to a Bordereau and Articles."""
        if not products:
            return

        bordereau_uri = get_bordereau_uri(self.tender_ref)
        self.graph.add((bordereau_uri, RDF.type, TS.Bordereaux))
        
        # Link Tender <-> Bordereau
        self.graph.add((self.tender_uri, TS.Has_Bordereau, bordereau_uri))
        self.graph.add((bordereau_uri, TS.Is_Bordereau_of, self.tender_uri))

        for i, product in enumerate(products):
            article_uri = get_article_uri(self.tender_ref, i)
            self.graph.add((article_uri, RDF.type, TS.Articles))
            
            if product.designation:
                self.graph.add((article_uri, TS.Has_Designation, Literal(product.designation, datatype=XSD.string)))
            
            if product.quantity:
                val = float(product.quantity) if isinstance(product.quantity, (int, float)) else product.quantity
                self.graph.add((article_uri, TS.Has_quantity, Literal(val, datatype=XSD.float)))
                
            if product.unit:
                self.graph.add((article_uri, TS.Has_Unit, Literal(product.unit, datatype=XSD.string)))

            # Link Bordereau <-> Article
            self.graph.add((bordereau_uri, TS.Has_Article, article_uri))
            self.graph.add((article_uri, TS.Is_Article_of, bordereau_uri))

    def map_specification(self, chunks: List[ChunkItem], s3_uri: str):
        """Map specification chunks to its document node."""
        spec_uri = get_specification_uri(self.tender_ref)
        self.graph.add((spec_uri, RDF.type, TS.TenderSpecifications))
        
        # We store the reference to the source doc in S3
        self.graph.add((spec_uri, TS.Has_CPS_Doc, Literal(s3_uri, datatype=XSD.string)))
        
        # Link Tender <-> Specification
        self.graph.add((self.tender_uri, TS.Has_specifications, spec_uri))
        self.graph.add((spec_uri, TS.Is_specifications_of, self.tender_uri))

    def map_administrative(self, chunks: List[ChunkItem], s3_uri: str):
        """Map administrative chunks to its document node."""
        reg_uri = get_reglement_uri(self.tender_ref)
        self.graph.add((reg_uri, RDF.type, TS.TenderReglement))
        
        # We store the reference to the source doc in S3
        self.graph.add((reg_uri, TS.Has_RC_Doc, Literal(s3_uri, datatype=XSD.string)))
        
        # Link Tender <-> Reglement
        self.graph.add((self.tender_uri, TS.Has_Reglement_Consultation, reg_uri))
        self.graph.add((reg_uri, TS.Is_Reglement_Consultation_Of, self.tender_uri))

    def get_ntriples(self) -> str:
        return self.graph.serialize(format="ntriples")
    
    def get_turtle(self) -> str:
        return self.graph.serialize(format="turtle")
