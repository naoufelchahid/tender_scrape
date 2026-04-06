"""SHACL validation and logical assertions for result RDF graphs."""
import logging
from pathlib import Path

from rdflib import Graph, RDF
from pyshacl import validate

from uri_builder import TS

logger = logging.getLogger(__name__)


class ShaclValidator:
    def __init__(self, shapes_path: str):
        self._shapes_path = shapes_path
        self._shapes_graph = None

    @property
    def shapes_graph(self) -> Graph:
        if self._shapes_graph is None:
            logger.info(f"Loading SHACL shapes from {self._shapes_path}")
            self._shapes_graph = Graph().parse(self._shapes_path, format="turtle")
        return self._shapes_graph

    def validate(self, data_graph: Graph) -> bool:
        """Run SHACL + logical assertions. Returns True if all pass."""
        ok = True

        # 1. SHACL validation
        conforms, _, v_text = validate(
            data_graph=data_graph,
            shacl_graph=self.shapes_graph,
            inference='none',
        )
        if not conforms and "sh:Violation" in v_text:
            logger.error(f"SHACL validation failed:\n{v_text[:500]}")
            ok = False

        # 2. Logical assertions
        try:
            self._assert_logical_consistency(data_graph)
        except AssertionError as e:
            logger.error(f"Logical consistency failed: {e}")
            ok = False

        return ok

    def _assert_logical_consistency(self, g: Graph) -> None:
        """Custom logical assertions for result graphs."""
        for result_uri in g.subjects(RDF.type, TS.TenderResults):
            # Must have at least one Is_Winner_Bid
            winners = list(g.objects(result_uri, TS.Is_Winner_Bid))
            if not winners:
                raise AssertionError(
                    f"TenderResults {result_uri} has no Is_Winner_Bid"
                )

            # Winner bid amount must be > 0
            for winner_bid in winners:
                amount = g.value(winner_bid, TS.Has_Bid_Amount)
                if amount is not None and float(amount) <= 0:
                    raise AssertionError(
                        f"Winner bid {winner_bid} has amount <= 0: {amount}"
                    )

                # Winner bid must have a contractor
                contractor = g.value(winner_bid, TS.Is_Bid_of)
                if contractor is None:
                    raise AssertionError(
                        f"Winner bid {winner_bid} has no Is_Bid_of contractor"
                    )
