# Tender Metadata Taxonomy (Moroccan Procurement Portal)

Based on browser exploration across **Services**, **Travaux**, and **Fournitures** categories, the following fields are available for extraction from the tender detail page (primarily in the `infosPrincipales` section).

## 1. Core Metadata

| Field Label | Proposed Mapping | Description | Selector/Identifier |
|-------------|------------------|-------------|---------------------|
| `Référence` | reference | Unique identifier. | `div#infosPrincipales` label "Référence" |
| `Objet` | `object` | Tender goal. | `div#infosPrincipales` label "Objet :" |
| `Acheteur public` obj | buyer | Launching org. | `div#infosPrincipales` label "Acheteur public :" |
| `Lieu d'exécution`obj | `city` | Locations. | `div#infosPrincipales` label "Lieu d'exécution :" |
| `Limite remise plis` | deadline | Submission deadline. | `div#infosPrincipales` label "Date et heure limite..." |
| `Publié le` | `launch_date` | Announcement date. | Search results table |

## 2. Procedure & Requirements

| Field Label | Proposed Mapping | Description | Selector/Identifier |
|-------------|------------------|-------------|---------------------|
| `Type d'annonce` | `consultation_type_raw` | e.g. "Annonce de..." | `div#infosPrincipales` label "Type d'annonce :" |
| `Procédure` | `mode_passation` | e.g. "AO ouvert" | `div#infosPrincipales` label "Procédure :" |
| `Catégorie principale obj`| `` | Services/Travaux/etc. | `div#infosPrincipales` label "Catégorie principale :" |
| `Allotissement`obj | `consultation_type` | Unique or Batch. | `div#infosPrincipales` label "Allotissement :" |
| `Domaines d'activité`obj | `activity_domains` | Industry sectors. | `div#infosPrincipales` label "Domaines d'activité :" |
| `SME Reserved` | `is_sme_reserved` | SME exclusion flag. | Details table row (if exists) |

## 3. Submission & Logistics

| Field Label | Proposed Mapping | Description | Selector/Identifier |
|-------------|------------------|-------------|---------------------|
| `Adresse dépôt` | `mode_soumission` | Electronic mapping. | `div#infosPrincipales` label "Adresse de dépôt..." |
| `Lieu ouverture` | `opening_location` | Bid opening spot. | `div#infosPrincipales` label "Lieu d'ouverture..." |
| `Contact Admin` | `contacts` | Phone/Email/Name. | `div#infosPrincipales` label "Contact Administratif :" |

## 4. Financials

| Field Label | Proposed Mapping | Description | Selector/Identifier |
|-------------|------------------|-------------|---------------------|
| `Estimation` | `estimated_value` | Global budget. | `div#infosPrincipales` label "Estimation..." |
| `Prix plans` | `plan_cost` | Fee for docs. | `div#infosPrincipales` label "Prix d'acquisition..." |
| `Caution` | `provisional_deposit` | Global deposit. | `div#infosPrincipales` label "Caution provisoire :" |

## 5. Lot Metadata (Popup)

| Field Label | Proposed Mapping | Description | Selector/Identifier |
|-------------|------------------|-------------|---------------------|
| `Lot X :` | `lot_title` | Lot name/number. | `span.blue.bold` (matches "Lot X") |
| `Catégorie` | `lot_category` | Lot category. | Popup label "Catégorie :" |
| `Description` | `lot_description` | Lot goal. | Popup label "Description :" |
| `Estimation` | `lot_estimated_value` | Lot budget. | Popup label "Estimation..." |
| `Caution` | `lot_provisional_deposit`| Lot deposit. | Popup label "Caution provisoire :" |
| `Qualifications` | `lot_qualifications` | Lot requirements. | Popup label "Qualifications :" |
| `Agréments` | `lot_agrements` | Lot approvals. | Popup label "Agréments :" |
| `Réunion` | `lot_meeting_date` | Meeting info. | Popup label "Réunion :" |
| `Visites` | `lot_site_visit` | Visit info. | Popup label "Visites des lieux :" |
| `Variante` | `lot_variant_allowed` | Variant flag. | Popup label "Variante :" |
| `Considérations env` | `lot_env_considerations`| Env obligations. | Popup label "Considérations env..." |
| `SME Reserved` | `lot_is_sme_reserved` | SME flag. | Popup label "Réservé à la TPE..." |

## Proposed Cleaning Rules

1. **Object**: Remove repetitive "Objet :", "objet ::", and leading/trailing colons.
2. **City**: Split by commas/dots and take the first item to avoid duplications like "Rabat...Rabat".
3. **Dates**: Convert `DD/MM/YYYY HH:MM` (deadline) and `DD/MM/YYYY` (launch) to full ISO `YYYY-MM-DDTHH:MM:SS`.
4. **Boolean Mapping**: Detect "Oui" / "Non" or specific keyword presence for `is_sme_reserved`, `mode_soumission`, and lot-level flags.
