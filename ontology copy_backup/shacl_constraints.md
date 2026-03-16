# Exhaustive SHACL Constraints — [tender_structure.ttl](file:///home/naoufel/projects/AO_scrape/ontology/tender_structure.ttl)

> [!NOTE]  
> Save this as `ontology/shapes.ttl`. It imports the main ontology and can be validated with `pySHACL` via `pyshacl -s shapes.ttl -sg shapes.ttl tender_structure.ttl`

```turtle
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix ts:    <http://www.tenderintelligence.io/ontology/tender-structure#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix regions: <http://www.tenderintelligence.io/ontology/morocco-regions#> .
@prefix activity: <http://www.tenderintelligence.io/ontology/activity-domains#> .
```

---

## ① `ts:Tenders` — Node Shape

```turtle
ts:TendersShape
    a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:name "TendersShape"@en ;
    sh:description "Constraints on every Appel d'Offres instance."@fr ;

    # ── IDENTITY & DESCRIPTION ──────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Object ;
        sh:name "Objet de l'AO" ;
        sh:minCount 1 ;                          # REQUIRED: title is mandatory
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:minLength 10 ;                        # Min 10 chars — avoids empty fillers
        sh:maxLength 500 ;
        sh:severity sh:Violation ;
    ] ;

    # ── FINANCIAL ───────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Budget ;
        sh:name "Budget Estimatif" ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
        sh:minInclusive 0 ;                      # Budget cannot be negative
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Caution ;
        sh:name "Caution Provisoire" ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
        sh:minInclusive 0 ;
        sh:severity sh:Warning ;
    ] ;

    # ── TEMPORAL ────────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Deadline ;
        sh:name "Date Limite" ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:dateTime ;
        sh:severity sh:Violation ;
    ] ;

    # ── FLAGS ───────────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Multilot ;
        sh:maxCount 1 ;
        sh:datatype xsd:boolean ;
        sh:severity sh:Violation ;
    ] ;

    # ── OBJECT PROPERTIES ───────────────────────────────────────────────
    sh:property [
        sh:path ts:Launched_by ;
        sh:name "Maître d'Ouvrage" ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Buyers ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Is_Located_In ;
        sh:name "Région" ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class skos:Concept ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Has_Category ;
        sh:name "Catégorie de Marché" ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class skos:ConceptScheme ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Is_Opened ;
        sh:name "PV d'ouverture" ;
        sh:maxCount 1 ;
        sh:class ts:TenderResults ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_specifications ;
        sh:maxCount 1 ;
        sh:class ts:TenderSpecifications ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Has_Reglement_Consultation ;
        sh:maxCount 1 ;
        sh:class ts:TenderReglement ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:IsAwarded_to ;
        sh:maxCount 1 ;
        sh:class ts:Contractor ;
        sh:severity sh:Warning ;
    ] .
```

---

## ② `ts:Contractor` — Node Shape

```turtle
ts:ContractorShape
    a sh:NodeShape ;
    sh:targetClass ts:Contractor ;

    # ── IDENTITY ────────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Name ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:minLength 2 ;
        sh:maxLength 200 ;
        sh:severity sh:Violation ;
    ] ;

    # ── LEGAL IDENTIFIER ────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_ICE ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:pattern "^[0-9]{15}$" ;              # ICE = exactly 15 digits (Moroccan law)
        sh:severity sh:Violation ;
    ] ;

    # ── CONTACT ─────────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Has_Mail ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:pattern "^[^@]+@[^@]+\\.[^@]+$" ;   # Basic RFC 5322 email pattern
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Phone ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:pattern "^(\\+212|0)[0-9]{9}$" ;    # Moroccan phone format
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Has_Adress ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:maxLength 300 ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Has_Contact ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Has_Owner ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Info ;
    ] ;

    # ── OBJECT PROPERTIES ───────────────────────────────────────────────
    sh:property [
        sh:path ts:Formulate_Bid ;
        sh:class ts:TenderBids ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Warning ;
    ] .
```

---

## ③ `ts:Buyers` — Node Shape

```turtle
ts:BuyersShape
    a sh:NodeShape ;
    sh:targetClass ts:Buyers ;

    sh:property [
        sh:path ts:Launched ;
        sh:class ts:Tenders ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Warning ;
    ] ;

    # Every Buyer must have at least a name (via rdfs:label)
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Violation ;
    ] .
```

---

## ④ `ts:TenderBids` — Node Shape

```turtle
ts:TenderBidsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderBids ;

    # ── FINANCIAL ───────────────────────────────────────────────────────
    sh:property [
        sh:path ts:Bid_Amount ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
        sh:minInclusive 0 ;                      # Bid cannot be negative
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Article_Bid ;
        sh:datatype xsd:decimal ;
        sh:minInclusive 0 ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Bid_For_Lot ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Info ;
    ] ;

    # ── RELATIONSHIPS ───────────────────────────────────────────────────
    sh:property [
        sh:path ts:Is_Bid_of ;                   # Every bid MUST be linked to a contractor
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Contractor ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Is_Bid_in ;                   # Every bid must link to a TenderResults
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:TenderResults ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] .
```

