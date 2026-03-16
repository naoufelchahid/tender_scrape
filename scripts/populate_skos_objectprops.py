import pandas as pd
import numpy as np
import sys

file_path = 'ontology/class.xlsx'

skos_mapping = {
    ':Launched_by': {
        'prefLabel': 'Lancé par',
        'altLabel': 'Initié par',
        'definition': "Indique l'Acheteur (Maître d'Ouvrage) responsable du lancement de l'appel d'offres."
    },
    ':Launched': {
        'prefLabel': 'A lancé',
        'altLabel': "Est l'initiateur de",
        'definition': "Relation inverse de :Launched_by; connecte l'Acheteur à ses Appels d'Offres."
    },
    ':Has_Reglement_Consultation ': {
        'prefLabel': 'Est régi par le RC',
        'altLabel': 'A pour Règlement',
        'definition': "Lie l'appel d'offres au document fixant les règles de la consultation (RC)."
    },
    ':Is_Reglement_Consultation_Of': {
        'prefLabel': 'Est le RC de',
        'altLabel': "Régit l'AO",
        'definition': "Relation inverse; lie le Règlement de Consultation à son Appel d'Offres."
    },
    ':Has_specifications': {
        'prefLabel': 'Contient les spécifications CPS',
        'altLabel': 'Régi par le CPS',
        'definition': "Lie l'appel d'offres au Cahier des Prescriptions Spéciales (CPS)."
    },
    ':Is_specifications_of': {
        'prefLabel': 'Est le CPS de',
        'altLabel': "Spécifie l'AO",
        'definition': "Relation inverse; lie le Cahier des Prescriptions Spéciales à son Appel d'Offres."
    },
    ':Has_Bordereau': {
        'prefLabel': 'Contient un BDP',
        'altLabel': 'Inclut le Bordereau',
        'definition': "Lie l'Appel d'Offres ou le CPS au Bordereau des Prix (BDP)."
    },
    ':Is_Bordereau_of ': {
        'prefLabel': 'Est le BDP de',
        'altLabel': 'BDP rattaché à',
        'definition': "Relation inverse; lie le Bordereau des Prix à l'appel d'offres correspondant."
    },
    ':Has_Article': {
        'prefLabel': 'Contient une ligne de prix',
        'altLabel': "Comprend l'article",
        'definition': "Lie le Bordereau des Prix à ses articles ou lignes de prestations spécifiques."
    },
    ':Is_Article_of': {
        'prefLabel': 'Fait partie du BDP',
        'altLabel': 'Ligne du Bordereau',
        'definition': "Relation inverse; connecte un article de prix au Bordereau des Prix parent."
    },
    ':Is_Opened': {
        'prefLabel': 'A été ouvert lors du PV',
        'altLabel': 'Plis ouverts (PV)',
        'definition': "Lie l'Appel d'Offres au Procès-Verbal d'ouverture des plis."
    },
    ':Is_Proces_Verbal_of ': {
        'prefLabel': "Est le PV d'ouverture de",
        'altLabel': "PV relatif à l'AO",
        'definition': "Relation inverse; lie le Procès-Verbal à l'Appel d'Offres concerné."
    },
    ':Is Awarded_to': {
        'prefLabel': 'Est attribué à',
        'altLabel': 'Adjugé à',
        'definition': "Lie l'Appel d'Offres au Concurrent (Entrepreneur) retenu comme attributaire."
    },
    ':Is_Bid_in ': {
        'prefLabel': 'A été soumissionnée pour',
        'altLabel': 'Offre déposée pour',
        'definition': "Lie une Offre (Soumission) à l'Appel d'Offres ou Lot correspondant."
    },
    ':Has_Bid': {
        'prefLabel': 'A reçu comme Offre',
        'altLabel': 'Offres déposées',
        'definition': "Relation inverse; lie l'Appel d'Offres aux offres concurrentes déposées."
    },
    ':Rejected_Bid': {
        'prefLabel': "A rejeté l'offre",
        'altLabel': 'Offre écartée',
        'definition': "Lie l'Appel d'Offres (via le jury) à une offre qui a été écartée lors de l'évaluation."
    },
    ':Is_Rejected_Bid': {
        'prefLabel': 'Est une offre écartée de',
        'altLabel': "Rejeté pour l'AO",
        'definition': "Relation inverse; indique qu'une offre spécifique a été rejetée pour un AO donné."
    },
    ':Is_Winner_Bid': {
        'prefLabel': "Est l'offre retenue pour",
        'altLabel': 'Soumission gagnante',
        'definition': "Indique que l'offre a été retenue et a remporté l'Appel d'Offres."
    },
    ':Formulate_Bid': {
        'prefLabel': "A formulé l'offre",
        'altLabel': 'Soumet',
        'definition': "Lie le Concurrent (Entrepreneur) à l'Offre (Soumission) qu'il a préparée."
    },
    ':Is_Bid_of': {
        'prefLabel': "Est l'offre de",
        'altLabel': 'Soumis par',
        'definition': "Relation inverse; lie l'Offre à l'Entrepreneur (Concurrent) qui l'a déposée."
    }
}

try:
    with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        df = pd.read_excel(file_path, sheet_name='ObjectPropreties')
        
        required_cols = ['Skos-preflabel', 'Skos-altlabel', 'Skos-definition']
        for col in required_cols:
            if col not in df.columns:
                df[col] = pd.NA
                
        for col in df.columns:
            if str(col).startswith('Skos-'):
                df[col] = df[col].astype(object)
                
        for idx, row in df.iterrows():
            prop_name = row['ObjectPropreties ']
            if prop_name in skos_mapping:
                mapping = skos_mapping[prop_name]
                df.at[idx, 'Skos-preflabel'] = mapping.get('prefLabel', np.nan)
                df.at[idx, 'Skos-altlabel'] = mapping.get('altLabel', np.nan)
                df.at[idx, 'Skos-definition'] = mapping.get('definition', np.nan)
                
        df.to_excel(writer, sheet_name='ObjectPropreties', index=False)
        
    print("Successfully populated ObjectPropreties sheet with SKOS annotations.")
    
except Exception as e:
    print(f"Error updating Excel: {e}")
    sys.exit(1)
