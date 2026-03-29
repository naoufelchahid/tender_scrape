import pytest
from rdflib import RDF, XSD, Literal
from src.json_to_rdf import JsonToRdfMapper
from src.models import AvisMetadata, ProductChunkMetadata, SpecificationMetadata, AdministrativeMetadata, ChunkItem
from src.uri_builder import TS, get_spec_chunk_uri, get_admin_chunk_uri, get_lot_uri


def test_map_avis_basic():
    """map_avis() adds supplemental properties but NOT type, buyer, category, or region."""
    mapper = JsonToRdfMapper("AO_TEST_001")
    metadata = AvisMetadata(
        objet="Test Tender Object",
        budget=1000000.50,
        contact="The Big Buyer",
        location="Casablanca",
        mode_de_soumission="Electronique",
        mode_de_passation="Appel d'offres ouvert",
        lot_number="0",
    )

    mapper.map_avis(metadata)
    g = mapper.graph

    tender = mapper.tender_uri

    # Core enrichment properties are set
    assert (tender, TS.Has_Object, Literal("Test Tender Object", datatype=XSD.string)) in g
    assert (tender, TS.Has_Budget, Literal(1000000.50, datatype=XSD.float)) in g
    assert (tender, TS.Has_Mode_Soumission, Literal("Electronique", datatype=XSD.string)) in g
    assert (tender, TS.Has_Mode_Passation, Literal("Appel d'offres ouvert", datatype=XSD.string)) in g
    assert (tender, TS.Has_Multilot, Literal(False, datatype=XSD.boolean)) in g

    # Core tender data owned by migration_container must NOT be re-created
    assert (tender, RDF.type, TS.Tenders) not in g
    assert len(list(g.objects(tender, TS.Launched_by))) == 0
    assert len(list(g.objects(tender, TS.Has_Category))) == 0
    assert len(list(g.objects(tender, TS.Is_Located_In))) == 0
    # Deadline and launch date are already in KB from migration — not re-added
    assert len(list(g.objects(tender, TS.Has_Deadline))) == 0
    assert len(list(g.objects(tender, TS.hasLaunchDate))) == 0


def test_map_avis_multilot():
    """Multi-lot tenders create Lot nodes linked to the tender."""
    mapper = JsonToRdfMapper("AO_MULTILOT_001")
    metadata = AvisMetadata(
        objet="Multi-lot tender",
        contact="Buyer Org",
        lot_number="2",
        lots={
            "Lot 1": {"description": "Génie civil", "estimation_dhs": 500000.0},
            "Lot 2": {"description": "Equipements", "estimation_dhs": 300000.0},
        }
    )

    mapper.map_avis(metadata)
    g = mapper.graph

    tender = mapper.tender_uri
    assert (tender, TS.Has_Multilot, Literal(True, datatype=XSD.boolean)) in g

    lots = list(g.objects(tender, TS.Has_Lot))
    assert len(lots) == 2

    lot_1_uri = get_lot_uri("AO_MULTILOT_001", 1)
    assert (lot_1_uri, RDF.type, TS.Lots) in g
    assert (lot_1_uri, TS.Has_Lot_Description, Literal("Génie civil", datatype=XSD.string)) in g


def test_map_products():
    mapper = JsonToRdfMapper("AO_TEST_002")
    products = [
        ProductChunkMetadata(designation="Product A", quantity=10, unit="unit", **{"product header": "Section 1"}),
        ProductChunkMetadata(designation="Product B", quantity=5.5, unit="kg"),
    ]

    mapper.map_products(products, bordereau_content="Full BPU text here")
    g = mapper.graph

    bordereau = next(g.objects(mapper.tender_uri, TS.Has_Bordereau))
    assert (bordereau, RDF.type, TS.Bordereaux) in g
    assert (bordereau, TS.Has_Bordereau_Content, Literal("Full BPU text here", datatype=XSD.string)) in g

    articles = list(g.objects(bordereau, TS.Has_Article))
    assert len(articles) == 2

    art_a = [a for a in articles if (a, TS.Has_Designation, Literal("Product A", datatype=XSD.string)) in g][0]
    assert (art_a, TS.Has_quantity, Literal(10.0, datatype=XSD.float)) in g
    assert (art_a, TS.Has_Product_Header, Literal("Section 1", datatype=XSD.string)) in g


