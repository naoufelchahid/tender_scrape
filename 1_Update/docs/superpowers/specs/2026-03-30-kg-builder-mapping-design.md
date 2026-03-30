# kg_builder.py Refactor — Full JSON→RDF Mapping Design

**Date:** 2026-03-30
**Scope:** Refactor `kg_builder.py` to map all fields from `Db_updater.py` per-tender JSON output to RDF triples, with new ontology properties where needed.

---

## 1. Architecture

**Approach:** In-place refactor of `kg_builder.py`. No new files.

Add a `SkosResolver` class instantiated once in `KGBuilder.__init__`. It parses `tender_structure_final.owl` once and builds 5 normalized-label → URIRef lookup dicts. `build_tender_triples()` is fully replaced with the new comprehensive mapping.

A subagent handles all OWL edits (`tender_structure_final.owl` + `tender_shacl_shapes.ttl`) before the Python refactor is written.

---

## 2. SkosResolver Class

Responsibility: parse OWL at init, expose `resolve(scheme, label) → Optional[URIRef]`.

**Five lookup dicts built at init:**

| Dict name | Scheme / source |
|---|---|
| `regions` | `morocco-regions#Scheme` (city-level narrower concepts) |
| `activity` | All 3 activity domain schemes combined |
| `mode_passation` | `ts:ModeDePassationScheme` |
| `qualifications` | `qualif:QualificationSystem` — QualificationCategory subtree |
| `agrements` | `qualif:QualificationSystem` — Agrement subtree |

**Normalization:** NFKD accent stripping + lowercase + collapse whitespace. Applied at index build time and at query time.

**Fallback contract:** when `resolve()` returns `None`, caller emits a `xsd:string` literal on the corresponding fallback data property. Nothing is silently dropped.

---

## 3. Ontology Changes (tender_structure_final.owl)

### 3a. Replace DataProperty → ObjectProperty

- `ts:Has_Mode_Passation`: remove existing `owl:DatatypeProperty` declaration, add `owl:ObjectProperty` with `rdfs:domain ts:Tenders`, `rdfs:range skos:Concept`.

### 3b. New ObjectProperties

| Property | Domain | Range |
|---|---|---|
| `ts:Has_Activity_Domain` | `ts:Tenders` | `skos:Concept` |
| `ts:Has_Qualification` | `ts:Tenders ∪ ts:Lots` | `skos:Concept` |
| `ts:Has_Agrement` | `ts:Tenders ∪ ts:Lots` | `skos:Concept` |
| `ts:Is_SME_Reserved` | `ts:Tenders ∪ ts:Lots` | `skos:Concept` |

### 3c. New DataProperties

| Property | Domain | Range |
|---|---|---|
| `ts:retrait_address` | `ts:Tenders` | `xsd:string` |
| `ts:depot_address` | `ts:Tenders` | `xsd:string` |
| `ts:samples_info` | `ts:Tenders ∪ ts:Lots` | `xsd:string` |

### 3d. New Named Individual

```
ts:IsSmeReserved
  rdf:type owl:NamedIndividual, skos:Concept
  skos:inScheme ts:ReserveTPEScheme
  skos:prefLabel "Réservé TPE/PME"@fr
  skos:topConceptOf ts:ReserveTPEScheme
```

### 3e. Verify Existing Buyer Properties

Confirm `rdfs:domain` of `ts:Has_Contact`, `ts:Has_Mail`, `ts:Has_Phone`, `ts:Has_Adress` includes or is compatible with `ts:Buyers`. Update if restricted to `ts:Buyer` (singular) only.

---

## 4. SHACL Changes (tender_shacl_shapes.ttl)

### BuyerShape — add optional constraints
```turtle
sh:property [
    sh:path ts:Has_Contact ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:Has_Mail ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:Has_Phone ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:Has_Adress ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
```

### TenderShape — add optional constraints
```turtle
sh:property [
    sh:path ts:Has_Activity_Domain ; sh:class skos:Concept ] ;
sh:property [
    sh:path ts:Has_Mode_Passation ; sh:class skos:Concept ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:Is_SME_Reserved ; sh:class skos:Concept ; sh:maxCount 1 ] ;
```

