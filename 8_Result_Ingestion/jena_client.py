"""Jena Fuseki client for SPARQL queries and updates."""
import logging
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from uri_builder import TS, slugify

logger = logging.getLogger(__name__)

PREFIXES = """
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
""".strip()

TIMEOUT = 30


class JenaClient:
    def __init__(self, endpoint: str, dataset: str,
                 username: str = "", password: str = ""):
        self.endpoint = endpoint.rstrip("/")
        self.dataset = dataset
        self.auth = HTTPBasicAuth(username, password) if username else None

    @property
    def _query_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/sparql"

    @property
    def _update_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/update"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def find_tender_iri(self, tender_ref: str) -> Optional[str]:
        """Return full IRI of tender if it exists, else None."""
        safe = slugify(tender_ref)
        uri = f"{TS}Tender_{safe}"
        query = f"""{PREFIXES}
ASK {{ <{uri}> a ts:Tenders . }}"""
        result = self._ask(query)
        if result:
            logger.info(f"Found tender: {uri}")
            return uri
        logger.warning(f"Tender '{tender_ref}' not found in Jena KB")
        return None

    def insert_triples(self, ntriples_data: str) -> bool:
        """INSERT DATA with N-Triples payload."""
        update = f"""{PREFIXES}
INSERT DATA {{
{ntriples_data}
}}"""
        return self._update(update)

    def check_tender_has_result(self, tender_iri: str) -> bool:
        query = f"""{PREFIXES}
ASK {{ <{tender_iri}> ts:Is_Opened ?r . }}"""
        return self._ask(query)

    def check_result_has_bids(self, tender_iri: str) -> bool:
        query = f"""{PREFIXES}
ASK {{
  <{tender_iri}> ts:Is_Opened ?r .
  ?r ts:Has_Bid ?b .
}}"""
        return self._ask(query)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _ask(self, query: str) -> bool:
        try:
            resp = requests.post(
                self._query_url,
                data={"query": query},
                auth=self.auth,
                headers={"Accept": "application/sparql-results+json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("boolean", False)
        except Exception as e:
            logger.error(f"SPARQL ASK failed: {e}")
            return False

    def _update(self, update: str) -> bool:
        try:
            resp = requests.post(
                self._update_url,
                data={"update": update},
                auth=self.auth,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"SPARQL UPDATE failed: {e}")
            return False
