# kg_builder.py Full Mapping Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `kg_builder.py` to emit a comprehensive set of RDF triples from the per-tender JSON output of `Db_updater.py`, including SKOS concept resolution with exactMatch, buyer contact enrichment, and lot-level triples.

**Architecture:** A `SkosResolver` class is added inside `kg_builder.py` and instantiated once at `KGBuilder.__init__` time. It parses `tender_structure_final.owl` once and builds 5 normalized-label → URIRef lookup dicts. `build_tender_triples()` is fully replaced. Two subagent-handled steps patch the OWL ontology and SHACL shapes before any Python is touched.

**Tech Stack:** Python 3, rdflib 7.6, pyshacl 0.31, boto3, OWL/XML, Turtle (SHACL).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tender_structure_final.owl` | Modify | Add 4 ObjectProperties, 3 DataProperties, 1 NamedIndividual; replace Has_Mode_Passation |
| `tender_shacl_shapes.ttl` | Modify | Align shapes to actual code property names; add new optional constraints |
| `kg_builder.py` | Modify | Add SkosResolver, parsing helpers, full build_tender_triples(), lot processing |

---

## Task 1: Patch OWL Ontology

**Files:**
- Modify: `tender_structure_final.owl`

- [ ] **Step 1: Locate and replace `Has_Mode_Passation` DataProperty**

Run to find the exact block:
```bash
grep -n "Has_Mode_Passation" tender_structure_final.owl
```

Find the block that looks like:
```xml
<owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Mode_Passation">
    <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
    <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
    <rdfs:label xml:lang="fr">Mode de passation</rdfs:label>
</owl:DatatypeProperty>
```

Replace it with:
```xml
<owl:ObjectProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Mode_Passation">
    <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
    <rdfs:range rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
    <rdfs:label xml:lang="fr">Mode de passation</rdfs:label>
</owl:ObjectProperty>
```

- [ ] **Step 2: Add new ObjectProperties before `</rdf:RDF>`**

Locate the closing `</rdf:RDF>` tag and insert before it:
```xml
    <!-- New ObjectProperties — kg_builder refactor 2026-03-30 -->

    <owl:ObjectProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Activity_Domain">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:range rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
        <rdfs:label xml:lang="fr">Domaines d'activité</rdfs:label>
    </owl:ObjectProperty>

    <owl:ObjectProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Qualification">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Lots"/>
        <rdfs:range rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
        <rdfs:label xml:lang="fr">Qualification requise</rdfs:label>
    </owl:ObjectProperty>

    <owl:ObjectProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Has_Agrement">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Lots"/>
        <rdfs:range rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
        <rdfs:label xml:lang="fr">Agrément requis</rdfs:label>
    </owl:ObjectProperty>

    <owl:ObjectProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#Is_SME_Reserved">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Lots"/>
        <rdfs:range rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
        <rdfs:label xml:lang="fr">Réservé TPE/PME</rdfs:label>
    </owl:ObjectProperty>

    <!-- New DataProperties — kg_builder refactor 2026-03-30 -->

    <owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#retrait_address">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
        <rdfs:label xml:lang="fr">Adresse de retrait</rdfs:label>
    </owl:DatatypeProperty>

    <owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#depot_address">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
        <rdfs:label xml:lang="fr">Adresse de dépôt</rdfs:label>
    </owl:DatatypeProperty>

    <owl:DatatypeProperty rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#samples_info">
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Tenders"/>
        <rdfs:domain rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#Lots"/>
        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
        <rdfs:label xml:lang="fr">Prospectus et échantillons</rdfs:label>
    </owl:DatatypeProperty>

    <!-- New NamedIndividual: SME reservation concept -->

    <owl:NamedIndividual rdf:about="http://www.tenderintelligence.io/ontology/tender-structure#IsSmeReserved">
        <rdf:type rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
        <skos:inScheme rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#ReserveTPEScheme"/>
        <skos:prefLabel xml:lang="fr">Réservé TPE/PME</skos:prefLabel>
        <skos:topConceptOf rdf:resource="http://www.tenderintelligence.io/ontology/tender-structure#ReserveTPEScheme"/>
    </owl:NamedIndividual>
