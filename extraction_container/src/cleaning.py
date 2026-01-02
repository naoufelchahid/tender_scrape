import re
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class LogicalDocument:
    original_filename: str
    content: str
    doc_type: str = "unknown"

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
            return [LogicalDocument(original_filename="unknown", content=text)]
            
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
            
            doc_type = DocumentCleaners.classify_document(filename, content)
            
            docs.append(LogicalDocument(
                original_filename=filename,
                content=content,
                doc_type=doc_type
            ))
            
        return docs

    @staticmethod
    def classify_document(filename: str, content: str = "") -> str:
        """Classifies document based on filename keywords and content analysis.
        
        Returns one of: specification, administrative, product, avis, engagement, declaration, other
        """
        fname = filename.lower()
        
        # Check exclusion types first (engagement and declaration)
        if any(x in fname for x in ['declaration', 'honneur', 'attestation']):
            return 'declaration'
        if any(x in fname for x in ['engagement', 'acte engagement', 'acte_engagement']):
            return 'engagement'
        
        # Known document types by filename
        if any(x in fname for x in ['cps', 'cctp', 'cahier des charges', 'prescriptions']):
            return 'specification'
        if any(x in fname for x in ['rc', 'reglement', 'consultation', 'règlement']):
            return 'administrative'
        if any(x in fname for x in ['bdp', 'bordereau', 'prix', 'estimatif', 'detail', 'dpgf']):
            return 'product'
        if any(x in fname for x in ['avis', 'publicité', 'annonce']):
            return 'avis'
        
        # Content-based classification fallback (if filename is ambiguous)
        if content:
            content_sample = content[:5000].lower()  # Check first 5000 chars
            
            # BDP detection: pricing tables with item numbers
            if re.search(r'n°\s*prix|désignation.*quantité|bordereau.*prix|estimatif', content_sample):
                return 'product'
            
            # CPS detection: articles and chapters (but not pricing)
            if re.search(r'article\s+\d+|chapitre\s+\d+', content_sample) and 'prix' not in fname:
                return 'specification'
            
            # RC detection: evaluation criteria, eligibility
            if re.search(r'critères.*évaluation|conditions.*participation|pièces.*dossier', content_sample):
                return 'administrative'
        
        return 'other'

    @staticmethod
    def normalize_headers(text: str) -> str:
        """Standardizes headers (Article X -> ## ARTICLE X)."""
        # Article 1..99
        text = re.sub(r'^(#+)?\s*(ARTICLE|Article)\s*(\d+)', r'## ARTICLE \3', text, flags=re.MULTILINE)
        # Arabic Chapter
        text = re.sub(r'^#\s*الباب', r'## CHAPITRE', text, flags=re.MULTILINE)
        return text
