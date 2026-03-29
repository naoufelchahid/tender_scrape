import graphistry
import pandas as pd
import os
import logging
import requests
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def visualize_jena_data():
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

    # 2. Fetch Data from Apache Jena Fuseki
    fuseki_url = os.getenv("FUSEKI_QUERY_URL", "http://localhost:3030/knowledgebase/query")
    
    logger.info(f"Fetching graph data from Apache Jena Fuseki at {fuseki_url}...")
    sparql_query = """
    PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?tender ?buyer ?buyerLabel ?object ?category ?deadline ?pubDate ?reference ?s3Uri ?isDocument
    WHERE {
      ?tender ts:Launched_by ?buyer .
      OPTIONAL { ?buyer rdfs:label ?buyerLabel }
      OPTIONAL { ?tender ts:Has_Object ?object }
      OPTIONAL { ?tender ts:Has_Category ?category }
      OPTIONAL { ?tender ts:Has_Deadline ?deadline }
      OPTIONAL { ?tender ts:Has_Publication_Date ?pubDate }
      OPTIONAL { ?tender ts:Has_Original_Reference ?reference }
      OPTIONAL { ?tender ts:Has_CPS_Doc ?s3Uri }
      OPTIONAL { ?tender ts:Has_Is_Documents ?isDocument }
    }
    LIMIT 2000
    """
    
    try:
        response = requests.post(fuseki_url, data={'query': sparql_query})
        response.raise_for_status()
        results = response.json()
        bindings = results.get('results', {}).get('bindings', [])
        
        if not bindings:
            logger.warning("No data found in Apache Jena Fuseki for visualization.")
            return

        # 3. Transform to DataFrame
        data = []
        for b in bindings:
            tender_id = b['tender']['value'].split('#')[-1]
            buyer_id = b['buyer']['value'].split('#')[-1]
            buyer_label = b.get('buyerLabel', {}).get('value', buyer_id)
            
            category = b.get('category', {}).get('value', '').split('#')[-1]
            deadline = b.get('deadline', {}).get('value', '')
            pub_date = b.get('pubDate', {}).get('value', '')
            reference = b.get('reference', {}).get('value', '')
            obj_desc = b.get('object', {}).get('value', 'No Description')
            if obj_desc.lower().startswith('object:'):
                obj_desc = obj_desc[7:].strip()
                
            s3_uri = b.get('s3Uri', {}).get('value', '')
            is_document = b.get('isDocument', {}).get('value', '')
            
            data.append({
                'tender': tender_id,
                'buyer': buyer_id,
                'buyerLabel': buyer_label,
                'object': obj_desc,
                'category': category,
                'deadline': deadline,
                'pubDate': pub_date,
                'reference': reference,
                's3Uri': s3_uri,
                'isDocument': is_document,
                'relationship': 'Launched_by'
            })
        
        df = pd.DataFrame(data)
        logger.info(f"Loaded {len(df)} relationships for visualization.")

        # 4. Create Nodes DataFrame for richer visualization
        tenders_df = df[['tender', 'object', 'category', 'deadline', 'pubDate', 'reference', 's3Uri', 'isDocument']].drop_duplicates().rename(columns={
            'tender': 'node_id', 
            'object': 'label'
        })
        tenders_df['type'] = 'Tender'
        
        buyers_df = df[['buyer', 'buyerLabel']].drop_duplicates().rename(columns={
            'buyer': 'node_id', 
            'buyerLabel': 'label'
        })
        buyers_df['type'] = 'Buyer'
        
        nodes_df = pd.concat([tenders_df, buyers_df], ignore_index=True)

        # 5. Create Edges DataFrame to avoid attaching node properties to edges
        edges_df = df[['buyer', 'tender', 'relationship']].drop_duplicates()

        # 6. Render with Graphistry
        g = graphistry.edges(edges_df, 'buyer', 'tender')
        g = g.nodes(nodes_df, 'node_id')
        
        # Bind labels and properties correctly
        g = g.bind(point_title='label', edge_title='relationship')
        
        # Launch visualization
        url = g.plot()
        logger.info(f"WOW! Your visualization is ready at: {url}")
        print(f"\n🚀 Visualization Link: {url}\n")

    except Exception as e:
        logger.error(f"Failed to create visualization: {e}")

if __name__ == "__main__":
    visualize_jena_data()