```

- [ ] **Step 3: Verify Has_Contact / Has_Mail / Has_Phone / Has_Adress domain**

```bash
grep -A4 "Has_Contact\|Has_Mail\|Has_Phone\|Has_Adress" tender_structure_final.owl | grep "domain"
```

If any property has `rdfs:domain` restricted to `ts:Buyer` (singular) only, add a second domain line for `ts:Buyers`. If domain is absent, no change needed.

- [ ] **Step 4: Verify OWL file parses without error**

```bash
python3 -c "
from rdflib import Graph
g = Graph()
g.parse('tender_structure_final.owl', format='xml')
print(f'OK — {len(g)} triples')
"
```
Expected: `OK — <number> triples` with no exceptions.

- [ ] **Step 5: Commit**

```bash
git add tender_structure_final.owl
git commit -m "feat: add OWL properties for full kg_builder mapping (Has_Activity_Domain, Has_Qualification, Has_Agrement, Is_SME_Reserved, retrait_address, depot_address, samples_info, IsSmeReserved; replace Has_Mode_Passation DataProperty with ObjectProperty)"
```

---

## Task 2: Update SHACL Shapes

**Files:**
- Modify: `tender_shacl_shapes.ttl`

The current shapes validate properties the code doesn't emit (`ts:reference`, `ts:object`, `ts:buyer → ts:Buyer`) and miss properties it does emit. Replace the entire file.

- [ ] **Step 1: Replace `tender_shacl_shapes.ttl` with aligned version**

```turtle
# SHACL Shapes for Tender Knowledge Graph Validation
# Updated 2026-03-30: aligned to actual kg_builder.py property names

@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix ts:    <http://www.tenderintelligence.io/ontology/tender-structure#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .

# ----- Tender Shape -----
ts:TenderShape a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:message "Tender validation failed" ;

    sh:property [
        sh:path ts:Ref ;
        sh:datatype xsd:string ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "Tender Reference" ;
        sh:message "Tender must have exactly one ts:Ref"
    ] ;

    sh:property [
        sh:path ts:Has_Object ;
        sh:datatype xsd:string ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "Tender Object" ;
        sh:message "Tender must have exactly one ts:Has_Object"
    ] ;

    sh:property [
        sh:path ts:Launched_by ;
        sh:class ts:Buyers ;
        sh:minCount 1 ;
        sh:name "Buyer" ;
        sh:message "Tender must link to at least one ts:Buyers via ts:Launched_by"
    ] ;

    sh:property [
        sh:path ts:estimated_value ;
        sh:datatype xsd:decimal ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Has_Deadline ;
        sh:datatype xsd:dateTime ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:launch_date ;
        sh:datatype xsd:dateTime ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:city ;
        sh:datatype xsd:string ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Has_Is_Documents ;
        sh:datatype xsd:boolean ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Has_CPS_Doc ;
        sh:datatype xsd:anyURI ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Has_Multilot ;
        sh:datatype xsd:boolean ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Has_Activity_Domain ;
        sh:class skos:Concept
    ] ;

    sh:property [
        sh:path ts:Has_Mode_Passation ;
        sh:class skos:Concept ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path ts:Is_SME_Reserved ;
        sh:class skos:Concept ;
        sh:maxCount 1
    ] ;

    sh:property [
        sh:path skos:exactMatch ;
        sh:class skos:Concept
    ] .

# ----- Buyer Shape -----
ts:BuyerShape a sh:NodeShape ;
    sh:targetClass ts:Buyers ;
    sh:message "Buyer validation failed" ;

    sh:property [
        sh:path rdfs:label ;
        sh:datatype xsd:string ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "Buyer Name" ;
        sh:message "Buyer must have exactly one rdfs:label"
    ] ;

    sh:property [ sh:path ts:Has_Contact ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:Has_Mail    ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:Has_Phone   ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:Has_Adress  ; sh:datatype xsd:string ; sh:maxCount 1 ] .

# ----- Lot Shape -----
ts:LotShape a sh:NodeShape ;
    sh:targetClass ts:Lots ;
    sh:message "Lot validation failed" ;

    sh:property [
        sh:path ts:lotID ;
        sh:datatype xsd:string ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "Lot ID" ;
        sh:message "Lot must have a lot identifier"
    ] ;

    sh:property [ sh:path ts:lot_description      ; sh:datatype xsd:string  ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_estimated_value  ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_provisional_deposit ; sh:datatype xsd:decimal ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_qualifications   ; sh:datatype xsd:string ] ;
    sh:property [ sh:path ts:lot_agrements        ; sh:datatype xsd:string ] ;
    sh:property [ sh:path ts:lot_env_considerations ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:samples_info         ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_meeting_date     ; sh:datatype xsd:dateTime ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_site_visit       ; sh:datatype xsd:dateTime ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:lot_variant_allowed  ; sh:datatype xsd:boolean ; sh:maxCount 1 ] ;
    sh:property [ sh:path ts:Has_Qualification    ; sh:class skos:Concept ] ;
    sh:property [ sh:path ts:Has_Agrement         ; sh:class skos:Concept ] ;
    sh:property [ sh:path ts:Is_SME_Reserved      ; sh:class skos:Concept ; sh:maxCount 1 ] ;
    sh:property [ sh:path skos:exactMatch         ; sh:class skos:Concept ] .

# ----- Validation Report Shape -----
ts:ValidationReportShape a sh:NodeShape ;
    sh:targetClass sh:ValidationReport ;
    sh:property [
        sh:path sh:conforms ;
        sh:datatype xsd:boolean
    ] .
