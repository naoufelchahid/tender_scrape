import logging
from rdflib import Graph, Namespace
from pyshacl import validate
from .uri_builder import TS

logger = logging.getLogger(__name__)

class DataTester:
    def __init__(self, ontology_path: str, shapes_path: str):
        self.ontology_graph = Graph().parse(ontology_path, format="turtle")
        self.shapes_graph = Graph().parse(shapes_path, format="turtle")

    def test_tender_graph(self, data_graph: Graph) -> bool:
        """
        Run the TDD data test suite. 
        Returns True if passed (Green), False otherwise (Red).
        """
        success = True
        
        # 1. SHACL Validation
        logger.info("Running SHACL validation...")
        conforms, v_graph, v_text = validate(
            data_graph=data_graph,
            shacl_graph=self.shapes_graph,
            ont_graph=self.ontology_graph,
            inference='rdfs'
        )
        
        if not conforms:
            logger.error(f"SHACL Validation Failed:\n{v_text}")
            # Check for severity=Violation specifically
            if "sh:Violation" in v_text:
                success = False
            else:
                logger.warning("SHACL Warnings/Info found, but proceeding.")

        # 2. Manual Logical Assertions (TDD logic)
        try:
            self._assert_logical_consistency(data_graph)
            logger.info("Logical consistency assertions passed.")
        except AssertionError as e:
            logger.error(f"Logical Consistency Failed: {str(e)}")
            success = False

        return success

    def _assert_logical_consistency(self, g: Graph):
        """Custom assertions that go beyond SHACL limitations."""
        
        # Check for Tender budget if cat is works/supplies
        # (This is just an example of TDD-style data testing)
        for tender in g.subjects(Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#").type, TS.Tenders):
            budget = g.value(tender, TS.Has_Budget)
            if budget is not None and float(budget) < 0:
                raise AssertionError(f"Tender {tender} has negative budget: {budget}")
            
            # Ensure it has an object
            obj = g.value(tender, TS.Has_Object)
            if not obj:
                raise AssertionError(f"Tender {tender} is missing Has_Object property")

            # Ensure it has a Buyer
            buyer = g.value(tender, TS.Launched_by)
            if not buyer:
                raise AssertionError(f"Tender {tender} is not linked to any Buyer")

        # Check Articles if Bordereau exists
        for article in g.subjects(Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#").type, TS.Articles):
            qty = g.value(article, TS.Has_quantity)
            if qty is not None and float(qty) <= 0:
                logger.warning(f"Article {article} has zero or negative quantity: {qty}")
