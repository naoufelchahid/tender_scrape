import logging
import owlrl
from rdflib import Graph
from owlapy.iri import IRI
from owlapy.ontology_manager import OntoManager
from owlapy.owl_reasoner import StructuralReasoner

logger = logging.getLogger(__name__)

class OwlReasoner:
    def __init__(self, ontology_path: str):
        self.ontology_path = ontology_path
        # Setup owlapy for TBox checks
        self.manager = OntoManager()
        self.onto = self.manager.load_ontology(IRI.create(f"file://{ontology_path}"))
        self.reasoner = StructuralReasoner(self.onto)

    def infer_and_materialize(self, data_graph: Graph) -> Graph:
        """
        Perform ABox inference using OWL-RL profile.
        Materializes inferred triples into the graph.
        """
        logger.info("Performing ABox materialization (OWL-RL)...")
        # DeductiveClosure expands the graph in-place
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(data_graph)
        return data_graph

    def check_structural_consistency(self, data_graph: Graph):
        """
        Example: Verify that entities in data_graph belong to valid classes in TBox.
        """
        # This is more of a validation step. 
        # For now, we mainly rely on materialization.
        pass