```

- [ ] **Step 2: Verify SHACL file parses**

```bash
python3 -c "
from rdflib import Graph
g = Graph()
g.parse('tender_shacl_shapes.ttl', format='turtle')
print(f'OK — {len(g)} triples')
"
```
Expected: `OK — <number> triples`

- [ ] **Step 3: Commit**

```bash
git add tender_shacl_shapes.ttl
git commit -m "fix: align SHACL shapes to actual kg_builder property names (ts:Ref, ts:Has_Object, ts:Launched_by/ts:Buyers); add new optional constraints"
```

---

## Task 3: Add Imports, Namespaces, and Parsing Helpers to kg_builder.py

**Files:**
- Modify: `kg_builder.py:17-53` (imports and namespace section)

- [ ] **Step 1: Update imports at top of kg_builder.py**

Replace the imports block (lines 17–28) with:
```python
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, RDF, RDFS, SKOS, XSD, URIRef
```

- [ ] **Step 2: Update namespace definitions (after `load_dotenv()`)**

Replace the existing namespace block (lines 44–60) with:
```python
# Namespace definitions
TS      = Namespace("http://www.tenderintelligence.io/ontology/tender-structure#")
ACTIVITY = Namespace("http://www.tenderintelligence.io/ontology/activity-domains#")
REGIONS = Namespace("http://www.tenderintelligence.io/ontology/morocco-regions#")
QUALIF  = Namespace("http://www.tenderintelligence.io/ontology/qualification#")