def test_map_specification_chunk_as_node():
    """Each spec chunk becomes a new TenderSpecifications node linked via Has_Chunk."""
    mapper = JsonToRdfMapper("AO_TEST_SPEC_001")

    chunks = [
        ChunkItem(content="CPS article 1 text", metadata=SpecificationMetadata(title="Article 1 - Objet", chapter="Chapitre I")),
        ChunkItem(content="CPS article 2 text", metadata=SpecificationMetadata(title="Article 2 - Conditions", chapter="Chapitre I")),
        ChunkItem(content="CPS article 3 no header", metadata=SpecificationMetadata(title=None, chapter="Chapitre II")),
    ]
    vector_refs = [
        "s3://bucket/vector_store/AO_TEST_SPEC_001/specification_chunk_0_vector.json",
        "s3://bucket/vector_store/AO_TEST_SPEC_001/specification_chunk_1_vector.json",
        "",  # empty — no vector for chunk 2
    ]

    mapper.map_specification(chunks, "s3://bucket/spec.json", chunk_vector_keys=vector_refs)
    g = mapper.graph

    # Parent spec node
    spec_uri = next(g.objects(mapper.tender_uri, TS.Has_specifications))
    assert (spec_uri, RDF.type, TS.TenderSpecifications) in g

    # Chunk nodes linked via Has_Chunk
    chunk_uris = list(g.objects(spec_uri, TS.Has_Chunk))
    assert len(chunk_uris) == 3

    # Chunk 0: has identifier and vector ref
    c0 = get_spec_chunk_uri("AO_TEST_SPEC_001", 0)
    assert (c0, RDF.type, TS.TenderSpecifications) in g
    assert (c0, TS.Has_Chunk_Identifier, Literal("Article 1 - Objet", datatype=XSD.string)) in g
    assert (c0, TS.Has_Vector_Key, Literal(vector_refs[0], datatype=XSD.string)) in g
    assert (spec_uri, TS.Has_Chunk, c0) in g

    # Chunk 2 (no title): fallback identifier
    c2 = get_spec_chunk_uri("AO_TEST_SPEC_001", 2)
    assert (c2, TS.Has_Chunk_Identifier, Literal("chunk_2", datatype=XSD.string)) in g


def test_map_administrative_chunk_as_node():
    """Each admin chunk becomes a new TenderReglement node linked via Has_Chunk."""
    mapper = JsonToRdfMapper("AO_TEST_ADMIN_001")

    chunks = [
        ChunkItem(content="RC article 1 text", metadata=AdministrativeMetadata(title="Article 1 - Définitions")),
    ]
    vector_refs = ["s3://bucket/vector_store/AO_TEST_ADMIN_001/administrative_chunk_0_vector.json"]

    mapper.map_administrative(chunks, "s3://bucket/rc.json", chunk_vector_keys=vector_refs)
    g = mapper.graph

    rc_uri = next(g.objects(mapper.tender_uri, TS.Has_Reglement_Consultation))
    assert (rc_uri, RDF.type, TS.TenderReglement) in g

    c0 = get_admin_chunk_uri("AO_TEST_ADMIN_001", 0)
    assert (c0, RDF.type, TS.TenderReglement) in g
    assert (c0, TS.Has_Chunk_Identifier, Literal("Article 1 - Définitions", datatype=XSD.string)) in g
    assert (c0, TS.Has_Vector_Key, Literal(vector_refs[0], datatype=XSD.string)) in g
    assert (rc_uri, TS.Has_Chunk, c0) in g


def test_extract_nested_products():
    """ProductChunkMetadata.extract_nested_products handles nested product_1/product_2 keys."""
    raw_meta = {
        "type": "product",
        "product header": "Section A",
        "product_1": {"designation": "Béton", "quantity": "10", "unit": "M3"},
        "product_2": {"designation": "Acier", "quantity": "500", "unit": "KG"},
    }
    products = ProductChunkMetadata.extract_nested_products(raw_meta)
    assert len(products) == 2
    designations = {p.designation for p in products}
    assert "Béton" in designations
    assert "Acier" in designations
