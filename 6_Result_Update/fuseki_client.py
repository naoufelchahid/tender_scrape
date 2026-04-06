"""Fuseki SPARQL client for querying tenders pending results."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

PREFIXES = """
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
""".strip()

TIMEOUT = 30


class FusekiClient:
    def __init__(self, endpoint: str, dataset: str,
                 username: str = "", password: str = ""):
        self.endpoint = endpoint.rstrip("/")
        self.dataset = dataset
        self.auth = HTTPBasicAuth(username, password) if username else None

    @property
    def _query_url(self) -> str:
        return f"{self.endpoint}/{self.dataset}/sparql"

    def get_pending_tenders(self) -> List[Dict[str, Optional[str]]]:
        """Query Fuseki for tenders past deadline without results.

        Returns list of dicts with keys: ref, original_ref, buyer, search_ref.
        search_ref is the reference to use in marchespublics.gov.ma search.
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

        query = f"""{PREFIXES}
SELECT ?tender ?ref ?originalRef ?buyer WHERE {{
  ?tender a ts:Tenders ;
          ts:Ref ?ref .
  ?tender ts:Has_Deadline ?deadline .
  FILTER(?deadline < "{yesterday}"^^xsd:dateTime)
  FILTER NOT EXISTS {{ ?tender ts:Is_Result "true"^^xsd:boolean }}
  OPTIONAL {{ ?tender ts:Has_Original_Reference ?originalRef }}
  OPTIONAL {{ ?tender ts:Launched_by ?buyerNode .
             ?buyerNode rdfs:label ?buyer }}
}}"""

        try:
            resp = requests.post(
                self._query_url,
                data={"query": query},
                auth=self.auth,
                headers={"Accept": "application/sparql-results+json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
        except Exception as e:
            logger.error(f"SPARQL query failed: {e}")
            return []

        tenders = []
        for b in bindings:
            ref = b["ref"]["value"]
            original_ref = b.get("originalRef", {}).get("value")
            buyer = b.get("buyer", {}).get("value")

            # Derive search_ref: prefer originalRef, fallback to stripping initials
            if original_ref:
                search_ref = original_ref
            elif "_" in ref:
                search_ref = ref.rsplit("_", 1)[0]
            else:
                search_ref = ref

            tenders.append({
                "ref": ref,
                "original_ref": original_ref,
                "buyer": buyer,
                "search_ref": search_ref,
            })

        logger.info(f"Found {len(tenders)} tenders pending results")
        return tenders
