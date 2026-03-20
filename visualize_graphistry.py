import graphistry
import pandas as pd
import os
import logging
from dotenv import load_dotenv
from kb_ingestion_container.src.neptune_client import NeptuneClient

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def visualize_neptune_data():
    # 1. Graphistry Configuration
    # You can set these in your .env file
    username = os.getenv("GRAPHISTRY_USERNAME")
    password = os.getenv("GRAPHISTRY_PASSWORD")
    key_id = os.getenv("GRAPHISTRY_KEY_ID")
    secret_key = os.getenv("GRAPHISTRY_SECRET_KEY")

    if key_id and secret_key:
        logger.info("Registering with Graphistry Personal Key ID and Secret...")
        graphistry.register(api=3, personal_key_id=key_id, personal_key_secret=secret_key, server='hub.graphistry.com')
    elif username and password:
        logger.info("Registering with Graphistry Username/Password...")
        graphistry.register(api=3, username=username, password=password, server='hub.graphistry.com')
    else:
        logger.error("Missing Graphistry credentials. Please set GRAPHISTRY_API_KEY or GRAPHISTRY_USERNAME/PASSWORD in .env")
        return

    # 2. Fetch Data from Neptune
    client = NeptuneClient()
    
    logger.info("Fetching graph data from Neptune...")
    sparql_query = """
    PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?tender ?buyer ?buyerLabel ?object
    WHERE {
      ?tender ts:Launched_by ?buyer .
      OPTIONAL { ?buyer rdfs:label ?buyerLabel }
      OPTIONAL { ?tender ts:Has_Object ?object }
    }
    LIMIT 1000
    """
    
    try:
        results = client.execute_query(sparql_query)
        bindings = results['results']['bindings']
        
        if not bindings:
            logger.warning("No data found in Neptune for visualization.")
            return

        # 3. Transform to DataFrame
        data = []
        for b in bindings:
            data.append({
                'tender': b['tender']['value'].split('#')[-1],
                'buyer': b.get('buyerLabel', {}).get('value', b['buyer']['value'].split('#')[-1]),
                'object': b.get('object', {}).get('value', 'No Description')
            })
        
        df = pd.DataFrame(data)
        logger.info(f"Loaded {len(df)} relationships for visualization.")

        # 4. Render with Graphistry
        # We'll map 'buyer' -> 'tender' edges
        g = graphistry.edges(df, 'buyer', 'tender')
        
        # Add some flair
        g = g.bind(edge_title='object', point_title='buyer')
        
        # Launch visualization
        url = g.plot()
        logger.info(f"WOW! Your visualization is ready at: {url}")
        print(f"\n🚀 Visualization Link: {url}\n")

    except Exception as e:
        logger.error(f"Failed to create visualization: {e}")

if __name__ == "__main__":
    visualize_neptune_data()
