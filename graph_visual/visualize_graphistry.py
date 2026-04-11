import graphistry
import pandas as pd
import os
import logging
from pathlib import Path
from rdflib import Graph, RDF, RDFS, Namespace
from rdflib.namespace import SKOS
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Namespaces
TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")

# Object properties that link instances to SKOS concepts
SKOS_OBJECT_PROPS = [
    TS.Has_Category,
    TS.Is_Located_In,
    TS.Has_Mode_Passation,
    TS.Has_Activity_Domain,
    TS.Has_Qualification,
    TS.Has_Agrement,
    TS.Is_SME_Reserved,
]

TYPE_COLORS = {
    'Tender':      0x1f77b4ff,
    'Buyer':       0xff7f0eff,
    'Lot':         0x2ca02cff,
    'SKOSConcept': 0x9467bdff,
}


def _local(uri: str) -> str:
    """Return local name after # or last / segment."""
    return uri.split('#')[-1] if '#' in uri else uri.rstrip('/').split('/')[-1]


def _str(vals) -> str:
    return str(vals[0]) if vals else ''


def visualize_nt_file(nt_file: str = "output/batch_20260330_203255.nt"):
    """Visualize RDF graph from N-Triples file + ontology SKOS individuals using Graphistry."""

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

    # 2. Load instance .nt file
    nt_path = Path(nt_file)
    if not nt_path.exists():
        logger.error(f"File not found: {nt_file}")
        return

    logger.info(f"Loading instance graph from {nt_file}...")
    graph = Graph()
    graph.parse(nt_path, format='nt')
    logger.info(f"Loaded {len(graph)} instance triples")

    # 3. Load and merge OWL ontology (brings in all SKOS individuals)
    onto_path = Path(__file__).parent / "tender_structure_final.owl"
    if onto_path.exists():
        logger.info(f"Loading ontology from {onto_path}...")
        graph.parse(str(onto_path))
        logger.info(f"Merged graph now has {len(graph)} triples")
    else:
        logger.warning(f"Ontology not found at {onto_path} — SKOS concept details will be limited")

    nodes_data: dict[str, dict] = {}
    edges_data: list[dict] = []

    # 4. Extract SKOS Concept nodes from the merged graph (ontology individuals)
    for concept in graph.subjects(RDF.type, SKOS.Concept):
        cid = _local(str(concept))

        pref_labels = [str(o) for o in graph.objects(concept, SKOS.prefLabel)]
        alt_labels  = [str(o) for o in graph.objects(concept, SKOS.altLabel)]
        notations   = [str(o) for o in graph.objects(concept, SKOS.notation)]
        schemes     = [_local(str(o)) for o in graph.objects(concept, SKOS.inScheme)]
        broaders    = list(graph.objects(concept, SKOS.broaderTransitive))
        broader_label = ''
        if broaders:
            bl = list(graph.objects(broaders[0], SKOS.prefLabel))
            broader_label = str(bl[0]) if bl else _local(str(broaders[0]))

        nodes_data[cid] = {
            'id': cid,
            'label': pref_labels[0] if pref_labels else cid,
            'type': 'SKOSConcept',
            'altLabel': alt_labels[0] if alt_labels else '',
            'notation': notations[0] if notations else '',
            'inScheme': schemes[0] if schemes else '',
            'broader': broader_label,
        }

    logger.info(f"Extracted {sum(1 for n in nodes_data.values() if n['type'] == 'SKOSConcept')} SKOS concept nodes")

    # 5. Extract Tender nodes with ALL data properties
    for tender in graph.subjects(RDF.type, TS.Tenders):
        tid = _local(str(tender))

        def tget(prop):
            return _str(list(graph.objects(tender, prop)))

        nodes_data[tid] = {
            'id': tid,
            'label': f"Tender: {tget(TS.Ref) or tid}",
            'type': 'Tender',
            'Ref': tget(TS.Ref),
            'Has_Original_Reference': tget(TS.Has_Original_Reference),
            'Has_Object': tget(TS.Has_Object)[:150] if tget(TS.Has_Object) else '',
            'estimated_value': tget(TS.estimated_value),
            'provisional_deposit': tget(TS.provisional_deposit),
            'launch_date': tget(TS.launch_date),
            'Has_Deadline': tget(TS.Has_Deadline),
            'retrait_address': tget(TS.retrait_address),
            'depot_address': tget(TS.depot_address),
            'opening_location': tget(TS.opening_location),
            'mode_soumission': tget(TS.mode_soumission),
            'reunionDetails': tget(TS.reunionDetails),
            'visiteLieuxDetails': tget(TS.visiteLieuxDetails),
            'plan_cost': tget(TS.plan_cost),
            'samples_info': tget(TS.samples_info),
            'Has_Is_Documents': tget(TS.Has_Is_Documents),
            'hasVariante': tget(TS.hasVariante),
            'Has_Multilot': tget(TS.Has_Multilot),
            'city': tget(TS.city),
            'mode_passation': tget(TS.mode_passation),
            'activity_domains': tget(TS.activity_domains),
            's3Uri': tget(TS.Has_CPS_Doc),
        }

        # Buyer edge
        for buyer in graph.objects(tender, TS.Launched_by):
            bid = _local(str(buyer))

            # Ensure buyer node exists (will be enriched below)
            if bid not in nodes_data:
                bl = list(graph.objects(buyer, RDFS.label))
                nodes_data[bid] = {
                    'id': bid,
                    'label': str(bl[0]) if bl else bid,
                    'type': 'Buyer',
                    'Has_Contact': '',
                    'Has_Mail': '',
                    'Has_Phone': '',
                    'Has_Adress': '',
                }

            def bget(prop):
                return _str(list(graph.objects(buyer, prop)))

            nodes_data[bid].update({
                'Has_Contact': bget(TS.Has_Contact),
                'Has_Mail': bget(TS.Has_Mail),
                'Has_Phone': bget(TS.Has_Phone),
                'Has_Adress': bget(TS.Has_Adress),
            })

            edges_data.append({'source': bid, 'target': tid, 'relationship': 'Launched_by'})

        # Lot edges
        for lot in graph.objects(tender, TS.Has_lot):
            lot_id = _local(str(lot))

            def lget(prop):
                return _str(list(graph.objects(lot, prop)))

            nodes_data[lot_id] = {
                'id': lot_id,
                'label': f"Lot: {lget(TS.lot_description)[:80] or lot_id}",
                'type': 'Lot',
                'lotID': lget(TS.lotID),
                'lot_description': lget(TS.lot_description),
                'lot_estimated_value': lget(TS.lot_estimated_value),
                'lot_provisional_deposit': lget(TS.lot_provisional_deposit),
                'lot_meeting_date': lget(TS.lot_meeting_date),
                'lot_site_visit': lget(TS.lot_site_visit),
                'lot_env_considerations': lget(TS.lot_env_considerations),
                'samples_info': lget(TS.samples_info),
                'lot_variant_allowed': lget(TS.lot_variant_allowed),
                'lot_qualifications': lget(TS.lot_qualifications),
                'lot_agrements': lget(TS.lot_agrements),
            }

            edges_data.append({'source': tid, 'target': lot_id, 'relationship': 'Has_lot'})

            # Lot → SKOS object property edges
            for prop in SKOS_OBJECT_PROPS:
                for concept in graph.objects(lot, prop):
                    cid = _local(str(concept))
                    edges_data.append({'source': lot_id, 'target': cid, 'relationship': _local(str(prop))})

            # Lot exactMatch edges
            for concept in graph.objects(lot, SKOS.exactMatch):
                cid = _local(str(concept))
                edges_data.append({'source': lot_id, 'target': cid, 'relationship': 'exactMatch'})

        # Tender → SKOS object property edges
        for prop in SKOS_OBJECT_PROPS:
            for concept in graph.objects(tender, prop):
                cid = _local(str(concept))
                edges_data.append({'source': tid, 'target': cid, 'relationship': _local(str(prop))})

        # Tender exactMatch edges
        for concept in graph.objects(tender, SKOS.exactMatch):
            cid = _local(str(concept))
            edges_data.append({'source': tid, 'target': cid, 'relationship': 'exactMatch'})

    if not edges_data:
        logger.warning("No relationships found in merged graph")
        return

    # 6. Build DataFrames
    edges_df = pd.DataFrame(edges_data).drop_duplicates()
    nodes_df = pd.DataFrame(list(nodes_data.values()))

    # Prune SKOS concept nodes to only those referenced by edges (avoid 1034 disconnected nodes)
    referenced_ids = set(edges_df['source']).union(set(edges_df['target']))
    nodes_df = nodes_df[nodes_df['id'].isin(referenced_ids)].copy()

    # Add color column
    nodes_df['color'] = nodes_df['type'].map(TYPE_COLORS).fillna(0x888888ff).astype(int)

    by_type = nodes_df['type'].value_counts().to_dict()
    logger.info(f"Final graph: {len(nodes_df)} nodes, {len(edges_df)} edges")
    for t, c in by_type.items():
        logger.info(f"  {t}: {c}")

    # 7. Render with Graphistry
    logger.info("Rendering graph with Graphistry...")
    g = graphistry.edges(edges_df, 'source', 'target')
    g = g.nodes(nodes_df, 'id')
    g = g.bind(point_title='label', point_color='color', edge_title='relationship')

    url = g.plot()
    logger.info(f"Visualization ready at: {url}")
    print(f"\nGraph Visualization: {url}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Visualize RDF N-Triples file + ontology SKOS individuals with Graphistry")
    parser.add_argument('--nt-file', default='output/batch_20260330_203255.nt', help='Path to N-Triples file')
    args = parser.parse_args()

    visualize_nt_file(args.nt_file)
