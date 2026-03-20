#!/usr/bin/env python3
"""
enhance_ontology.py
───────────────────
Add OWL-Time timeline monitoring to tender_structure.ttl.

Creates temporal data properties, phase-interval classes, and a
TenderTimeline aggregate so we can measure time-lapses between:
  • Launch  → Deadline
  • Deadline → Adjudication
  • Adjudication → Execution Start
"""

from pathlib import Path
from rdflib import Graph, Namespace, Literal, RDF, RDFS, OWL, XSD, URIRef
from rdflib.namespace import SKOS

# ── Namespaces ────────────────────────────────────────────────────
TS   = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
TIME = Namespace("http://www.w3.org/2006/time#")

ONTOLOGY_PATH = Path(__file__).parent / "tender_structure.ttl"


# ── Helper ────────────────────────────────────────────────────────
def _add_datatype_property(
    g: Graph,
    prop_uri,
    domain_uri,
    range_uri,
    pref_label: str,
    alt_label: str,
    definition: str,
):
    """Declare a DatatypeProperty with SKOS metadata."""
    g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
    g.add((prop_uri, RDFS.domain, domain_uri))
    g.add((prop_uri, RDFS.range, range_uri))
    g.add((prop_uri, SKOS.prefLabel, Literal(pref_label, lang="fr")))
    g.add((prop_uri, SKOS.altLabel,  Literal(alt_label,  lang="fr")))
    g.add((prop_uri, SKOS.definition, Literal(definition, lang="fr")))
    g.add((prop_uri, SKOS.inScheme, TS.TenderStructureScheme))


def _add_class(
    g: Graph,
    cls_uri,
    super_cls,
    pref_label: str,
    alt_label: str,
    definition: str,
):
    """Declare an OWL Class with SKOS metadata."""
    g.add((cls_uri, RDF.type, OWL.Class))
    g.add((cls_uri, RDFS.subClassOf, super_cls))
    g.add((cls_uri, SKOS.prefLabel, Literal(pref_label, lang="fr")))
    g.add((cls_uri, SKOS.altLabel,  Literal(alt_label,  lang="fr")))
    g.add((cls_uri, SKOS.definition, Literal(definition, lang="fr")))
    g.add((cls_uri, SKOS.broader, super_cls))
    g.add((cls_uri, SKOS.inScheme, TS.TenderStructureScheme))


def _add_object_property(
    g: Graph,
    prop_uri,
    domain_uri,
    range_uri,
    pref_label: str,
    alt_label: str,
    definition: str,
):
    """Declare an ObjectProperty with SKOS metadata."""
    g.add((prop_uri, RDF.type, OWL.ObjectProperty))
    g.add((prop_uri, RDFS.domain, domain_uri))
    g.add((prop_uri, RDFS.range, range_uri))
    g.add((prop_uri, SKOS.prefLabel, Literal(pref_label, lang="fr")))
    g.add((prop_uri, SKOS.altLabel,  Literal(alt_label,  lang="fr")))
    g.add((prop_uri, SKOS.definition, Literal(definition, lang="fr")))
    g.add((prop_uri, SKOS.inScheme, TS.TenderStructureScheme))


# ── 1. Missing Temporal Data Properties ───────────────────────────
def add_temporal_properties(g: Graph):
    """Add date properties missing from the lifecycle."""

    _add_datatype_property(
        g,
        TS.Has_Adjudication_Date,
        TS.TenderResults,
        XSD.dateTime,
        pref_label="Date d'Adjudication",
        alt_label="Date d'Attribution",
        definition=(
            "Date à laquelle la commission a statué sur "
            "l'attribution du marché."
        ),
    )

    _add_datatype_property(
        g,
        TS.Has_Execution_Start_Date,
        TS.TenderExecution,
        XSD.dateTime,
        pref_label="Date de Début d'Exécution",
        alt_label="Démarrage du Marché",
        definition=(
            "Date effective de lancement de l'exécution "
            "du marché par le titulaire."
        ),
    )

    _add_datatype_property(
        g,
        TS.Has_Execution_End_Date,
        TS.TenderExecution,
        XSD.dateTime,
        pref_label="Date de Fin d'Exécution",
        alt_label="Réception Définitive",
        definition=(
            "Date de réception définitive ou d'achèvement "
            "du marché."
        ),
    )

    print("  ✓ Added 3 temporal data properties")


