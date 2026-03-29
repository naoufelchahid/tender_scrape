import logging
import time
from rdflib import Graph, Namespace, RDF
from pyshacl import validate
from .uri_builder import TS
from .jena_client import JenaClient

logger = logging.getLogger(__name__)

RDF_NS = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


class DataTester:
    def __init__(self, ontology_path: str, shapes_path: str, jena_client: JenaClient = None):
        # Lazy-load: store paths, parse on first use to reduce startup memory
        self._ontology_path = ontology_path
        self._shapes_path = shapes_path
        self._ontology_graph = None
        self._shapes_graph = None
        self.jena = jena_client

    @property
    def ontology_graph(self) -> Graph:
        if self._ontology_graph is None:
            logger.info(f"Lazy-loading ontology from {self._ontology_path}...")
            self._ontology_graph = Graph().parse(self._ontology_path)
            logger.info(f"Ontology loaded: {len(self._ontology_graph)} triples")
        return self._ontology_graph

    @property
    def shapes_graph(self) -> Graph:
        if self._shapes_graph is None:
            logger.info(f"Lazy-loading SHACL shapes from {self._shapes_path}...")
            self._shapes_graph = Graph().parse(self._shapes_path, format="turtle")
            logger.info(f"SHACL shapes loaded: {len(self._shapes_graph)} triples")
        return self._shapes_graph

    def test_tender_graph(self, data_graph: Graph) -> bool:
        """
        Run TDD data tests against a local rdflib Graph.
        Returns True if all checks pass, False otherwise.
        """
        success = True

        # 1. SHACL Validation (local graph)
        logger.info("Running SHACL validation...")
        
        # ═══════════════════════════════════════════════════════════════
        # TIMING INSTRUMENTATION: Measure validation components
        # ═══════════════════════════════════════════════════════════════

        # Time: PyShacl validation
        t0_validation = time.perf_counter()
        conforms, v_graph, v_text = validate(
            data_graph=data_graph,
            shacl_graph=self.shapes_graph,
            inference='none'
        )
        t1_validation = time.perf_counter()
        logger.info(f"[TIMING] PyShacl validation execution: {t1_validation - t0_validation:.3f}s")
        
        print(f"\n[DEBUG] SHACL conforms: {conforms}")

        if not conforms:
            # Time: Parsing and summarizing violations
            t0_parse = time.perf_counter()
            
            # Parse v_text to count violations
            lines = v_text.split('\n')
            violation_count = v_text.count('sh:Violation')
            warning_count = v_text.count('sh:Warning')
            info_count = v_text.count('sh:Info')
            
            # Count constraint types
            constraint_types = {}
            for line in lines:
                if 'MinCountConstraintComponent' in line:
                    constraint_types['MinCount'] = constraint_types.get('MinCount', 0) + 1
                elif 'DatatypeConstraintComponent' in line:
                    constraint_types['Datatype'] = constraint_types.get('Datatype', 0) + 1
                elif 'SPARQLConstraintComponent' in line:
                    constraint_types['SPARQL'] = constraint_types.get('SPARQL', 0) + 1
                elif 'ClassConstraintComponent' in line:
                    constraint_types['Class'] = constraint_types.get('Class', 0) + 1
                elif 'PatternConstraintComponent' in line:
                    constraint_types['Pattern'] = constraint_types.get('Pattern', 0) + 1
            
            t1_parse = time.perf_counter()
            logger.info(f"[TIMING] Violation parsing: {t1_parse - t0_parse:.3f}s")
            
            # Time: Logging summary (instead of full text)
            t0_log = time.perf_counter()
            
            summary = f"""SHACL Validation Failed - Summary:
  Total Violations: {violation_count}
  Total Warnings: {warning_count}
  Total Info: {info_count}
  
  Constraint Types:
"""
            for ctype, count in sorted(constraint_types.items(), key=lambda x: x[1], reverse=True):
                summary += f"    {ctype}: {count}\n"
            
            summary += f"\n  Validation output length: {len(v_text)} chars ({len(lines)} lines)"
            
            # Log first 50 lines as sample
            sample_lines = lines[:50]
            summary += f"\n\n  First 50 lines (sample):\n" + '\n'.join(sample_lines)
            
            logger.error(summary)
            
            # OPTIONAL: Save full validation output to file for deep analysis
            # with open('/tmp/shacl_validation_full.txt', 'w') as f:
            #     f.write(v_text)
            # logger.info("Full validation output saved to /tmp/shacl_validation_full.txt")
            
            t1_log = time.perf_counter()
            logger.info(f"[TIMING] Logging summary: {t1_log - t0_log:.3f}s")
            
            # COMPARISON: Time the OLD way (logging full v_text)
            # t0_old = time.perf_counter()
            # logger.error(f"SHACL Validation Failed:\n{v_text}")  # OLD WAY
            # t1_old = time.perf_counter()
            # logger.info(f"[TIMING] Logging full v_text (OLD): {t1_old - t0_old:.3f}s")
            
            if "sh:Violation" in v_text:
                print("[DEBUG] SHACL has Violations")
                success = False
            else:
                logger.warning("SHACL Warnings/Info found, but proceeding.")

        # 2. Manual Logical Assertions
        t0_logical = time.perf_counter()
        try:
            self._assert_logical_consistency(data_graph)
            logger.info("Logical consistency assertions passed.")
            print("[DEBUG] Logical consistency assertions passed.")
        except AssertionError as e:
            logger.error(f"Logical Consistency Failed: {str(e)}")
            print(f"[DEBUG] Logical Consistency Failed: {str(e)}")
            success = False
        t1_logical = time.perf_counter()
        logger.info(f"[TIMING] Logical consistency checks: {t1_logical - t0_logical:.3f}s")

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
        """Custom assertions for enrichment graph consistency."""
        # Every Bordereau must have at least one Article
        for bordereau in g.subjects(RDF.type, TS.Bordereaux):
            articles = list(g.objects(bordereau, TS.Has_Article))
            if not articles:
                msg = f"Bordereau {bordereau} has no Articles (ts:Has_Article)"
                logger.error(msg)
                raise AssertionError(msg)

        # Child chunk nodes must have an identifier (warn only — fallback always set in mapper)
        for chunk_type in [TS.TenderSpecifications, TS.TenderReglement]:
            for chunk in g.subjects(RDF.type, chunk_type):
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