### LotShape — add optional constraints
```turtle
sh:property [
    sh:path ts:Has_Qualification ; sh:class skos:Concept ] ;
sh:property [
    sh:path ts:Has_Agrement ; sh:class skos:Concept ] ;
sh:property [
    sh:path ts:Is_SME_Reserved ; sh:class skos:Concept ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:lot_env_considerations ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
sh:property [
    sh:path ts:samples_info ; sh:datatype xsd:string ; sh:maxCount 1 ] ;
```

### Alignment gap fix
TenderShape currently uses `sh:path ts:buyer → sh:class ts:Buyer`. Add a parallel constraint for `ts:Launched_by → ts:Buyers` to match the actual code pattern, or replace the existing one.

---

## 5. Complete Field Mapping

### 5a. Tender-Level Triples

| JSON field | Triple predicate | Type | Fallback |
|---|---|---|---|
| `reference` | `ts:Ref` | data xsd:string | — |
| `original_reference` | `ts:Has_Original_Reference` | data xsd:string | — |
| `buyer` (after first ` - `) | `ts:Launched_by` → `ts:Buyers` node | object | — |
| `main_category` | `ts:Has_Category` → `activity:Travaux/Fournitures/Services` | object | skipped |
| `launch_date` | `ts:launch_date` | data xsd:dateTime | skipped if unparseable |
| `object` | `ts:Has_Object` | data xsd:string | — |
| `city` | `ts:Is_Located_In` → regions concept | object | `ts:city` literal |
| `all_cities` (each) | `ts:Is_Located_In` → regions concept | object | `ts:city` literal |
| `deadline` | `ts:Has_Deadline` | data xsd:dateTime | skipped |
| `mode_passation` (strip `\| `) | `ts:Has_Mode_Passation` → ModeDePassation concept | object | `ts:mode_passation` literal |
| `activity_domains` (last segment each) | `ts:Has_Activity_Domain` → activity concept | object | `ts:activity_domains` literal |
| `is_sme_reserved=true` | `ts:Is_SME_Reserved` → `ts:IsSmeReserved` | object | — |
| `retrait_address` | `ts:retrait_address` | data xsd:string | — |
| `depot_address` | `ts:depot_address` | data xsd:string | — |
| `mode_soumission` | `ts:mode_soumission` | data xsd:string | — |
| `opening_location` | `ts:opening_location` | data xsd:string | — |
| `estimated_value` | `ts:estimated_value` | data xsd:decimal (parse FR format) | — |
| `plan_cost` | `ts:plan_cost` | data xsd:string | — |
| `provisional_deposit` | `ts:provisional_deposit` | data xsd:decimal | — |
| `qualifications` (3rd segment each) | `ts:Has_Qualification` → qualification concept | object | `ts:Has_Qualifications` literal |
| `agrements` (3rd segment each) | `ts:Has_Agrement` → agrement concept | object | `ts:requiredAgrements` literal |
| `variante` ("Oui"→True) | `ts:hasVariante` | data xsd:boolean | — |
| `reunion` | `ts:reunionDetails` | data xsd:string | — |
| `site_visit` | `ts:visiteLieuxDetails` | data xsd:string | — |
| `samples_info` | `ts:samples_info` | data xsd:string | — |
| `download_available` | `ts:Has_Is_Documents` | data xsd:boolean | — |
| `s3_folder` | `ts:Has_CPS_Doc` | data xsd:anyURI | — |
| `lots` (len > 1) | `ts:Has_Multilot` | data xsd:boolean | always emitted |

### 5b. Buyer Node Triples (on the `ts:Buyers` individual linked via `ts:Launched_by`)

| Source | Predicate | Type |
|---|---|---|
| buyer name (after first ` - `) | `rdfs:label` | required per SHACL |
| `contacts.name` | `ts:Has_Contact` | data xsd:string |
| `contacts.email` | `ts:Has_Mail` | data xsd:string |
| `contacts.phone` | `ts:Has_Phone` | data xsd:string |
| `opening_location` | `ts:Has_Adress` | data xsd:string |

### 5c. Lot-Level Triples (one `ts:Lots` node per entry, linked via `ts:Has_lot`)

