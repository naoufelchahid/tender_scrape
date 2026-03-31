import graphistry
import pandas as pd
import os
import logging
from pathlib import Path
from rdflib import Graph, RDF, RDFS, Namespace
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Namespaces
TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

def visualize_nt_file(nt_file: str = "output/batch_20260330_203255.nt"):
    """Visualize RDF graph from N-Triples file using Graphistry."""

    # 1. Graphistry Configuration
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
        logger.error("Missing Graphistry credentials. Set GRAPHISTRY_KEY_ID/SECRET or USERNAME/PASSWORD in .env")
        return

    # 2. Load RDF graph from N-Triples file
    nt_path = Path(nt_file)
    if not nt_path.exists():
        logger.error(f"File not found: {nt_file}")
        return

    try:
        logger.info(f"Loading RDF graph from {nt_file}...")
        graph = Graph()
        graph.parse(nt_path, format='nt')
        logger.info(f"Loaded {len(graph)} triples from {nt_file}")

        # 3. Extract entities and relationships from RDF
        edges_data = []
        nodes_data = {}

        # Extract all tender-buyer relationships (Launched_by)
        for tender in graph.subjects(RDF.type, TS.Tenders):
            tender_id = str(tender).split('#')[-1]

            # Tender properties
            obj = list(graph.objects(tender, TS.Has_Object))
            obj_text = str(obj[0])[:100] if obj else "No Description"

            deadline = list(graph.objects(tender, TS.Has_Deadline))
            deadline_text = str(deadline[0]) if deadline else ""

            category = list(graph.objects(tender, TS.Has_Category))
            category_text = str(category[0]).split('#')[-1] if category else ""

            s3_doc = list(graph.objects(tender, TS.Has_CPS_Doc))
            s3_uri = str(s3_doc[0]) if s3_doc else ""

            has_docs = list(graph.objects(tender, TS.Has_Is_Documents))
            is_doc = str(has_docs[0]) if has_docs else "false"

            ref = list(graph.objects(tender, TS.Ref))
            reference = str(ref[0]) if ref else ""

            # Store tender node
            nodes_data[tender_id] = {
                'id': tender_id,
                'label': f"Tender: {reference}",
                'type': 'Tender',
                'object': obj_text,
                'category': category_text,
                'deadline': deadline_text,
                's3Uri': s3_uri,
                'hasDocuments': is_doc
            }

            # Get buyer
            buyers = list(graph.objects(tender, TS.Launched_by))
            for buyer in buyers:
                buyer_id = str(buyer).split('#')[-1]

                buyer_label = list(graph.objects(buyer, RDFS.label))
                buyer_label_text = str(buyer_label[0]) if buyer_label else buyer_id

                # Store buyer node
                if buyer_id not in nodes_data:
                    nodes_data[buyer_id] = {
                        'id': buyer_id,
                        'label': buyer_label_text,
                        'type': 'Buyer',
                        'contact': '',
                        'email': '',
                        'phone': ''
                    }

                # Add buyer contact info
                contact = list(graph.objects(buyer, TS.Has_Contact))
                if contact:
                    nodes_data[buyer_id]['contact'] = str(contact[0])

                email = list(graph.objects(buyer, TS.Has_Mail))
                if email:
                    nodes_data[buyer_id]['email'] = str(email[0])

                phone = list(graph.objects(buyer, TS.Has_Phone))
                if phone:
                    nodes_data[buyer_id]['phone'] = str(phone[0])

                # Create edge
                edges_data.append({
                    'source': buyer_id,
                    'target': tender_id,
                    'relationship': 'Launched_by'
                })

        # Extract tender-lot relationships
        for tender in graph.subjects(RDF.type, TS.Tenders):
            tender_id = str(tender).split('#')[-1]

            for lot in graph.objects(tender, TS.Has_lot):
                lot_id = str(lot).split('#')[-1]

                lot_desc = list(graph.objects(lot, TS.lot_description))
                lot_desc_text = str(lot_desc[0])[:80] if lot_desc else "Lot"

                lot_est = list(graph.objects(lot, TS.lot_estimated_value))
                lot_value = str(lot_est[0]) if lot_est else ""

                # Store lot node
                nodes_data[lot_id] = {
                    'id': lot_id,
                    'label': f"Lot: {lot_desc_text}",
                    'type': 'Lot',
                    'description': lot_desc_text,
                    'estimatedValue': lot_value
                }

                # Create edge
                edges_data.append({
                    'source': tender_id,
                    'target': lot_id,
                    'relationship': 'Has_lot'
                })

        if not edges_data:
            logger.warning("No relationships found in RDF graph")
            return

        # 4. Create DataFrames
        edges_df = pd.DataFrame(edges_data)
        nodes_df = pd.DataFrame(list(nodes_data.values()))

        logger.info(f"Extracted {len(nodes_df)} nodes and {len(edges_df)} edges")
        logger.info(f"\nNodes by type:")
        logger.info(f"  Tenders: {(nodes_df['type'] == 'Tender').sum()}")
        logger.info(f"  Buyers: {(nodes_df['type'] == 'Buyer').sum()}")
        logger.info(f"  Lots: {(nodes_df['type'] == 'Lot').sum()}")

        # 5. Render with Graphistry
        logger.info("Rendering graph with Graphistry...")
        g = graphistry.edges(edges_df, 'source', 'target')
        g = g.nodes(nodes_df, 'id')
        g = g.bind(point_title='label', point_color='type', edge_title='relationship')

        # Launch visualization
        url = g.plot()
        logger.info(f"✅ Visualization ready at: {url}")
        print(f"\n🚀 Graph Visualization: {url}\n")

    except Exception as e:
        logger.error(f"Failed to create visualization: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Visualize RDF N-Triples file with Graphistry")
    parser.add_argument('--nt-file', default='output/batch_20260330_203255.nt', help='Path to N-Triples file')
    args = parser.parse_args()

    visualize_nt_file(args.nt_file)
