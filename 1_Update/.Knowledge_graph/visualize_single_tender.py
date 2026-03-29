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

def visualize_single_tender(tender_ref):
    # 1. Graphistry Configuration
    username = os.getenv("GRAPHISTRY_USERNAME")
    password = os.getenv("GRAPHISTRY_PASSWORD")
    key_id = os.getenv("GRAPHISTRY_KEY_ID")
    secret_key = os.getenv("GRAPHISTRY_SECRET_KEY")

    if key_id and secret_key:
        graphistry.register(api=3, personal_key_id=key_id, personal_key_secret=secret_key, server='hub.graphistry.com')
    elif username and password:
        graphistry.register(api=3, username=username, password=password, server='hub.graphistry.com')
    else:
        logger.error("Missing Graphistry credentials.")
        return

    # 2. Fetch Data from Apache Jena Fuseki
    dataset = os.getenv("JENA_DATASET", "tender")
    fuseki_url = os.getenv("FUSEKI_QUERY_URL", f"http://localhost:3030/{dataset}/query")
    
    tender_iri = f"http://www.tenderintelligence.io/ontology/tender-structure#Tender_{tender_ref}"
    
    logger.info(f"Fetching full data view for {tender_iri} from {fuseki_url}...")
    
    # Expanded query: 3-hop traversal to capture Articles and Chunks
    sparql_query = f"""
    PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

    SELECT ?s ?p ?o ?sType ?oType
    WHERE {{
      {{
        # Hop 1: Direct from tender
        BIND(<{tender_iri}> AS ?s)
        ?s ?p ?o .
      }}
      UNION
      {{
        # Hop 2: Neighbors
        BIND(<{tender_iri}> AS ?central)
        ?central ?p1 ?s .
        FILTER(isIRI(?s))
        ?s ?p ?o .
        FILTER(?p != rdf:type)
      }}
      UNION
      {{
        # Hop 3: Neighbors of neighbors (e.g. Articles from Bordereau)
        BIND(<{tender_iri}> AS ?central)
        ?central ?p1 ?mid .
        FILTER(isIRI(?mid))
        ?mid ?p2 ?s .
        FILTER(isIRI(?s))
        ?s ?p ?o .
        FILTER(?p != rdf:type)
      }}
      OPTIONAL {{ ?s rdf:type ?sType }}
      OPTIONAL {{ ?o rdf:type ?oType }}
    }}
    """
    
    try:
        response = requests.post(fuseki_url, data={'query': sparql_query})
        response.raise_for_status()
        results = response.json()
        bindings = results.get('results', {}).get('bindings', [])
        
        if not bindings:
            logger.warning(f"No data found for {tender_iri}.")
            return

        # 3. Transform to Edge list
        edges = []
        nodes_dict = {}

        def get_short_id(uri):
            if '#' in uri: return uri.split('#')[-1]
            return uri.split('/')[-1]

        def process_node(node_data, node_type_data=None):
            val = node_data['value']
            is_iri = node_data['type'] == 'uri'
            
            if val in nodes_dict:
                # Merge type if discovered now
                if node_type_data and nodes_dict[val]['type'] == 'Entity':
                   nodes_dict[val]['type'] = node_type_data['value'].split('#')[-1]
                return val

            if is_iri:
                short_id = get_short_id(val)
                ntype = node_type_data['value'].split('#')[-1] if node_type_data else 'Entity'
                nodes_dict[val] = {
                    'node_id': val,
                    'label': short_id,
                    'type': ntype
                }
            else:
                # Literal node
                label = val[:50] + "..." if len(val) > 50 else val
                nodes_dict[val] = {
                    'node_id': val,
                    'label': label,
                    'type': 'Literal'
                }
            return val

        for b in bindings:
            s_uri = process_node(b['s'], b.get('sType'))
            o_val = process_node(b['o'], b.get('oType'))
            
            rel = get_short_id(b['p']['value'])
            
            edges.append({
                'source': s_uri,
                'target': o_val,
                'relationship': rel
            })
        
        edges_df = pd.DataFrame(edges).drop_duplicates()
        nodes_df = pd.DataFrame(list(nodes_dict.values()))

        # 4. Render with Graphistry
        g = graphistry.edges(edges_df, 'source', 'target')
        g = g.nodes(nodes_df, 'node_id')
        
        # Color strategy:
        g = g.encode_point_color('type', categorical_mapping={
            'Tenders': 'red',
            'Buyers': 'blue',
            'Lots': 'green',
            'Articles': 'orange',
            'Bordereaux': 'purple',
            'TenderSpecifications': 'brown',
            'TenderReglement': 'cyan',
            'Literal': 'silver'
        })
        
        # Bind labels and properties
        g = g.bind(point_title='label', edge_title='relationship')
        
        url = g.plot()
        logger.info(f"Deep visualization ready at: {url}")
        print(f"\n🚀 Deep Visualization Link: {url}\n")

    except Exception as e:
        logger.error(f"Failed to create visualization: {e}")

if __name__ == "__main__":
    visualize_single_tender("003_2026_SRMCS_SOCREGMULCASSETSA")