# Top-level category → SKOS concept URI
CATEGORY_TOP = {
    'travaux':     ACTIVITY.Travaux,
    'fournitures': ACTIVITY.Fournitures,
    'services':    ACTIVITY.Services,
}
```

- [ ] **Step 3: Add `parse_fr_decimal` and `parse_bool_str` helpers after `get_buyer_uri`**

After the existing `get_buyer_uri` function (around line 151), add:
```python
def parse_fr_decimal(value) -> Optional[Decimal]:
    """Parse French-formatted decimal string ('114 956 868,00') to Decimal."""
    if value is None:
        return None
    s = str(value).strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_bool_str(value) -> Optional[bool]:
    """Convert 'Oui'/'Non'/bool/None to bool or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('oui', 'true', '1', 'yes'):
        return True
    if s in ('non', 'false', '0', 'no'):
        return False
    return None


def parse_buyer_name(buyer_raw: str) -> str:
    """Extract display name: 'CODE / CODE - FULL NAME' → 'FULL NAME'."""
    if ' - ' in buyer_raw:
        return buyer_raw.split(' - ', 1)[1].strip()
    return buyer_raw.strip()
```

- [ ] **Step 4: Update `parse_date` to try ISO format first**

Replace the existing `parse_date` function with:
```python
def parse_date(date_str) -> Optional[str]:
    """
    Parse date string to ISO 8601 xsd:dateTime.
    Tries: fromisoformat → dd/mm/yyyy HH:MM → dd/mm/yyyy
    Handles malformed format: dd/mm/yyyyHH:MM (missing space).
    """
    if not date_str:
        return None
    date_str = str(date_str).strip()
    # Try ISO format first (e.g., "2026-05-12T10:00:00")
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
    except ValueError:
        pass
    # Fix malformed dates (e.g., "03/02/202610:00" → "03/02/2026 10:00")
    date_str = re.sub(r'(\d{2}/\d{2}/\d{4})(\d{2}:\d{2})', r'\1 \2', date_str)
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        except ValueError:
            continue
    logger.warning(f"Could not parse date: {date_str!r}")
    return None
```

- [ ] **Step 5: Verify helpers work**

```bash
python3 -c "
from kg_builder import parse_fr_decimal, parse_bool_str, parse_buyer_name, parse_date
assert str(parse_fr_decimal('114 956 868,00')) == '114956868.00'
assert parse_bool_str('Oui') is True
assert parse_bool_str('Non') is False
assert parse_bool_str(None) is None
assert parse_buyer_name('RGON / RGON - REGION DE GUELMIM - OUED NOUN') == 'REGION DE GUELMIM - OUED NOUN'
assert parse_date('2026-05-12T10:00:00').startswith('2026-05-12')
assert parse_date('03/02/202610:00').startswith('2026-02-03')
print('All helpers OK')
"
```
Expected: `All helpers OK`

- [ ] **Step 6: Commit**

```bash
git add kg_builder.py
git commit -m "feat: add parsing helpers and namespace definitions to kg_builder.py"
```

---

## Task 4: Add SkosResolver Class

**Files:**
- Modify: `kg_builder.py` — insert `SkosResolver` class before `KGBuilder`

- [ ] **Step 1: Insert `SkosResolver` class before the `KGBuilder` class definition**

Insert immediately before `class KGBuilder:`:
```python
class SkosResolver:
    """
    Parses the OWL ontology once and builds normalized-label → URIRef
    lookup dicts for five SKOS schemes. Used by KGBuilder to resolve
    string fields to SKOS concept URIs.
    """

    def __init__(self, ontology_path: Path):
        self._g = Graph()
        self._g.parse(str(ontology_path), format="xml")
        logger.info(f"SkosResolver: loaded {len(self._g)} triples from {ontology_path.name}")
        self.regions       = self._build_scheme_index(REGIONS.Scheme)
        self.activity      = self._build_activity_index()
        self.mode_passation = self._build_scheme_index(TS.ModeDePassationScheme)
        self.qualifications = self._build_subtree_index(QUALIF.QualificationCategory)
        self.agrements     = self._build_subtree_index(QUALIF.Agrement)
        logger.info(
            f"SkosResolver: regions={len(self.regions)}, activity={len(self.activity)}, "
            f"mode_passation={len(self.mode_passation)}, "
            f"qualifications={len(self.qualifications)}, agrements={len(self.agrements)}"
        )

    @staticmethod
    def _normalize(s: str) -> str:
        """Strip accents, lowercase, collapse whitespace."""
        s = unicodedata.normalize('NFKD', s)
        s = ''.join(c for c in s if not unicodedata.combining(c))
        return ' '.join(s.lower().split())

    def _build_scheme_index(self, scheme_uri: URIRef) -> Dict[str, URIRef]:
        """Index all concepts in a scheme by normalized prefLabel."""
        idx: Dict[str, URIRef] = {}
        for concept in self._g.subjects(SKOS.inScheme, scheme_uri):
            for label in self._g.objects(concept, SKOS.prefLabel):
                idx[self._normalize(str(label))] = concept
        return idx

    def _build_activity_index(self) -> Dict[str, URIRef]:
        """Combine all three activity domain schemes into one index."""
        idx: Dict[str, URIRef] = {}
        for scheme in [
            ACTIVITY.SchemeTravaux,
            ACTIVITY.SchemeFournitures,
            ACTIVITY.SchemeServices,
        ]:
            idx.update(self._build_scheme_index(scheme))
        return idx

    def _build_subtree_index(self, root: URIRef) -> Dict[str, URIRef]:
        """
        Walk narrowerTransitive from root, index every node by prefLabel.
        Used for qualification and agrement subtrees.
        """
        idx: Dict[str, URIRef] = {}
        seen: set = set()
        queue = [root]
        while queue:
            node = queue.pop()
            if node in seen:
                continue
            seen.add(node)
            for label in self._g.objects(node, SKOS.prefLabel):
                idx[self._normalize(str(label))] = node
            for child in self._g.objects(node, SKOS.narrowerTransitive):
                queue.append(child)
        return idx

    def resolve(self, scheme: str, label: str) -> Optional[URIRef]:
        """
        Return the URIRef for `label` in `scheme`, or None if not found.
        Caller must emit a fallback literal when None is returned.
        """
        idx = {
            'regions':       self.regions,
            'activity':      self.activity,
            'mode_passation': self.mode_passation,
            'qualifications': self.qualifications,
            'agrements':     self.agrements,
        }.get(scheme)
        if idx is None:
            logger.warning(f"SkosResolver: unknown scheme '{scheme}'")
            return None
        return idx.get(self._normalize(label))
```

- [ ] **Step 2: Instantiate SkosResolver in `KGBuilder.__init__`**

Inside `KGBuilder.__init__`, after `self.output_dir.mkdir(parents=True, exist_ok=True)`, add:
```python
        # SKOS concept resolver — built once from OWL at init time
        if self.ontology_file.exists():
            self.resolver = SkosResolver(self.ontology_file)
        else:
            logger.warning(f"Ontology not found: {self.ontology_file} — SKOS resolution disabled")
            self.resolver = None
```

- [ ] **Step 3: Verify SkosResolver loads and resolves**

```bash
python3 -c "
from pathlib import Path
from kg_builder import SkosResolver
r = SkosResolver(Path('tender_structure_final.owl'))
# city lookup
print('TAN-TAN ->', r.resolve('regions', 'TAN-TAN'))
# mode passation lookup (strip the leading pipe first)
print('Sur offre de prix ->', r.resolve('mode_passation', 'Sur offre de prix'))
# activity lookup
print('Travaux dassises ->', r.resolve('activity', 'Travaux d assises traitees et enrobees a chaud'))
print('Done')
"
```
Expected: URIRef or None for each (no exceptions).

- [ ] **Step 4: Commit**

```bash
git add kg_builder.py
git commit -m "feat: add SkosResolver class to kg_builder.py with 5 normalized SKOS lookup indices"
```

---

## Task 5: Refactor `build_tender_triples()` — Tender and Buyer Triples

**Files:**
- Modify: `kg_builder.py:251-383` (replace `build_tender_triples`)

- [ ] **Step 1: Replace `build_tender_triples()` with the new implementation**

Replace the entire `build_tender_triples` method with:

```python
    def build_tender_triples(self, tender: Dict) -> Graph:
        """
        Build RDF triples for a single tender from per-tender JSON format.
        Lot triples are included via _build_lot_triples().
        """
        g = Graph()
        g.bind("ts", TS)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("activity", ACTIVITY)
        g.bind("skos", SKOS)
        g.bind("regions", REGIONS)
        g.bind("qualif", QUALIF)

        reference = tender.get('reference')
        if not reference:
            logger.warning("Skipping tender without reference")
            return g

        tender_uri = get_tender_uri(reference)
        g.add((tender_uri, RDF.type, TS.Tenders))

        # ── Core data properties ──────────────────────────────────────────
        g.add((tender_uri, TS.Ref, Literal(reference, datatype=XSD.string)))

        orig_ref = tender.get('original_reference')
        if orig_ref:
            g.add((tender_uri, TS.Has_Original_Reference,
                   Literal(orig_ref, datatype=XSD.string)))

        obj = tender.get('object')
        if obj:
            g.add((tender_uri, TS.Has_Object, Literal(obj, datatype=XSD.string)))

        deadline = tender.get('deadline')
        if deadline:
            parsed = parse_date(deadline)
            if parsed:
                g.add((tender_uri, TS.Has_Deadline,
                       Literal(parsed, datatype=XSD.dateTime)))

        launch_date = tender.get('launch_date')
        if launch_date:
            parsed = parse_date(launch_date)
            if parsed:
                g.add((tender_uri, TS.launch_date,
                       Literal(parsed, datatype=XSD.dateTime)))

        # ── SKOS: main_category → top concept ────────────────────────────
        main_cat = (tender.get('main_category') or '').strip().lower()
        cat_uri = CATEGORY_TOP.get(main_cat)
        if cat_uri:
            g.add((tender_uri, TS.Has_Category, cat_uri))

        # ── SKOS: city / all_cities → Is_Located_In ──────────────────────
        def _add_city(city_str: str):
            if not city_str:
                return
            city_uri = self.resolver.resolve('regions', city_str) if self.resolver else None
            if city_uri:
                g.add((tender_uri, TS.Is_Located_In, city_uri))
                g.add((tender_uri, SKOS.exactMatch, city_uri))
            else:
                g.add((tender_uri, TS.city, Literal(city_str, datatype=XSD.string)))

        city = tender.get('city')
        if city:
            _add_city(city)

        all_cities = tender.get('all_cities') or []
        if isinstance(all_cities, list):
            for c in all_cities:
                if c and c != city:
                    _add_city(c)

        # ── SKOS: mode_passation ──────────────────────────────────────────
        mode_raw = tender.get('mode_passation') or ''
        mode_clean = mode_raw.lstrip('|').strip()
        if mode_clean:
            mode_uri = self.resolver.resolve('mode_passation', mode_clean) if self.resolver else None
            if mode_uri:
                g.add((tender_uri, TS.Has_Mode_Passation, mode_uri))
                g.add((tender_uri, SKOS.exactMatch, mode_uri))
            else:
                g.add((tender_uri, TS.mode_passation,
                       Literal(mode_clean, datatype=XSD.string)))

        # ── SKOS: activity_domains (last segment each) ────────────────────
        for domain_str in (tender.get('activity_domains') or []):
            if not domain_str:
                continue
            last_seg = domain_str.split(' / ')[-1].strip()
            act_uri = self.resolver.resolve('activity', last_seg) if self.resolver else None
            if act_uri:
                g.add((tender_uri, TS.Has_Activity_Domain, act_uri))
                g.add((tender_uri, SKOS.exactMatch, act_uri))
            else:
                g.add((tender_uri, TS.activity_domains,
                       Literal(last_seg, datatype=XSD.string)))

        # ── SKOS: is_sme_reserved ─────────────────────────────────────────
        if tender.get('is_sme_reserved') is True:
            g.add((tender_uri, TS.Is_SME_Reserved, TS.IsSmeReserved))
            g.add((tender_uri, SKOS.exactMatch, TS.IsSmeReserved))

        # ── Plain string data properties ──────────────────────────────────
        for field, prop in [
            ('retrait_address',  TS.retrait_address),
            ('depot_address',    TS.depot_address),
            ('mode_soumission',  TS.mode_soumission),
            ('opening_location', TS.opening_location),
            ('plan_cost',        TS.plan_cost),
            ('reunion',          TS.reunionDetails),
            ('site_visit',       TS.visiteLieuxDetails),
            ('samples_info',     TS.samples_info),
        ]:
            val = tender.get(field)
            if val:
                g.add((tender_uri, prop, Literal(str(val), datatype=XSD.string)))

        # ── Decimal properties ────────────────────────────────────────────
        est_val = parse_fr_decimal(tender.get('estimated_value'))
        if est_val is not None:
            g.add((tender_uri, TS.estimated_value,
                   Literal(est_val, datatype=XSD.decimal)))

        prov_dep = parse_fr_decimal(tender.get('provisional_deposit'))
        if prov_dep is not None:
            g.add((tender_uri, TS.provisional_deposit,
                   Literal(prov_dep, datatype=XSD.decimal)))

        # ── SKOS: qualifications (3rd segment each) ───────────────────────
        for qual_str in (tender.get('qualifications') or []):
            if not qual_str:
                continue
            parts = qual_str.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else qual_str.strip()
            qual_uri = self.resolver.resolve('qualifications', seg) if self.resolver else None
            if qual_uri:
                g.add((tender_uri, TS.Has_Qualification, qual_uri))
                g.add((tender_uri, SKOS.exactMatch, qual_uri))
            else:
                g.add((tender_uri, TS.Has_Qualifications,
                       Literal(seg, datatype=XSD.string)))

        # ── SKOS: agrements (3rd segment each) ───────────────────────────
        for agr_str in (tender.get('agrements') or []):
            if not agr_str:
                continue
            parts = agr_str.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else agr_str.strip()
            agr_uri = self.resolver.resolve('agrements', seg) if self.resolver else None
            if agr_uri:
                g.add((tender_uri, TS.Has_Agrement, agr_uri))
                g.add((tender_uri, SKOS.exactMatch, agr_uri))
            else:
                g.add((tender_uri, TS.requiredAgrements,
                       Literal(seg, datatype=XSD.string)))

        # ── Boolean: variante ─────────────────────────────────────────────
        variante = parse_bool_str(tender.get('variante'))
        if variante is not None:
            g.add((tender_uri, TS.hasVariante,
                   Literal(variante, datatype=XSD.boolean)))

        # ── Documents ────────────────────────────────────────────────────
        download_available = tender.get('download_available')
        g.add((tender_uri, TS.Has_Is_Documents,
               Literal(bool(download_available), datatype=XSD.boolean)))

        s3_folder = tender.get('s3_folder')
        if s3_folder:
            if not s3_folder.startswith('s3://') and not s3_folder.startswith('http'):
                s3_folder = f"s3://{self.s3_bucket}/{s3_folder}" if self.s3_bucket else s3_folder
            g.add((tender_uri, TS.Has_CPS_Doc,
                   Literal(s3_folder, datatype=XSD.anyURI)))

        # ── Multilot ─────────────────────────────────────────────────────
        lots = tender.get('lots') or []
        g.add((tender_uri, TS.Has_Multilot,
               Literal(len(lots) > 1, datatype=XSD.boolean)))

        # ── Buyer node ───────────────────────────────────────────────────
        buyer_raw = tender.get('buyer') or ''
        if buyer_raw:
            buyer_name = parse_buyer_name(buyer_raw)
            buyer_uri = get_buyer_uri(buyer_name)
            if buyer_uri not in self.seen_buyers:
                g.add((buyer_uri, RDF.type, TS.Buyers))
                g.add((buyer_uri, RDFS.label,
                       Literal(buyer_name, datatype=XSD.string)))
                contacts = tender.get('contacts') or {}
                if contacts.get('name'):
                    g.add((buyer_uri, TS.Has_Contact,
                           Literal(contacts['name'], datatype=XSD.string)))
                if contacts.get('email'):
                    g.add((buyer_uri, TS.Has_Mail,
                           Literal(contacts['email'], datatype=XSD.string)))
                if contacts.get('phone'):
                    g.add((buyer_uri, TS.Has_Phone,
                           Literal(contacts['phone'], datatype=XSD.string)))
                opening_loc = tender.get('opening_location')
                if opening_loc:
                    g.add((buyer_uri, TS.Has_Adress,
                           Literal(opening_loc, datatype=XSD.string)))
                self.seen_buyers.add(buyer_uri)
            g.add((tender_uri, TS.Launched_by, buyer_uri))

        # ── Lot nodes ────────────────────────────────────────────────────
        for lot in lots:
            self._build_lot_triples(g, tender_uri, reference, lot)

        return g
```

- [ ] **Step 2: Add `_build_lot_triples` as a private method of `KGBuilder`**

Add immediately after `build_tender_triples`:
```python
    def _build_lot_triples(
        self, g: Graph, tender_uri: URIRef, reference: str, lot: Dict
    ) -> None:
        """Add lot triples to graph g. Called once per lot dict."""
        lot_n = lot.get('lot number')
        if lot_n is None:
            return
        lot_id = str(lot_n)
        lot_uri = TS[f"Lot_{slugify(reference)}_{lot_id}"]
        g.add((lot_uri, RDF.type, TS.Lots))
        g.add((lot_uri, TS.lotID, Literal(lot_id, datatype=XSD.string)))
        g.add((tender_uri, TS.Has_lot, lot_uri))

        # Description — key is e.g. "lot1_object", "lot2_object"
        lot_desc = lot.get(f'lot{lot_id}_object')
        if lot_desc:
            g.add((lot_uri, TS.lot_description,
                   Literal(lot_desc, datatype=XSD.string)))

        # Financial — keys e.g. "Lot1_estimation", "Lot2_caution"
        lot_est = parse_fr_decimal(lot.get(f'Lot{lot_id}_estimation'))
        if lot_est is not None:
            g.add((lot_uri, TS.lot_estimated_value,
                   Literal(lot_est, datatype=XSD.decimal)))

        lot_caut = parse_fr_decimal(lot.get(f'Lot{lot_id}_caution'))
        if lot_caut is not None:
            g.add((lot_uri, TS.lot_provisional_deposit,
                   Literal(lot_caut, datatype=XSD.decimal)))

        # SKOS: qualification (key e.g. "Lot1_qualification")
        lot_qual = lot.get(f'Lot{lot_id}_qualification')
        if lot_qual:
            parts = lot_qual.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else lot_qual.strip()
            qual_uri = self.resolver.resolve('qualifications', seg) if self.resolver else None
            if qual_uri:
                g.add((lot_uri, TS.Has_Qualification, qual_uri))
                g.add((lot_uri, SKOS.exactMatch, qual_uri))
            else:
                g.add((lot_uri, TS.lot_qualifications,
                       Literal(seg, datatype=XSD.string)))

        # SKOS: agrement (key e.g. "Lot1_agreement")
        lot_agr = lot.get(f'Lot{lot_id}_agreement')
        if lot_agr:
            parts = lot_agr.split(' / ')
            seg = parts[2].strip() if len(parts) >= 3 else lot_agr.strip()
            agr_uri = self.resolver.resolve('agrements', seg) if self.resolver else None
            if agr_uri:
                g.add((lot_uri, TS.Has_Agrement, agr_uri))
                g.add((lot_uri, SKOS.exactMatch, agr_uri))
            else:
                g.add((lot_uri, TS.lot_agrements,
                       Literal(seg, datatype=XSD.string)))

        # Fixed-key lot fields
        samples = lot.get('Procpectus_et_echantillons')
        if samples:
            g.add((lot_uri, TS.samples_info,
                   Literal(str(samples), datatype=XSD.string)))

        reunion = lot.get('Reunion')
        if reunion:
            parsed = parse_date(reunion)
            if parsed:
                g.add((lot_uri, TS.lot_meeting_date,
                       Literal(parsed, datatype=XSD.dateTime)))

        visite = lot.get('visite_des_lieux')
        if visite:
            parsed = parse_date(visite)
            if parsed:
                g.add((lot_uri, TS.lot_site_visit,
                       Literal(parsed, datatype=XSD.dateTime)))

        lot_var = parse_bool_str(lot.get('variante'))
        if lot_var is not None:
            g.add((lot_uri, TS.lot_variant_allowed,
                   Literal(lot_var, datatype=XSD.boolean)))

        env = lot.get('Env_consideration')
        if env:
            g.add((lot_uri, TS.lot_env_considerations,
                   Literal(str(env), datatype=XSD.string)))

        if parse_bool_str(lot.get('Reserve_TPE_PME')) is True:
            g.add((lot_uri, TS.Is_SME_Reserved, TS.IsSmeReserved))
            g.add((lot_uri, SKOS.exactMatch, TS.IsSmeReserved))
```

- [ ] **Step 3: Update `build_batch_graph()` to add new namespace bindings**

Find the `batch_graph.bind(...)` block in `build_batch_graph()` and replace it with:
```python
        batch_graph = Graph()
        batch_graph.bind("ts",       TS)
        batch_graph.bind("rdfs",     RDFS)
        batch_graph.bind("xsd",      XSD)
        batch_graph.bind("activity", ACTIVITY)
        batch_graph.bind("skos",     SKOS)
        batch_graph.bind("regions",  REGIONS)
        batch_graph.bind("qualif",   QUALIF)
```

- [ ] **Step 4: Fix `upload_to_s3` crash when using `--input-dir`**

In `upload_to_s3`, the `Metadata` dict references `self.input_file.name` which crashes when `input_file` is `None`. Replace the `Metadata` dict with:
```python
                    'Metadata': {
                        'batch_date': datetime.now().isoformat(),
                        'tender_count': str(tender_count),
                        'source': self.input_file.name if self.input_file else str(self.input_dir),
                    }
```

- [ ] **Step 5: Commit**

```bash
git add kg_builder.py
git commit -m "feat: refactor build_tender_triples() with full JSON→RDF mapping, lot processing, buyer contact enrichment, SKOS exactMatch"
```

---

## Task 6: Smoke Test Against Sample JSON Files

**Files:**
- Read: `tenders_metadata/12_BR_RGON_2026.json`
- Read: `tenders_metadata/TO4130038_2026_ONEEBELEC.json`

- [ ] **Step 1: Run kg_builder against the tenders_metadata/ directory**

```bash
python3 kg_builder.py \
    --input-dir ./tenders_metadata \
    --output-dir ./output \
    --ontology tender_structure_final.owl \
    --shacl-shapes tender_shacl_shapes.ttl
```
Expected: exit code 0, log lines showing triple count and "PHASE 3 COMPLETED SUCCESSFULLY". If SHACL fails, see Step 2.

- [ ] **Step 2: If SHACL fails — inspect violations**

```bash
python3 -c "
from rdflib import Graph
from pyshacl import validate
from pathlib import Path
from kg_builder import KGBuilder

b = KGBuilder(input_dir='./tenders_metadata', output_dir='./output',
              ontology_file='tender_structure_final.owl',
              shacl_file='tender_shacl_shapes.ttl')
tenders = b.load_from_dir()
g = b.build_batch_graph(tenders)
shacl_g = Graph(); shacl_g.parse('tender_shacl_shapes.ttl', format='turtle')
ont_g = Graph(); ont_g.parse('tender_structure_final.owl', format='xml')
conforms, _, text = validate(g, shacl_graph=shacl_g, ont_graph=ont_g, inference='none')
print(text)
"
```
Read the violation messages, identify the property or shape causing the failure, fix either the SHACL shape (if the constraint is wrong) or the Python code (if the triple is malformed).

- [ ] **Step 3: Verify triple content for 12_BR_RGON_2026**

```bash
python3 -c "
from rdflib import Graph
from pathlib import Path
from kg_builder import KGBuilder, TS, SKOS

b = KGBuilder(input_dir='./tenders_metadata', output_dir='./output',
              ontology_file='tender_structure_final.owl',
              shacl_file='tender_shacl_shapes.ttl')
import json
tender = json.loads(Path('tenders_metadata/12_BR_RGON_2026.json').read_text())
g = b.build_tender_triples(tender)

from rdflib import URIRef, Literal, XSD
tender_uri = list(g.subjects(TS.Ref, Literal('12/BR/RGON/2026', datatype=XSD.string)))[0]
print('Tender URI:', tender_uri)
print('Triple count:', len(g))
print('Has_Object:', list(g.objects(tender_uri, TS.Has_Object)))
print('Launched_by:', list(g.objects(tender_uri, TS.Launched_by)))
print('Is_Located_In:', list(g.objects(tender_uri, TS.Is_Located_In)))
print('Has_Activity_Domain:', list(g.objects(tender_uri, TS.Has_Activity_Domain)))
print('exactMatches:', list(g.objects(tender_uri, SKOS.exactMatch)))
print('estimated_value:', list(g.objects(tender_uri, TS.estimated_value)))
"
```
Expected: non-empty lists for `Is_Located_In`, `Has_Activity_Domain`, `exactMatches`. `estimated_value` should be `Decimal('114956868.00')`.

- [ ] **Step 4: Verify lot triples for TO4130038_2026_ONEEBELEC**

```bash
python3 -c "
from rdflib import Graph, Literal, XSD
from pathlib import Path
from kg_builder import KGBuilder, TS

b = KGBuilder(input_dir='./tenders_metadata', output_dir='./output',
              ontology_file='tender_structure_final.owl',
              shacl_file='tender_shacl_shapes.ttl')
import json
tender = json.loads(Path('tenders_metadata/TO4130038_2026_ONEEBELEC.json').read_text())
g = b.build_tender_triples(tender)

lots = list(g.subjects(TS.lotID, None))
print('Lot count:', len(lots))
for lot in lots:
    print(' Lot:', lot)
    print('   lotID:', list(g.objects(lot, TS.lotID)))
    print('   lot_estimated_value:', list(g.objects(lot, TS.lot_estimated_value)))
    print('   Reserve_TPE_PME (Is_SME_Reserved):', list(g.objects(lot, TS.Is_SME_Reserved)))
print('Has_Multilot:', list(g.objects(list(g.subjects(TS.Has_Multilot, None))[0], TS.Has_Multilot)))
"
```
Expected: 3 lots, each with `lotID`, `lot_estimated_value`. Lot 1 should have `Is_SME_Reserved → ts:IsSmeReserved`.

- [ ] **Step 5: Commit**

```bash
git add kg_builder.py
git commit -m "fix: resolve smoke-test issues in kg_builder.py full mapping refactor"
```
(Only needed if Step 2 revealed and fixed bugs. Skip if no changes were made.)

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Section 2 (SkosResolver): Tasks 4
- ✅ Section 3 (OWL changes): Task 1
- ✅ Section 4 (SHACL changes): Task 2
- ✅ Section 5a (tender-level triples): Task 5
- ✅ Section 5b (buyer node triples): Task 5
- ✅ Section 5c (lot-level triples): Task 5 + `_build_lot_triples`
- ✅ Section 6 (parsing rules): Task 3 + Task 5
- ✅ exactMatch contract: emitted in Task 5 for every SKOS resolution

**Type consistency:** `SkosResolver.resolve()` returns `Optional[URIRef]` — all callers in Task 5 check for `None` before emitting triples. `_build_lot_triples` uses same resolver pattern. `parse_fr_decimal` returns `Optional[Decimal]`.

**No placeholders:** All code blocks are complete and runnable.