# ── 2. OWL-Time Interval Classes ─────────────────────────────────
def add_timeline_classes(g: Graph):
    """Add TenderTimeline and phase-interval sub-classes."""

    # Main aggregate class
    _add_class(
        g,
        TS.TenderTimeline,
        OWL.Thing,
        pref_label="Chronologie du Marché",
        alt_label="Timeline",
        definition=(
            "Agrégat des intervalles temporels couvrant le cycle "
            "de vie d'un appel d'offres: publication, adjudication, "
            "exécution."
        ),
    )

    # Phase intervals  (all subclass of time:ProperInterval)
    _add_class(
        g,
        TS.LaunchToDeadlineInterval,
        TIME.ProperInterval,
        pref_label="Intervalle Publication → Échéance",
        alt_label="Délai de Soumission",
        definition=(
            "Durée entre la date de publication de l'AO et la date "
            "limite de remise des offres."
        ),
    )

    _add_class(
        g,
        TS.DeadlineToAdjudicationInterval,
        TIME.ProperInterval,
        pref_label="Intervalle Échéance → Adjudication",
        alt_label="Délai d'Évaluation",
        definition=(
            "Durée entre la date limite de remise des offres "
            "et la date d'attribution du marché."
        ),
    )

    _add_class(
        g,
        TS.AdjudicationToExecutionInterval,
        TIME.ProperInterval,
        pref_label="Intervalle Adjudication → Exécution",
        alt_label="Délai de Démarrage",
        definition=(
            "Durée entre la date d'attribution du marché et le "
            "début effectif de l'exécution."
        ),
    )

    print("  ✓ Added 4 OWL-Time classes (TenderTimeline + 3 intervals)")


# ── 3. Linking Object Properties ─────────────────────────────────
def add_timeline_properties(g: Graph):
    """Add properties that wire tenders to their timelines."""

    _add_object_property(
        g,
        TS.Has_Timeline,
        TS.Tenders,
        TS.TenderTimeline,
        pref_label="A pour Chronologie",
        alt_label="Timeline du marché",
        definition=(
            "Lie un appel d'offres à l'objet TenderTimeline "
            "qui agrège ses intervalles de phase."
        ),
    )

    _add_object_property(
        g,
        TS.Has_Phase_Interval,
        TS.TenderTimeline,
        TIME.ProperInterval,
        pref_label="Contient l'Intervalle de Phase",
        alt_label="Phase temporelle",
        definition=(
            "Relie un TenderTimeline à un intervalle temporel "
            "de phase spécifique (soumission, évaluation, exécution)."
        ),
    )

    # Duration in days — a data property on intervals
    _add_datatype_property(
        g,
        TS.Has_Duration_Days,
        TIME.ProperInterval,
        XSD.integer,
        pref_label="Durée en Jours",
        alt_label="Nombre de jours",
        definition=(
            "Nombre de jours calculé entre le début et la fin "
            "de cet intervalle de phase."
        ),
    )

    print("  ✓ Added 2 object properties + 1 duration data property")


# ── Main ──────────────────────────────────────────────────────────
def main():
    print(f"Loading {ONTOLOGY_PATH} …")
    g = Graph()
    g.parse(str(ONTOLOGY_PATH), format="turtle")

    # Bind OWL-Time prefix
    g.bind("time", TIME)
    print("  ✓ Bound time: prefix")

    # Fix Ontology Header and add Import
    # Find existing ontology node or create one
    onto_uri = URIRef("http://www.tenderintelligence.io/ontology/tender-structure")
    
    # Check if there's a blank node ontology or existing one
    existing_onto = None
    for s in g.subjects(RDF.type, OWL.Ontology):
        existing_onto = s
        break
    
    if existing_onto:
        # If it's a blank node or different, we might want to unify it
        # Protege prefers a named ontology
        if isinstance(existing_onto, URIRef) and existing_onto != onto_uri:
             print(f"  ! Found existing ontology IRI: {existing_onto}")
             onto_uri = existing_onto
        elif not isinstance(existing_onto, URIRef):
             print(f"  ✓ Upgrading blank node ontology to {onto_uri}")
             # Transfer properties from blank node to named URI
             for p, o in g.predicate_objects(existing_onto):
                 g.add((onto_uri, p, o))
                 g.remove((existing_onto, p, o))
    else:
        print(f"  ✓ Creating ontology header at {onto_uri}")
        g.add((onto_uri, RDF.type, OWL.Ontology))

    # Add OWL-Time import
    TIME_ONTO = URIRef("http://www.w3.org/2006/time")
    if (onto_uri, OWL.imports, TIME_ONTO) not in g:
        g.add((onto_uri, OWL.imports, TIME_ONTO))
        print(f"  ✓ Added owl:imports <{TIME_ONTO}>")

    add_temporal_properties(g)
    add_timeline_classes(g)
    add_timeline_properties(g)

    # Serialize back to the same file
    g.serialize(str(ONTOLOGY_PATH), format="turtle")
    print(f"\n✅ Enhanced ontology saved → {ONTOLOGY_PATH}")


if __name__ == "__main__":
    main()
