import logging
from rdflib import Graph, Namespace, RDF
from pyshacl import validate
from .uri_builder import TS
from .jena_client import JenaClient

logger = logging.getLogger(__name__)

RDF_NS = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


class DataTester:
    def __init__(self, ontology_path: str, shapes_path: str, jena_client: JenaClient = None):
        self.ontology_graph = Graph().parse(ontology_path)
        self.shapes_graph = Graph().parse(shapes_path, format="turtle")
        self.jena = jena_client

    def test_tender_graph(self, data_graph: Graph) -> bool:
        """
        Run TDD data tests against a local rdflib Graph.
        Returns True if all checks pass, False otherwise.
        """
        success = True

        # 1. SHACL Validation (local graph)
        logger.info("Running SHACL validation...")
        # Avoid pyshacl deep_clone hanging by manually adding ontology to data_graph
        # Exclude sample 'Instance_' entities mixed in the ontology to prevent false SHACL validation errors.
        combined_graph = Graph()
        for t in data_graph: combined_graph.add(t)
        for s, p, o in self.ontology_graph:
            if "Instance_" in str(s):
                continue
            combined_graph.add((s, p, o))

        conforms, v_graph, v_text = validate(
            data_graph=combined_graph,
            shacl_graph=self.shapes_graph,
            inference='none'
        )
        print(f"\n[DEBUG] SHACL conforms: {conforms}")

        if not conforms:
            logger.error(f"SHACL Validation Failed:\n{v_text}")
            if "sh:Violation" in v_text:
                print("[DEBUG] SHACL has Violations")
                success = False
            else:
                logger.warning("SHACL Warnings/Info found, but proceeding.")

        # 2. Manual Logical Assertions
        try:
            self._assert_logical_consistency(data_graph)
            logger.info("Logical consistency assertions passed.")
            print("[DEBUG] Logical consistency assertions passed.")
        except AssertionError as e:
            logger.error(f"Logical Consistency Failed: {str(e)}")
            print(f"[DEBUG] Logical Consistency Failed: {str(e)}")
            success = False

        print(f"[DEBUG] Final success: {success}")
        return success

    def validate_tender_in_jena(self, tender_iri: str) -> bool:
        """
        Run quality gate checks against the Jena KB for an already-ingested tender.
        Requires a JenaClient to be injected.
        """
        if not self.jena:
            logger.warning("No Jena client configured — skipping KB quality gates.")
            return True

        checks = {
            "has_specification": self.jena.check_tender_has_spec(tender_iri),
            "has_administrative": self.jena.check_tender_has_admin(tender_iri),
            "has_bordereau": self.jena.check_tender_has_bordereau(tender_iri),
            "bordereau_has_articles": self.jena.check_bordereau_has_articles(tender_iri),
        }

        all_pass = True
        for check_name, result in checks.items():
            if result:
                logger.info(f"Quality gate PASSED: {check_name}")
            else:
                logger.error(f"Quality gate FAILED: {check_name} for tender {tender_iri}")
                all_pass = False

        return all_pass

    def _assert_logical_consistency(self, g: Graph):
        """Custom assertions beyond SHACL."""
        for tender in g.subjects(RDF.type, TS.Tenders):
            budget = g.value(tender, TS.Has_Budget)
            if budget is not None and float(budget) < 0:
                msg = f"Tender {tender} has negative budget: {budget}"
                logger.error(msg)
                raise AssertionError(msg)

            obj = g.value(tender, TS.Has_Object)
            if not obj:
                msg = f"Tender {tender} is missing Has_Object property"
                logger.error(msg)
                raise AssertionError(msg)

            buyer = g.value(tender, TS.Launched_by)
            if not buyer:
                msg = f"Tender {tender} is not linked to any Buyer"
                logger.error(msg)
                raise AssertionError(msg)

        # Check chunk nodes have identifiers
        for chunk_type in [TS.TenderSpecifications, TS.TenderReglement]:
            for chunk in g.subjects(RDF.type, chunk_type):
                # parent nodes (spec/RC) won't have Has_Chunk_Identifier; chunk nodes will
                # We only warn if Has_Chunk is present (meaning it is a child chunk node)
                is_child_chunk = any(True for _ in g.subjects(TS.Has_Chunk, chunk))
                if is_child_chunk:
                    identifier = g.value(chunk, TS.Has_Chunk_Identifier)
                    if not identifier:
                        logger.warning(f"Chunk node {chunk} is missing Has_Chunk_Identifier")

        # Check articles
        for article in g.subjects(RDF.type, TS.Articles):
            qty = g.value(article, TS.Has_quantity)
            if qty is not None and float(qty) <= 0:
                logger.warning(f"Article {article} has zero or negative quantity: {qty}")
