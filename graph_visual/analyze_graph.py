#!/usr/bin/env python3
"""Analyze the generated RDF graph to verify structural compliance."""

import logging
from pathlib import Path
from rdflib import Graph, RDF, RDFS, Namespace, Literal
from collections import defaultdict, Counter

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Namespaces
TS = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")

def categorize_properties(graph: Graph) -> tuple:
    """Categorize all properties as data properties or object properties."""
    data_props = defaultdict(set)  # predicate -> set of value types
    object_props = defaultdict(set)  # predicate -> set of target classes

    for s, p, o in graph.triples((None, None, None)):
        prop_name = str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]

        if isinstance(o, Literal):
            # Data property
            dtype = o.datatype if o.datatype else "xsd:string"
            dtype_short = str(dtype).split('#')[-1]
            data_props[prop_name].add(dtype_short)
        else:
            # Object property - get the target's type
            target_types = list(graph.objects(o, RDF.type))
            if target_types:
                for t in target_types:
                    type_name = str(t).split('#')[-1]
                    object_props[prop_name].add(type_name)
            else:
                object_props[prop_name].add("(untyped)")

    return data_props, object_props

def analyze_graph(nt_file: Path) -> dict:
    """Load and analyze the RDF graph."""
    logger.info(f"Loading RDF graph from {nt_file}...")
    graph = Graph()
    graph.parse(nt_file, format='nt')

    logger.info(f"\nTotal triples: {len(graph)}")

    # Analyze by type
    types_count = Counter()
    for s, p, o in graph.triples((None, RDF.type, None)):
        types_count[str(o).split('#')[-1]] += 1

    logger.info("\n=== ENTITY TYPES ===")
    for entity_type, count in types_count.most_common():
        logger.info(f"  {entity_type}: {count}")

    # Analyze Tenders
    tenders = list(graph.subjects(RDF.type, TS.Tenders))
    logger.info(f"\n=== TENDERS ({len(tenders)}) ===")
    for tender in tenders:
        tender_id = str(tender).split('#')[-1]
        logger.info(f"\n  Tender: {tender_id}")

        # Core properties
        refs = list(graph.objects(tender, TS.Ref))
        if refs:
            logger.info(f"    Ref: {refs[0]}")

        objs = list(graph.objects(tender, TS.Has_Object))
        if objs:
            logger.info(f"    Object: {str(objs[0])[:80]}...")

        # Dates
        deadlines = list(graph.objects(tender, TS.Has_Deadline))
        if deadlines:
            logger.info(f"    Deadline: {deadlines[0]}")

        # Buyer
        buyers = list(graph.objects(tender, TS.Launched_by))
        if buyers:
            buyer_name = list(graph.objects(buyers[0], RDFS.label))
            logger.info(f"    Buyer: {buyer_name[0] if buyer_name else str(buyers[0]).split('#')[-1]}")

        # SKOS resolutions
        skos_matches = list(graph.objects(tender, SKOS.exactMatch))
        if skos_matches:
            logger.info(f"    SKOS exactMatches: {len(skos_matches)}")
            for match in skos_matches[:3]:
                logger.info(f"      - {str(match).split('#')[-1]}")
            if len(skos_matches) > 3:
                logger.info(f"      ... and {len(skos_matches) - 3} more")

        # Activity domains
        activities = list(graph.objects(tender, TS.Has_Activity_Domain))
        if activities:
            logger.info(f"    Activity Domains: {len(activities)}")
            for act in activities[:2]:
                logger.info(f"      - {str(act).split('#')[-1]}")

        # Qualifications
        quals = list(graph.objects(tender, TS.Has_Qualification))
        if quals:
            logger.info(f"    Qualifications: {len(quals)}")
            for qual in quals[:2]:
                logger.info(f"      - {str(qual).split('#')[-1]}")

        # Lots
        lots = list(graph.objects(tender, TS.Has_lot))
        if lots:
            logger.info(f"    Lots: {len(lots)}")

    # Analyze Lots
    lots = list(graph.subjects(RDF.type, TS.Lots))
    logger.info(f"\n=== LOTS ({len(lots)}) ===")
    for lot in lots[:5]:  # Show first 5
        lot_id = str(lot).split('#')[-1]
        logger.info(f"\n  Lot: {lot_id}")

        lot_desc = list(graph.objects(lot, TS.lot_description))
        if lot_desc:
            logger.info(f"    Description: {str(lot_desc[0])[:60]}...")

        lot_est = list(graph.objects(lot, TS.lot_estimated_value))
        if lot_est:
            logger.info(f"    Estimated Value: {lot_est[0]}")

        lot_deposit = list(graph.objects(lot, TS.lot_provisional_deposit))
        if lot_deposit:
            logger.info(f"    Provisional Deposit: {lot_deposit[0]}")

        sme_reserved = list(graph.objects(lot, TS.Is_SME_Reserved))
        if sme_reserved:
            logger.info(f"    SME Reserved: {str(sme_reserved[0]).split('#')[-1]}")

    # Analyze Buyers
    buyers = list(graph.subjects(RDF.type, TS.Buyers))
    logger.info(f"\n=== BUYERS ({len(buyers)}) ===")
    for buyer in buyers:
        buyer_id = str(buyer).split('#')[-1]
        logger.info(f"\n  Buyer: {buyer_id}")

        labels = list(graph.objects(buyer, RDFS.label))
        if labels:
            logger.info(f"    Label: {labels[0]}")

        contacts = list(graph.objects(buyer, TS.Has_Contact))
        if contacts:
            logger.info(f"    Contact: {contacts[0]}")

        mails = list(graph.objects(buyer, TS.Has_Mail))
        if mails:
            logger.info(f"    Email: {mails[0]}")

        phones = list(graph.objects(buyer, TS.Has_Phone))
        if phones:
            logger.info(f"    Phone: {phones[0]}")

        address = list(graph.objects(buyer, TS.Has_Adress))
        if address:
            logger.info(f"    Address: {str(address[0])[:60]}...")

    # Categorize properties
    data_props, object_props = categorize_properties(graph)

    # DATA PROPERTIES
    logger.info("\n" + "=" * 70)
    logger.info("DATA PROPERTIES (Literal values)")
    logger.info("=" * 70)
    for prop in sorted(data_props.keys()):
        dtypes = sorted(data_props[prop])
        count = sum(1 for s, p, o in graph.triples((None, None, None))
                   if isinstance(o, Literal) and
                   (str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]) == prop)
        logger.info(f"\n  {prop}")
        logger.info(f"    Triple count: {count}")
        logger.info(f"    Value types: {', '.join(dtypes)}")
        # Show sample values
        samples = []
        for s, p, o in graph.triples((None, None, None)):
            if isinstance(o, Literal):
                prop_name = str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]
                if prop_name == prop:
                    sample = str(o)[:60]
                    if sample not in samples:
                        samples.append(sample)
                    if len(samples) >= 2:
                        break
        if samples:
            logger.info(f"    Sample values:")
            for sample in samples:
                logger.info(f"      - {sample}")

    # OBJECT PROPERTIES
    logger.info("\n" + "=" * 70)
    logger.info("OBJECT PROPERTIES (References to other entities)")
    logger.info("=" * 70)
    for prop in sorted(object_props.keys()):
        targets = sorted(object_props[prop])
        count = sum(1 for s, p, o in graph.triples((None, None, None))
                   if not isinstance(o, Literal) and
                   (str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]) == prop)
        logger.info(f"\n  {prop}")
        logger.info(f"    Triple count: {count}")
        logger.info(f"    Target types: {', '.join(targets)}")
        # Show sample references
        samples = []
        for s, p, o in graph.triples((None, None, None)):
            if not isinstance(o, Literal):
                prop_name = str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]
                if prop_name == prop:
                    sample = str(o).split('#')[-1]
                    if sample not in samples:
                        samples.append(sample)
                    if len(samples) >= 2:
                        break
        if samples:
            logger.info(f"    Sample references:")
            for sample in samples:
                logger.info(f"      - {sample}")

    # PROPERTY DISTRIBUTION SUMMARY
    logger.info("\n" + "=" * 70)
    logger.info("PROPERTY DISTRIBUTION SUMMARY")
    logger.info("=" * 70)
    pred_count = Counter()
    for s, p, o in graph.triples((None, None, None)):
        pred = str(p).split('#')[-1] if '#' in str(p) else str(p).split('/')[-1]
        pred_count[pred] += 1

    logger.info(f"\nTotal data properties: {len(data_props)}")
    logger.info(f"Total object properties: {len(object_props)}")
    logger.info(f"\nAll properties by frequency:")
    for prop, count in pred_count.most_common():
        prop_type = "DATA" if prop in data_props else "OBJECT"
        logger.info(f"  {prop:40} {count:4} triples ({prop_type})")

    return {
        'total_triples': len(graph),
        'entities': dict(types_count),
        'tenders': len(tenders),
        'lots': len(lots),
        'buyers': len(buyers),
    }

if __name__ == "__main__":
    nt_file = Path("output/batch_20260330_203255.nt")
    if not nt_file.exists():
        logger.error(f"File not found: {nt_file}")
        exit(1)

    stats = analyze_graph(nt_file)

    logger.info("\n" + "=" * 60)
    logger.info("GRAPH ANALYSIS COMPLETE")
    logger.info("=" * 60)