Dynamic key parsing: lot number `n` (1-based) → keys `lot{n}_object`, `Lot{n}_estimation`, `Lot{n}_caution`, `Lot{n}_qualification`, `Lot{n}_agreement`.

| Lot key | Triple predicate | Type | Fallback |
|---|---|---|---|
| `"lot number"` | `ts:lotID` | data xsd:string | required per SHACL |
| `lot{n}_object` | `ts:lot_description` | data xsd:string | — |
| `Lot{n}_estimation` | `ts:lot_estimated_value` | data xsd:decimal (parse FR) | — |
| `Lot{n}_caution` | `ts:lot_provisional_deposit` | data xsd:decimal (parse FR) | — |
| `Lot{n}_qualification` | `ts:Has_Qualification` → qualification concept | object | `ts:lot_qualifications` literal |
| `Lot{n}_agreement` | `ts:Has_Agrement` → agrement concept | object | `ts:lot_agrements` literal |
| `Procpectus_et_echantillons` | `ts:samples_info` | data xsd:string | — |
| `Reunion` | `ts:lot_meeting_date` | data xsd:dateTime | — |
| `visite_des_lieux` | `ts:lot_site_visit` | data xsd:dateTime | — |
| `variante` | `ts:lot_variant_allowed` | data xsd:boolean (Oui/Non) | — |
| `Env_consideration` | `ts:lot_env_considerations` | data xsd:string | — |
| `Reserve_TPE_PME` = "Oui" | `ts:Is_SME_Reserved` → `ts:IsSmeReserved` | object | — |

---

## 6. Parsing Rules

- **Buyer name:** `buyer.split(" - ", 1)[1]` → everything after first ` - `
- **FR decimal:** strip spaces + replace `,` with `.` → `Decimal("114956868.00")`
- **mode_passation:** `lstrip("| ").strip()`
- **activity_domains last segment:** `domain_str.split(" / ")[-1].strip()`
- **qualifications 3rd segment:** `qual_str.split(" / ")[2].strip()` (index 2); fallback to full string if fewer than 3 segments
- **agrements 3rd segment:** same pattern
- **main_category → SKOS topConcept:** `{"Travaux": activity:Travaux, "Fournitures": activity:Fournitures, "Services": activity:Services}`
- **boolean from string:** `"Oui" → True`, `"Non" → False`, `null → skip`
- **dateTime:** try `datetime.fromisoformat()`, then `%d/%m/%Y %H:%M`, then malformed date fix (insert space before time if missing)

---

## 7. Unused Ontology Properties

These exist in the ontology but are not populated by Phase 2 JSON:

**Tender — data properties:**
- `ts:consultation_type_raw` — `procedure_type` intentionally dropped
- `ts:Has_RC_Doc`, `ts:Has_Bordereau_Doc`, `ts:Has_Bordereau_Content` — no Phase 2 source
- `ts:prospectusDocuments`, `ts:Has_Product_Header` — no Phase 2 source
- `ts:Has_Duration_Days` — computable but not stored
- `ts:environmentalConsiderations` — only at lot level in JSON
- `ts:Has_Status`, `ts:Has_PV` — Phase 3/4 pipeline fields
- `ts:Has_Spec_Vector`, `ts:Has_Reglement_Vector`, `ts:Has_Chunk_Identifier`, `ts:Has_Chunk_Vector_Ref` — embedding pipeline

**Tender — object properties:**
- `ts:Has_specifications`, `ts:Has_Reglement_Consultation`, `ts:Has_Timeline`, `ts:Has_Bordereau` — require document parsing
- `ts:Includes_Article_Category` — populated from Bordereaux

**Lots — properties:**
- `ts:lot_title` — no distinct title field in JSON
- `ts:lot_category` — not extracted by Db_updater
- `ts:lot_is_sme_reserved` (boolean DataProperty) — superseded by `ts:Is_SME_Reserved` SKOS object property

**Buyer — properties:**
- `ts:Has_ICE` — ICE tax ID not extracted in Phase 2
- `ts:Has_Name` — using `rdfs:label` instead

**Unused JSON fields (not mapped):**
- `procedure_type`, `category`, `processed_at`, `downloadable_files`, `contacts.fax`
