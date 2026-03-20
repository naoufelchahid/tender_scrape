import logging
import requests
from requests_aws4auth import AWS4Auth
import boto3
from rdflib import Graph
from .config import settings

logger = logging.getLogger(__name__)

class NeptuneClient:
    def __init__(self):
        self.config = settings
        self.endpoint = settings.NEPTUNE_ENDPOINT
        self.port = settings.NEPTUNE_PORT
        self.region = settings.AWS_REGION
        self.url = f"https://{self.endpoint}:{self.port}/sparql"
        
        self.auth = None
        if settings.NEPTUNE_USE_IAM:
            credentials = boto3.Session().get_credentials()
            self.auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                self.region,
                'neptune-db',
                session_token=credentials.token
            )

    def execute_update(self, sparql_query: str):
        """Execute a SPARQL UPDATE query."""
        try:
            # Handle SSL verification for local tunnels
            verify = True
            if self.endpoint in ["127.0.0.1", "localhost"]:
                verify = False
                # Disable insecure request warnings for local dev
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            headers = {'Content-Type': 'application/sparql-update'}
            if self.config.NEPTUNE_REAL_HOST:
                headers['Host'] = self.config.NEPTUNE_REAL_HOST
            
            response = requests.post(
                self.url,
                data=sparql_query,
                headers=headers,
                auth=self.auth,
                verify=verify,
                timeout=60
            )
            if response.status_code == 400:
                with open("/tmp/failing_query.sparql", "w") as f:
                    f.write(sparql_query)
                logger.error("Full failing query saved to /tmp/failing_query.sparql")
            response.raise_for_status()
            logger.info("Successfully executed SPARQL update.")
            return response.json()
        except Exception as e:
            logger.error(f"Neptune SPARQL update failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    def execute_query(self, sparql_query: str):
        """Execute a SPARQL SELECT/DESCRIBE query."""
        try:
            verify = True
            if self.endpoint in ["127.0.0.1", "localhost"]:
                verify = False
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            headers = {'Content-Type': 'application/sparql-query'}
            if self.config.NEPTUNE_REAL_HOST:
                headers['Host'] = self.config.NEPTUNE_REAL_HOST
            
            response = requests.post(
                self.url,
                data=sparql_query,
                headers=headers,
                auth=self.auth,
                verify=verify,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Neptune SPARQL query failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    def upload_graph(self, graph: Graph):
        """Convert graph to triples and upload via INSERT DATA."""
        triples = graph.serialize(format="ntriples")
        if not triples.strip():
            logger.warning("Empty graph. Skipping upload.")
            return

        # Simple INSERT DATA query
        query = f"INSERT DATA {{ {triples} }}"
        return self.execute_update(query)
