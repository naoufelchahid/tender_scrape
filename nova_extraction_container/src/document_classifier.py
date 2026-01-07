"""
Document classifier for filtering and categorizing tender documents.
Automatically skips unwanted document types.
"""
import os
import re
from typing import Tuple, Optional
import pdfplumber

from logger import logger


class DocumentClassifier:
    """Classifier for tender documents."""
    
    # Document types to exclude from processing
    EXCLUDED_TYPES = {
        'acte_engagement',
        'engagement_honneur',
        'plan',
        'attestation',
        'bordereau_envoi',
        'certificat',
        'declaration',
        'specimen_signature'
    }
    
    # Document types to process
    SUPPORTED_TYPES = {
        'avis',
        'rc',
        'administrative',
        'cps',
        'bdp',
        'product',
        'decompte',
        'cctp',
        'technical'
    }
    
    # Filename patterns for classification
    FILENAME_PATTERNS = {
        'acte_engagement': r'(?i)(acte[\s_]*d?[\s_]*engagement|acte[\s_]*dengagement)',
        'engagement_honneur': r'(?i)(engagement[\s_]*sur[\s_]*l?[\s_]*honneur|engagement[\s_]*honneur)',
        'plan': r'(?i)(plan[sx]?|dessin[sx]?)',
        'attestation': r'(?i)attestation',
        'bordereau_envoi': r'(?i)(bordereau[\s_]*d?[\s_]*envoi|bordereau[\s_]*envoi)',
        'certificat': r'(?i)certificat',
        'declaration': r'(?i)d[eé]claration',
        'specimen_signature': r'(?i)(sp[eé]cimen|signature)',
        
        # Supported types
        'avis': r'(?i)(avis|annonce)',
        'rc': r'(?i)(r[eè]glement[\s_]*consultation|rc[\s_])',
        'cps': r'(?i)(cahier[\s_]*prescriptions[\s_]*sp[eé]ciales|cps)',
        'bdp': r'(?i)(bordereau[\s_]*prix|bdp|bpu)',
        'cctp': r'(?i)(cahier[\s_]*clauses[\s_]*techniques|cctp)',
        'decompte': r'(?i)(d[eé]compte|quantit[eé]s)',
    }
    
    def __init__(self):
        """Initialize classifier."""
        pass
    
    def classify_by_filename(self, filename: str) -> Optional[str]:
        """
        Classify document type based on filename.
        
        Args:
            filename: File name
            
        Returns:
            Document type or None if cannot determine
        """
        # Normalize filename
        filename_clean = filename.lower().replace('.pdf', '')
        
        # Check each pattern
        for doc_type, pattern in self.FILENAME_PATTERNS.items():
            if re.search(pattern, filename_clean):
                logger.debug(f"Filename match: {filename} → {doc_type}")
                return doc_type
        
        return None
    
    def extract_first_page_text(self, pdf_path: str, max_chars: int = 2000) -> str:
        """
        Extract text from first page for classification.
        
        Args:
            pdf_path: Path to PDF file
            max_chars: Maximum characters to extract
            
        Returns:
            First page text
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > 0:
                    text = pdf.pages[0].extract_text()
                    if text:
                        return text[:max_chars]
            return ""
        except Exception as e:
            logger.warning(f"Error extracting first page text: {e}")
            return ""
    
    def classify_by_content(self, text: str) -> Optional[str]:
        """
        Classify document type based on content.
        
        Args:
            text: Document text (first page)
            
        Returns:
            Document type or None
        """
        text_lower = text.lower()
        
        # Exclusion patterns (high priority)
        if re.search(r"acte\s+d['']engagement|acte\s+dengagement", text_lower):
            return 'acte_engagement'
        if re.search(r"engagement\s+sur\s+l['']honneur", text_lower):
            return 'engagement_honneur'
        if re.search(r"attestation", text_lower):
            return 'attestation'
        if re.search(r"certificat", text_lower):
            return 'certificat'
        
        # Supported types
        if re.search(r"avis\s+d['']appel|annonce", text_lower):
            return 'avis'
        if re.search(r"r[èe]glement\s+de\s+consultation", text_lower):
            return 'rc'
        if re.search(r"cahier\s+des\s+prescriptions\s+sp[ée]ciales|cps", text_lower):
            return 'cps'
        if re.search(r"bordereau\s+des\s+prix|sous-détail", text_lower):
            return 'bdp'
        if re.search(r"cahier\s+des\s+clauses\s+techniques", text_lower):
            return 'cctp'
        
        return None
    
    def classify(self, pdf_path: str) -> Tuple[str, bool]:
        """
        Classify document and determine if it should be processed.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            (doc_type, should_process): Document type and whether to process
        """
        filename = os.path.basename(pdf_path)
        
        # Try filename classification first (faster)
        doc_type = self.classify_by_filename(filename)
        
        if doc_type:
            should_process = doc_type not in self.EXCLUDED_TYPES
            logger.info(f"📝 Classified {filename}: {doc_type} (process: {should_process})")
            return doc_type, should_process
        
        # Fall back to content classification
        logger.debug(f"Filename classification failed, analyzing content for {filename}")
        text = self.extract_first_page_text(pdf_path)
        
        if text:
            doc_type = self.classify_by_content(text)
            if doc_type:
                should_process = doc_type not in self.EXCLUDED_TYPES
                logger.info(f"📝 Classified {filename}: {doc_type} (process: {should_process})")
                return doc_type, should_process
        
        # Default: unknown type, process it to be safe
        doc_type = 'unknown'
        logger.warning(f"⚠️  Could not classify {filename}, will process as 'unknown'")
        return doc_type, True
    
    def is_excluded(self, doc_type: str) -> bool:
        """Check if document type should be excluded."""
        return doc_type in self.EXCLUDED_TYPES
