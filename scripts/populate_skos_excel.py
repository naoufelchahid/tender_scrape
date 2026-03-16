import pandas as pd
import numpy as np
import sys

file_path = 'ontology/class.xlsx'

# Mapping defined in the implementation plan
skos_mapping = {
    ':Buyers': {
        'prefLabel': 'Acheteur Public',
        'altLabel': "Maître d'ouvrage",
        'definition': "Entité publique (ministère, établissement public, etc.) lançant l'appel d'offres."
    },
    ':Tenders': {
        'prefLabel': "Appel d'Offres",
        'altLabel': 'AO, Marché Public',
        'definition': "Procédure de passation pour attributer un marché public."
    },
    ':TenderReglement ': {
        'prefLabel': 'Règlement de Consultation',
        'altLabel': 'RC',
        'definition': "Document fixant les règles de la consultation pour les concurrents."
    },
    ':TenderSpecifications': {
        'prefLabel': 'Cahier des Prescriptions Spéciales',
        'altLabel': 'CPS, Specs',
        'definition': "Document fixant les clauses techniques et administratives du marché."
    },
    ':Bordereaux': {
        'prefLabel': 'Bordereau des Prix',
        'altLabel': 'BDP, BP',
        'definition': "Document listant les prix unitaires et forfaitaires des prestations."
    },
    ':Articles': {
        'prefLabel': 'Article de Prix',
        'altLabel': 'Ligne BDP',
        'definition': "Une ligne spécifique de prestation ou fourniture au sein du bordereau."
    },
    ':TendersAttribution ': {
        'prefLabel': 'Attribution de Marché',
        'altLabel': "Résultat d'AO",
        'definition': "Décision d'attribuer le marché à un ou plusieurs concurrents."
    },
    ':TenderResults': {
        'prefLabel': "Résultat d'Appel d'Offres",
        'altLabel': 'Décision du Jury',
        'definition': "Rapport final détaillant les concurrents retenus et écartés."
    },
    ':TenderBids': {
        'prefLabel': 'Offre Concurrent',
        'altLabel': 'Soumission',
        'definition': "Offre technique et financière déposée par un soumissionnaire."
    },
    ':TenderReferencePrice': {
        'prefLabel': "Estimation du Maître d'Ouvrage",
        'altLabel': 'Budget Estimatif',
        'definition': "Coût estimé des prestations par l'acheteur public avant l'AO."
    },
    ':TenderExecution ': {
        'prefLabel': 'Exécution du Marché',
        'altLabel': 'Déroulement',
        'definition': "Phase de réalisation des prestations une fois le marché notifié."
    },
    ':Executed': {
        'prefLabel': 'Marché Achevé',
        'altLabel': 'Réceptionné',
        'definition': "L'exécution du marché a été finalisée."
    },
    ':Resilied': {
        'prefLabel': 'Marché Résilié',
        'altLabel': 'Annulé',
        'definition': "Le marché a été interrompu prématurément."
    },
    ':TenderCategory': {
        'prefLabel': 'Catégorie de Marché',
        'altLabel': 'Type de Marché',
        'definition': "Classification du marché selon sa nature principale."
    },
    ':Travaux ': {
        'prefLabel': 'Marché de Travaux',
        'altLabel': 'Construction',
        'definition': "Marché couvrant la réalisation d'ouvrages ou de travaux."
    },
    ':Services': {
        'prefLabel': 'Marché de Services',
        'altLabel': 'Prestation',
        'definition': "Marché couvrant des prestations immatérielles (nettoyage, gardiennage)."
    },
    ':Fournitures': {
        'prefLabel': 'Marché de Fournitures',
        'altLabel': 'Achat public',
        'definition': "Marché concernant l'achat ou location de produits et matériels."
    },
    ':Contractor ': {
        'prefLabel': 'Entrepreneur',
        'altLabel': 'Concurrent, Société',
        'definition': "Entité économique soumissionnant ou exécutant le marché public."
    },
    ':BureauEtude': {
        'prefLabel': "Bureau d'Études",
        'altLabel': 'BET',
        'definition': "Structure d'ingénierie et de conseil technique."
    },
    ':BureauConsulting': {
        'prefLabel': 'Cabinet de Conseil',
        'altLabel': 'Conseil',
        'definition': "Entité fournissant des prestations intellectuelles et stratégiques."
    },
    ':Architecte': {
        'prefLabel': 'Architecte',
        'altLabel': "Cabinet d'Architecture",
        'definition': "Professionnel chargé de la conception architecturale des ouvrages."
    },
    ':Fournisseur ': {
        'prefLabel': 'Fournisseur',
        'altLabel': 'Vendor',
        'definition': "Entité fournissant des biens et matériels."
    },
    ':EntrepriseTravaux': {
        'prefLabel': 'Entreprise de Travaux',
        'altLabel': 'BTP, GC',
        'definition': "Entreprise réalisant des travaux de construction et BTP."
    },
    ':EntrepriseServices': {
        'prefLabel': 'Entreprise de Services',
        'altLabel': 'Prestataire',
        'definition': "Société fournissant des services d'entretien, IT, ou logistique."
    }
}

try:
    df = pd.read_excel(file_path, sheet_name='Sheet1')
    
    # Ensure necessary columns exist.
    required_cols = ['Skos-preflabel', 'Skos-altlabel', 'Skos-definition', 'Skos-broader']
    for col in required_cols:
        if col not in df.columns:
            df[col] = pd.NA
            
    # Cast all SKOS columns to object to avoid float assignment errors
    for col in df.columns:
        if str(col).startswith('Skos-'):
            df[col] = df[col].astype('object')
            
    # Function to extract broader class from 'Type'
    def get_broader(type_str):
        if pd.isna(type_str): return np.nan
        type_str = str(type_str).lower()
        if 'subclass of' in type_str:
            parts = type_str.split('subclass of')
            if len(parts) > 1:
                return parts[1].strip()
        return np.nan

    for idx, row in df.iterrows():
        class_name = row['Class']
        
        if class_name in skos_mapping:
            mapping = skos_mapping[class_name]
            df.at[idx, 'Skos-preflabel'] = mapping.get('prefLabel', np.nan)
            df.at[idx, 'Skos-altlabel'] = mapping.get('altLabel', np.nan)
            df.at[idx, 'Skos-definition'] = mapping.get('definition', np.nan)
            
        # extract broader
        broader = get_broader(row['Type'])
        if pd.notna(broader):
            df.at[idx, 'Skos-broader'] = broader
            
    df.to_excel(file_path, sheet_name='Sheet1', index=False)
    print("Successfully updated ontology/class.xlsx with SKOS annotations.")

except Exception as e:
    print(f"Error updating Excel: {e}")
    sys.exit(1)
