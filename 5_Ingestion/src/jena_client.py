import logging
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests to Jena (seconds)
DEFAULT_TIMEOUT = 30


class JenaClient:
    """
    Client for interacting with Apache Jena Fuseki via direct HTTP or MCP tools.

    Supports two execution modes:
    1. Direct HTTP: Makes SPARQL queries/updates directly to Jena Fuseki's REST API.
       This allows the container to run standalone without MCP tool injection.
    2. DI override: Accepts callable functions for DI/testing (e.g., MagicMock in tests).
       Priority: injected function > HTTP fallback.

    HTTP endpoints:
    - Query: POST {endpoint}/{dataset}/sparql (Content-Type: application/sparql-query)
    - Update: POST {endpoint}/{dataset}/update (Content-Type: application/sparql-update)
    """

    TS_PREFIX = "http://www.tenderintelligence.io/ontology/tender-structure#"
    PREFIXES = f"""
PREFIX ts: <{TS_PREFIX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
""".strip()

    def __init__(self, dataset: str = "tenders",
                 sparql_query_fn=None, sparql_update_fn=None):
        """
        Args:
            dataset: Jena dataset name.
            sparql_query_fn: Required Callable (query: str, dataset: str) -> dict.
            sparql_update_fn: Required Callable (update: str, dataset: str) -> dict.
        """
        if sparql_query_fn is None or sparql_update_fn is None:
            logger.error("JenaClient requires sparql_query_fn and sparql_update_fn for Dependency Injection.")
            
        self.dataset = dataset
        self._query_fn = sparql_query_fn
        self._update_fn = sparql_update_fn

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def find_tender_by_ref(self, tender_ref: str) -> Optional[str]:
        """
        Return the tender IRI (as string) for a given tender reference.
        Returns None on failure or if not found.
        """
        try:
            query = self._build_find_tender_query(tender_ref)
            result = self._execute_query(query)
            if result and result.get("boolean"):
                tender_uri = f"{self.TS_PREFIX}Tender_{tender_ref}"
                logger.info(f"Found tender in KB: {tender_uri}")
                return tender_uri
            
            logger.warning(f"Tender with reference '{tender_ref}' not found in Jena KB.")
            return None
        except Exception as e:
            logger.error(f"Error finding tender by ref: {e}")
            return None

    def insert_triples(self, turtle_data: str) -> bool:
        """Execute a SPARQL INSERT DATA with turtle-formatted triples."""
        try:
            update = self._build_insert_update(turtle_data)
            return self._execute_update(update)
        except Exception as e:
            logger.error(f"Error inserting triples: {e}")
            return False

    def sparql_ask(self, query: str) -> bool:
        """Run a SPARQL ASK query and return True/False."""
        try:
            result = self._execute_query(query)
            if result:
                return result.get("boolean", False)
            return False
        except Exception as e:
            logger.error(f"Error executing SPARQL ASK: {e}")
            return False

    def check_tender_has_spec(self, tender_iri: str) -> bool:
        """Quality gate: tender must have a specification node."""
        query = f"""
{self.PREFIXES}
ASK {{
  <{tender_iri}> ts:Has_specifications ?spec .
}}
"""
        return self.sparql_ask(query)

    def check_tender_has_admin(self, tender_iri: str) -> bool:
        """Quality gate: tender must have an administrative (reglement) node."""
        query = f"""
{self.PREFIXES}
ASK {{
  <{tender_iri}> ts:Has_Reglement_Consultation ?rc .
}}
"""
        return self.sparql_ask(query)

    def check_tender_has_bordereau(self, tender_iri: str) -> bool:
        """Quality gate: tender must have a bordereau node."""
        query = f"""
{self.PREFIXES}
ASK {{
  <{tender_iri}> ts:Has_Bordereau ?b .
}}
"""
        return self.sparql_ask(query)

    def check_bordereau_has_articles(self, tender_iri: str) -> bool:
        """Quality gate: the bordereau linked to a tender must have ≥1 article."""
        query = f"""
{self.PREFIXES}
ASK {{
  <{tender_iri}> ts:Has_Bordereau ?b .
  ?b ts:Has_Article ?a .
}}
"""
        return self.sparql_ask(query)

    # ------------------------------------------------------------------ #
    # Query/Update builders (Private for DI/Testing)                      #
    # ------------------------------------------------------------------ #

    def _build_find_tender_query(self, tender_ref: str) -> str:
        tender_uri = f"{self.TS_PREFIX}Tender_{tender_ref}"
        return f"""
{self.PREFIXES}
ASK {{
  <{tender_uri}> a ts:Tenders .
}}
""".strip()

    def _build_insert_update(self, turtle_data: str) -> str:
        return f"""
{self.PREFIXES}
INSERT DATA {{
{turtle_data}
}}
""".strip()

    # ------------------------------------------------------------------ #
    # Internal execution helpers (DI ONLY)                                #
    # ------------------------------------------------------------------ #

    def _execute_query(self, query: str) -> Optional[dict]:
        """Execute query via injected function. Returns None on failure."""
        if self._query_fn is None:
            logger.error("No sparql_query_fn provided for DI.")
            return None
        try:
            return self._query_fn(query=query, dataset=self.dataset)
        except Exception as e:
            logger.error(f"SPARQL query via injected function failed: {e}")
            return None

    def _execute_update(self, update: str) -> bool:
        """Execute update via injected function. Returns False on failure."""
        if self._update_fn is None:
            logger.error("No sparql_update_fn provided for DI.")
            return False
        try:
            self._update_fn(update=update, dataset=self.dataset)
            return True
        except Exception as e:
            logger.error(f"SPARQL update via injected function failed: {e}")
            return False