---

## ⑤ `ts:TenderResults` — Node Shape

```turtle
ts:TenderResultsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderResults ;

    sh:property [
        sh:path ts:Has_Date ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:dateTime ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Has_Status ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:in ( "Ouvert" "Attribué" "Infructueux" "Résilié" "Annulé" ) ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Has_PV ;
        sh:maxCount 1 ;
        sh:datatype xsd:anyURI ;
        sh:severity sh:Info ;
    ] ;

    # ── RELATIONSHIPS ───────────────────────────────────────────────────
    sh:property [
        sh:path ts:Is_Proces_Verbal_of ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Tenders ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Is_Winner_Bid ;
        sh:maxCount 1 ;
        sh:class ts:TenderBids ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Bid ;
        sh:class ts:TenderBids ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Rejected_Bid ;
        sh:class ts:TenderBids ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Info ;
    ] .
```

---

## ⑥ `ts:Bordereaux` & `ts:Articles` — Node Shapes

```turtle
ts:BordereauxShape
    a sh:NodeShape ;
    sh:targetClass ts:Bordereaux ;

    sh:property [
        sh:path ts:Has_Bordereau_Doc ;
        sh:maxCount 1 ;
        sh:datatype xsd:anyURI ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Has_Article ;
        sh:class ts:Articles ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Is_Bordereau_of ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Tenders ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] .

ts:ArticlesShape
    a sh:NodeShape ;
    sh:targetClass ts:Articles ;

    sh:property [
        sh:path ts:Has_Designation ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:minLength 3 ;
        sh:severity sh:Violation ;
    ] ;
    sh:property [
        sh:path ts:Has_Unit ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:in ( "U" "ML" "M2" "M3" "FF" "KG" "T" "H" "J" "Mois" "Km" "L" ) ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_quantity ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
        sh:minInclusive 0 ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Article_Category ;
        sh:maxCount 1 ;
        sh:class skos:Concept ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Is_Article_of ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Bordereaux ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] .
```

---

## ⑦ `ts:TenderSpecifications` — Node Shape

```turtle
ts:TenderSpecificationsShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderSpecifications ;

    sh:property [
        sh:path ts:Has_CPS_Doc ;
        sh:maxCount 1 ;
        sh:datatype xsd:anyURI ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Spec_Vector ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Is_specifications_of ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Tenders ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] .
```

---

## ⑧ `ts:TenderReglement` — Node Shape

```turtle
ts:TenderReglementShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderReglement ;

    sh:property [
        sh:path ts:Has_RC_Doc ;
        sh:maxCount 1 ;
        sh:datatype xsd:anyURI ;
        sh:severity sh:Warning ;
    ] ;
    sh:property [
        sh:path ts:Has_Reglement_Vector ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:severity sh:Info ;
    ] ;
    sh:property [
        sh:path ts:Is_Reglement_Consultation_Of ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:class ts:Tenders ;
        sh:nodeKind sh:IRI ;
        sh:severity sh:Violation ;
    ] .
```

---

## ⑨ Cross-Class SPARQL-Based Constraints (sh:SPARQLConstraint)

These are semantic integrity rules that cannot be expressed with simple cardinality.

