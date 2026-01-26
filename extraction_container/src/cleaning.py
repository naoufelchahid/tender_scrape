import re
from typing import List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class LogicalDocument:
    original_filename: str
    content: str
    doc_type: str = "unknown"
    page_start: Optional[int] = None
    page_end: Optional[int] = None

class DocumentCleaners:
    
    @staticmethod
    def split_concatenated_file(text: str) -> List[LogicalDocument]:
        """
        Splits a concatenated OCR markdown file into logical components.
        Expected format:
        # File: filename1.docx
        ... content ...
        ---
        # File: filename2.pdf
        ...
        """
        docs = []
        # Regex to find file boundaries. 
        # Captures filename in group 1.
        pattern = r'(?m)^# File:\s*(.*?)$'
        
        matches = list(re.finditer(pattern, text))
        
        if not matches:
            # Assume single file if no headers found
            single_doc_type = DocumentCleaners.classify_document("unknown", text)
            return [LogicalDocument(original_filename="unknown", content=text, doc_type=single_doc_type)]
            
        for i, match in enumerate(matches):
            filename = match.group(1).strip()
            start_idx = match.end()
            
            # End index is start of next match or end of string
            if i + 1 < len(matches):
                end_idx = matches[i+1].start()
            else:
                end_idx = len(text)
                
            content = text[start_idx:end_idx].strip()
            
            # Clean generic separators if present at start/end
            content = re.sub(r'^---\s*', '', content)
            content = re.sub(r'\s*---$', '', content)
            
            # Extract doc_type from classification header (injected by classification container)
            # Format: > Document Type: <type>
            doc_type = "unknown"
            type_match = re.search(r'^\s*>\s*Document\s+Type:\s*(\w+)', content, re.IGNORECASE | re.MULTILINE)
            if type_match:
                doc_type = type_match.group(1).strip()
                logger.debug(f"Extracted doc_type '{doc_type}' from classification header")
            
            docs.append(LogicalDocument(
                original_filename=filename,
                content=content,
                doc_type=doc_type
            ))
            
        return docs

    @staticmethod
    def classify_document(filename: str, content: str = "") -> str:
        """Classifies document based ONLY on content analysis, ignoring filename signals."""
        if not content:
            return 'other'

        # Sample for header analysis (first 3000 chars) vs full context
        header_sample = content[:3000].lower()
        content_sample = content[:50000].lower()
        doc_length = len(content)
        
        # helper for arabic tatweel
        def clean_ar(text): 
            return re.sub(r'[\u0640]', '', text)

        clean_header = clean_ar(header_sample)
        clean_content = clean_ar(content_sample)

        # --- AVIS FILENAME PRIORITY (User Request) ---
        if "avis" in filename.lower():
             return "avis"

        # --- STRONG RC/CPS SIGNALS IN HEADER (Override Declaration/Engagement) ---
        header_rc_signals = [
            r"règlement\s+de\s+la\s+consultation",
            r"règlement\s+de\s+consultation",
            r"نظام\s+الاستشارة",
            r"cahier\s+des\s+prescriptions",
            r"clauses\s+administratives",
            r"cahier\s+des\s+charges",
            r"دفتر\s+التحملات"
        ]
        has_big_doc_header = any(re.search(p, clean_header) for p in header_rc_signals)

        # --- DECLARATION / ENGAGEMENT (Restricted) ---
        # Heuristic: These docs are usually short (< 25000 chars)
        # AND they shouldn't have a big doc header unless it's a specific form attached
        if doc_length < 25000 and not has_big_doc_header:
            
            # Engagement Check
            engagement_patterns = [
                r"acte\s+d['’]engagement",
                r"عقد\s*ـ*\s*ا?لتزام",
                r"engagement\s+du\s+concurrent",
                r"montant\s+total\s+de\s+l['’]offre", # Engagement has price
                r"l['’]offre\s+s['’]élève\s+à"
            ]
            if any(re.search(p, clean_header) for p in engagement_patterns):
                 # Ensure it's not just a mention
                 if clean_content.count("article") < 15:
                    return 'engagement'

            # Declaration Check
            declaration_patterns = [
                r"déclaration\s+sur\s+l['’]honneur",
                r"تصريح\s*ـ*\s*بالشرف",
                r"je\s+soussigné",
                r"nous\s+soussignés",
                r"أنا\s+الموقع\s+أسفله"
            ]
            if any(re.search(p, clean_header) for p in declaration_patterns):
                # Differentiate from Engagement (Verification)
                if "déclare" in clean_header or "certifie" in clean_header or "أصرح" in clean_header:
                     return 'declaration'
                if "m'engage" in clean_header and ("prix" in clean_header or "offre" in clean_header):
                    return 'engagement'
                return 'declaration'

        # --- ADMINISTRATIVE (RC) ---
        rc_patterns = [
            r"objet\s+du\s+règlement",
            r"règlement\s+de\s+la\s+consultation",
            r"règlement\s+de\s+consultation",
            r"نظام\s+الاستشارة",
            r"conditions\s+requises\s+des\s+concurrents",
            r"contenu\s+du\s+dossier\s+des\s+concurrents",
            r"critères\s+d['’]évaluation\s+des\s+offres",
            r"cautionnement\s+provisoire\s+.*article"
        ]
        is_rc = any(re.search(p, clean_content) for p in rc_patterns)

        # --- SPECIFICATION (CPS) ---
        cps_patterns = [
            r"cahier\s+des\s+prescriptions",
            r"cahier\s+des\s+charges",
            r"دفتر\s+التحملات",
            r"consistance\s+du\s+projet",
            r"clauses\s+générales",
            r"clauses\s+techniques",
            r"description\s+technique\s+des\s+prix",
            r"mode\s+de\s+passation\s+du\s+marché",
            r"programme\s+physique",
            r"nantissement",
            r"délai\s+d['’]exécution",
            r"cctp", 
            r"c\.c\.t\.p"
        ]
        is_cps = any(re.search(p, clean_content) for p in cps_patterns)

        # Disambiguation
        if is_rc and is_cps:
            if re.search(r"règlement\s+de\s+(la\s+)?consultation", clean_header) or re.search(r"نظام\s+الاستشارة", clean_header):
                return 'administrative'
            if re.search(r"cahier\s+des\s+prescriptions", clean_header) or re.search(r"دفتر\s+التحملات", clean_header):
                 return 'specification'
            # Weighted check: RC usually has more occurrences of "concurrent"
            if clean_content.count("concurrent") > clean_content.count("entrepreneur") + clean_content.count("attributaire"):
                return 'administrative'
            return 'specification'
            
        if is_rc:
            return 'administrative'
        if is_cps:
            return 'specification'

        # --- AVIS (Tender Notice) ---
        # User Request: Use filename signals "avis", "fr", "ar" to help disambiguate
        fname_lower = filename.lower()
        is_avis_filename = "avis" in fname_lower
        
        avis_patterns = [
            r"avis\s+d['’]appel\s+d['’]offres",
            r"avis\s+de\s+publicit[ée]",
            r"avis\s+d['’]achat",
            r"إعلان\s*ـ*\s*عن\s+طلب\s+عروض",
            r"إعلان\s*ـ*\s*عن\s+مزايدة",
            r"il\s+sera\s+procédé",
            r"www\.marchespublics\.gov\.ma"
        ]
        
        is_avis_content = any(re.search(p, clean_content) for p in avis_patterns)

        if is_avis_filename or is_avis_content:
            # Disambiguate from Administrative:
            # RC often contains the text of the Avis. 
            # If filename says 'avis', trust it.
            if is_avis_filename:
                return 'avis'
                
            # If content-only detection:
            # Avis are usually short. If very long, might be RC quoting Avis.
            if doc_length < 25000:
                if "règlement" in clean_header and "avis" not in clean_header:
                     # It says Regulation in header -> Administrative
                     pass 
                else:
                    return 'avis'
            else:
                 # Long document with Avis keywords. 
                 # If header explicitly looks like an Avis (not RC), it's an Avis.
                 if re.search(r"avis\s+d['’](appel|achat)", clean_header) and "règlement" not in clean_header:
                     return 'avis'

        # --- PRODUCT (BDP) ---
        bdp_indicators = [
            r"bordereau\s+des\s+prix",
            r"détail\s+estimatif",
            r"جدول\s+الأثمان",
            r"البيان\s+التقديري",
            r"désignation\s+des\s+prestations",
            r"prix\s+unitaire",
            r"désignation",
            r"total\s+ttc",
            r"total\s+h\.?t",
            r"\(chiffres\)",
            r"arrété\s+le\s+présent",
            r"arrêté\s+le\s+présent",
            r"montant\s+ht",
            r"prix\s+total",
            r"quantité",
            r"unité",
            r"u\.?m" 
        ]
        matches = sum(1 for p in bdp_indicators if re.search(p, clean_content))
        if matches >= 2:
            return 'product'

        return 'other'

    @staticmethod
    def normalize_headers(text: str) -> str:
        """Standardizes headers (Article X -> ## ARTICLE X)."""
        # Article 1..99
        text = re.sub(r'^(#+)?\s*(ARTICLE|Article)\s*(\d+)', r'## ARTICLE \3', text, flags=re.MULTILINE)
        # Arabic Chapter
        text = re.sub(r'^#\s*الباب', r'## CHAPITRE', text, flags=re.MULTILINE)
        return text