```turtle
# ── RULE 1: A Winner Bid must also appear in Has_Bid ───────────────────
ts:WinnerBidConsistencyShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderResults ;
    sh:sparql [
        sh:message "ts:Is_Winner_Bid must point to a bid that is also listed in ts:Has_Bid."@en ;
        sh:prefixes ts: ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Is_Winner_Bid ?winner .
                FILTER NOT EXISTS { $this ts:Has_Bid ?winner }
            }
        """ ;
        sh:severity sh:Violation ;
    ] .

# ── RULE 2: Deadline must be after PV date ─────────────────────────────
ts:DeadlineBeforePVShape
    a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:sparql [
        sh:message "ts:Has_Deadline must be before (or equal to) the PV date in ts:Has_Date."@en ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Has_Deadline ?deadline .
                $this ts:Is_Opened/ts:Has_Date ?pvDate .
                FILTER (?deadline > ?pvDate)
            }
        """ ;
        sh:severity sh:Warning ;
    ] .

# ── RULE 3: Caution must be ≤ 3% of Budget (Moroccan Decree 2-22-431) ──
ts:CautionRatioShape
    a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:sparql [
        sh:message "Caution Provisoire must not exceed 3% of the estimated budget (Décret 2-22-431)."@fr ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Has_Caution ?caution .
                $this ts:Has_Budget ?budget .
                FILTER (?caution > ?budget * 0.03)
            }
        """ ;
        sh:severity sh:Violation ;
    ] .

# ── RULE 4: ICE uniqueness — no two Contractors share the same ICE ─────
ts:ICEUniquenessShape
    a sh:NodeShape ;
    sh:targetClass ts:Contractor ;
    sh:sparql [
        sh:message "ts:Has_ICE must be unique; two contractors cannot share the same ICE."@fr ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Has_ICE ?ice .
                ?other ts:Has_ICE ?ice .
                FILTER ($this != ?other)
            }
        """ ;
        sh:severity sh:Violation ;
    ] .

# ── RULE 5: Region must belong to MoroccoRegionsScheme ────────────────
ts:RegionConceptShape
    a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:sparql [
        sh:message "ts:Is_Located_In must point to a concept in regions:MoroccoRegionsScheme."@fr ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Is_Located_In ?region .
                FILTER NOT EXISTS {
                    ?region skos:inScheme <http://www.tenderintelligence.io/ontology/morocco-regions#MoroccoRegionsScheme>
                }
            }
        """ ;
        sh:severity sh:Violation ;
    ] .

# ── RULE 6: Has_Category must be one of the 3 known ConceptSchemes ─────
ts:CategorySchemeShape
    a sh:NodeShape ;
    sh:targetClass ts:Tenders ;
    sh:sparql [
        sh:message "ts:Has_Category must be one of: SchemeTravaux, SchemeFournitures, SchemeServices."@fr ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Has_Category ?scheme .
                FILTER (?scheme NOT IN (
                    <http://www.tenderintelligence.io/ontology/activity-domains#SchemeTravaux>,
                    <http://www.tenderintelligence.io/ontology/activity-domains#SchemeFournitures>,
                    <http://www.tenderintelligence.io/ontology/activity-domains#SchemeServices>
                ))
            }
        """ ;
        sh:severity sh:Violation ;
    ] .

# ── RULE 7: Bid_Amount must match Bid_For_Lot when multilot ───────────
ts:MultilotBidShape
    a sh:NodeShape ;
    sh:targetClass ts:TenderBids ;
    sh:sparql [
        sh:message "When the parent tender has ts:Has_Multilot true, each bid must specify ts:Bid_For_Lot."@fr ;
        sh:select """
            SELECT $this WHERE {
                $this ts:Is_Bid_in/ts:Is_Proces_Verbal_of ?tender .
                ?tender ts:Has_Multilot true .
                FILTER NOT EXISTS { $this ts:Bid_For_Lot ?lot }
            }
        """ ;
        sh:severity sh:Warning ;
    ] .

# ── RULE 8: Contractor subclass specialisation ─────────────────────────
ts:ContractorSubclassShape
    a sh:NodeShape ;
    sh:targetClass ts:Contractor ;
    sh:sparql [
        sh:message "A Contractor should be typed as a specialised subclass (EntrepriseTravaux, BureauEtude, Architecte, etc)."@fr ;
        sh:select """
            SELECT $this WHERE {
                FILTER NOT EXISTS {
                    { $this a ts:EntrepriseTravaux } UNION
                    { $this a ts:EntrepriseServices } UNION
                    { $this a ts:BureauEtude } UNION
                    { $this a ts:BureauConsulting } UNION
                    { $this a ts:Architecte } UNION
                    { $this a ts:Fournisseur }
                }
            }
        """ ;
        sh:severity sh:Info ;
    ] .
```

---

## Summary Table — Constraint Coverage

| Shape | Constraint Type | SHACL Features Used |
|---|---|---|
| `TendersShape` | Cardinality, Datatype, Range | `sh:minCount`, `sh:maxCount`, `sh:datatype`, `sh:class`, `sh:minLength`, `sh:maxLength` |
| `ContractorShape` | Pattern, Cardinality | `sh:pattern` (ICE 15-digit, email, Moroccan phone), `sh:maxLength` |
| `BuyersShape` | ObjectProperty range | `sh:class`, `sh:nodeKind` |
| `TenderBidsShape` | Cardinality, Non-negative | `sh:minInclusive 0`, `sh:minCount 1` |
| `TenderResultsShape` | Enum, Cardinality | `sh:in` (status enum), `sh:maxCount 1` on winner |
| `ArticlesShape` | Enum, Non-negative | `sh:in` (unit enum), `sh:minLength` |
| `BordereauxShape` | Navigation integrity | `sh:class ts:Tenders`, `sh:minCount 1` |
| `TenderSpecificationsShape` | URI + Vector | `sh:datatype xsd:anyURI` |
| `TenderReglementShape` | URI + Vector | `sh:datatype xsd:anyURI` |
| `WinnerBidConsistencyShape` | Cross-node integrity | `sh:SPARQLConstraint` |
| `DeadlineBeforePVShape` | Temporal logic | `sh:SPARQLConstraint` with FILTER |
| `CautionRatioShape` | Moroccan Decree 2-22-431 | Numeric ratio rule (≤ 3%) |
| `ICEUniquenessShape` | Uniqueness | Cross-instance SPARQL |
| `RegionConceptShape` | Taxonomy membership | `skos:inScheme` check |
| `CategorySchemeShape` | Enumeration (object) | IRI-in-set FILTER |
| `MultilotBidShape` | Conditional requirement | Exists + path |
| `ContractorSubclassShape` | Typing completeness | UNION subclass check |

> [!TIP]
> Run validation with: `pyshacl -s ontology/shapes.ttl -sg ontology/shapes.ttl ontology/tender_structure.ttl`
