"""
Pipeline Stage: Classification Container
Document classifier implementing 3-step classification logic
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of document classification."""
    doc_type: str
    confidence: str  # "high", "medium", "low", or "unknown"
    step: int  # Which step produced the result (1, 2, or 3)


class DocumentClassifier:
    """
    3-step document classifier for tender documents.
    
    Step 1: Filename + high-confidence content patterns
    Step 2: Content-based classification for unknowns
    Step 3: AI-based classification using OpenRouter
    """
    
    def __init__(self, openrouter_client=None):
        """
        Initialize classifier.
        
        Args:
            openrouter_client: OpenRouter client for Step 3 (optional)
        """
        self.openrouter_client = openrouter_client
    
    @staticmethod
    def _count_matches(patterns: List[str], text: str) -> int:
        """Count how many patterns match in text."""
        return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
    
    def classify(self, filename: str, content: str) -> ClassificationResult:
        """
        Classify document using 3-step process.
        
        Args:
            filename: Original filename
            content: Document content
            
        Returns:
            ClassificationResult with doc_type, confidence, and step
        """
        # Step 1: High-confidence filename + content
        result = self.step1_classify(filename, content)
        if result:
            logger.info(f"Step 1 classified '{filename}' as '{result.doc_type}' (confidence: {result.confidence})")
            return result
        
        # Step 2: Content-based for unknowns
        result = self.step2_classify(filename, content)
        if result:
            logger.info(f"Step 2 classified '{filename}' as '{result.doc_type}' (confidence: {result.confidence})")
            return result
        
        # Step 3: AI-based classification
        if self.openrouter_client:
            result = self.step3_classify(filename, content)
            if result:
                logger.info(f"Step 3 classified '{filename}' as '{result.doc_type}'")
                return result
        else:
            logger.warning("OpenRouter client not available, skipping Step 3")
        
        # All steps failed
        logger.warning(f"All classification steps failed for '{filename}'")
        return ClassificationResult(doc_type="unknown", confidence="unknown", step=0)
    
    @staticmethod
    def step1_classify(filename: str, content: str) -> Optional[ClassificationResult]:
        """
        Step 1: Filename + high-confidence content patterns.
        
        Returns:
            ClassificationResult or None if no match
        """
        fname_lower = filename.lower()
        content_lower = content.lower()
        
        # AVIS: Check filename first
        # AVIS: Check filename first
        avis_keywords = ["avis", "avis_ar", "avis_arabe","arabe","ar"]
        if any(kw in fname_lower for kw in avis_keywords):
            # Verify with content
            if re.search(r"il\s+sera\s+procédé", content_lower):
                return ClassificationResult(doc_type="avis", confidence="high", step=1)
        
        # CPS/CCTP/CAHIERDESCHARGES: Specification
        cps_keywords = ["cps", "cctp", "cahierdescharges", "cahier_des_charges"]
        if any(kw in fname_lower.replace("_", "").replace(" ", "") for kw in ["cps", "cctp", "cahierdescharges"]):
            spec_patterns = [
                r"cahier\s+des\s+prescriptions",
                r"cahier\s+des\s+charges",
                r"دفتر\s+التحملات",
                r"consistance\s+du\s+projet",
                r"clauses\s+générales",
                r"clauses\s+techniques",
                r"description\s+technique\s+des\s+prix",
                r"mode\s+de\s+passation\s+du\s+marché",
                r"nantissement",
                r"délai\s+d['']exécution",
                r"cctp",
                r"c\.c\.t\.p"
            ]
            matches = DocumentClassifier._count_matches(spec_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="specification", confidence="high", step=1)
            elif matches == 2:
                return ClassificationResult(doc_type="specification", confidence="medium", step=1)
            elif matches == 1:
                return ClassificationResult(doc_type="specification", confidence="low", step=1)
        
        # RC: Administrative
        rc_keywords = ["rc", "réglement_consultation", "reglement_consultation", "rgao", "rpao", "rcdg", "ccag", "ccafg"]
        if any(kw in fname_lower.replace("_", " ") for kw in rc_keywords):
            admin_patterns = [
                r"objet\s+du\s+règlement",
                r"règlement\s+de\s+la\s+consultation",
                r"règlement\s+de\s+consultation",
                r"نظام\s+الاستشارة",
                r"conditions\s+requises\s+des\s+concurrents",
                r"contenu\s+du\s+dossier\s+des\s+concurrents",
                r"critères\s+d['']évaluation\s+des\s+offres"
            ]
            matches = DocumentClassifier._count_matches(admin_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="administrative", confidence="high", step=1)
            elif matches == 2:
                return ClassificationResult(doc_type="administrative", confidence="medium", step=1)
            elif matches == 1:
                return ClassificationResult(doc_type="administrative", confidence="low", step=1)
        
        # BDP: Bordereau des prix
        bdp_keywords = ["bordereau_des_prix", "bdp", "detail_estimatif", "bordereau", "détail_estimatif", "bpu", "bdpe", "bp", "dqe","bordereaux"]
        if any(kw in fname_lower.replace("_", " ") for kw in bdp_keywords):
            bdp_patterns = [
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
                r"unité"
            ]
            matches = DocumentClassifier._count_matches(bdp_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="product", confidence="high", step=1)
            elif matches == 2:
                return ClassificationResult(doc_type="product", confidence="medium", step=1)
            elif matches == 1:
                return ClassificationResult(doc_type="product", confidence="low", step=1)
        
        # Forms: Acte d'engagement, Declaration, etc.
        form_keywords = ["acte_d_engagement", "ae", "annexe", "dsh", "honneur", "dh", "declarartion", "déclaration", "déclaration_sur_l_honneur", "déclaration_sur _l_honneur"]
        fname_normalized = fname_lower.replace("_", " ")
        if any(kw in fname_lower for kw in form_keywords) or any(kw in fname_normalized for kw in form_keywords):
            form_patterns = [
                r"déclaration\s+sur\s+l['']honneur",
                r"تصريح\s*ـ*\s*بالشرف",
                r"je\s+soussigné",
                r"nous\s+soussignés",
                r"أنا\s+الموقع\s+أسفله",
                r"acte\s+d['']engagement",
                r"عقد\s*ـ*\s*ا?لتزام",
                r"engagement\s+du\s+concurrent",
                r"montant\s+total\s+de\s+l['']offre",
                r"l['']offre\s+s['']élève\s+à"
            ]
            matches = DocumentClassifier._count_matches(form_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="form", confidence="high", step=1)
            elif matches == 2:
                return ClassificationResult(doc_type="form", confidence="medium", step=1)
            elif matches == 1:
                return ClassificationResult(doc_type="form", confidence="low", step=1)

        return None
    
    @staticmethod
    def step2_classify(filename: str, content: str) -> Optional[ClassificationResult]:
        """
        Step 2: Content-based classification for unknowns.
        
        Returns:
            ClassificationResult or None if no match
        """
        content_lower = content.lower()
        doc_length = len(content)
        
        # Short documents (<3000 chars)
        if doc_length < 3000:
            # Check for Avis
            avis_patterns = [
                r"avis\s+d['']appel\s+d['']offres",
                r"avis\s+de\s+publicit[ée]",
                r"avis\s+d['']achat",
                r"إعلان\s*ـ*\s*عن\s+طلب\s+عروض",
                r"إعلان\s*ـ*\s*عن\s+مزايدة",
                r"il\s+sera\s+procédé",
                r"www\.marchespublics\.gov\.ma"
            ]
            matches = DocumentClassifier._count_matches(avis_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="avis", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="avis", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="avis", confidence="low", step=2)
            
            # Check for Forms (Declaration/Engagement)
            form_patterns = [
                r"déclaration\s+sur\s+l['']honneur",
                r"تصريح\s*ـ*\s*بالشرف",
                r"je\s+soussigné",
                r"nous\s+soussignés",
                r"أنا\s+الموقع\s+أسفله",
                r"acte\s+d['']engagement",
                r"عقد\s*ـ*\s*ا?لتزام",
                r"engagement\s+du\s+concurrent",
                r"montant\s+total\s+de\s+l['']offre",
                r"l['']offre\s+s['']élève\s+à"
            ]
            matches = DocumentClassifier._count_matches(form_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="form", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="form", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="form", confidence="low", step=2)
            
            # Check for BDP (short version)
            bdp_patterns = [
                r"bordereau\s+des\s+prix",
                r"détail\s+estimatif",
                r"جدول\s+الأثمان",
                r"البيان\s+التقديري",
                r"désignation\s+des\s+prestations",
                r"prix\s+unitaire",
                r"total\s+ttc",
                r"total\s+h\.?t",
                r"quantité",
                r"unité"
            ]
            matches = DocumentClassifier._count_matches(bdp_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="product", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="product", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="product", confidence="low", step=2)
        
        # Long documents (>3000 chars) - use first 5000 chars
        else:
            sample = content[:5000].lower()
            
            # Check for Specification (CPS)
            spec_patterns = [
                r"cahier\s+des\s+prescriptions",
                r"cahier\s+des\s+charges",
                r"دفتر\s+التحملات",
                r"consistance\s+du\s+projet",
                r"clauses\s+générales",
                r"clauses\s+techniques",
                r"description\s+technique\s+des\s+prix",
                r"mode\s+de\s+passation\s+du\s+marché",
                r"nantissement",
                r"délai\s+d['']exécution",
                r"cctp",
                r"c\.c\.t\.p"
            ]
            matches = DocumentClassifier._count_matches(spec_patterns, sample)
            
            if matches > 2:
                return ClassificationResult(doc_type="specification", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="specification", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="specification", confidence="low", step=2)
            
            # Check for Administrative (RC)
            admin_patterns = [
                r"objet\s+du\s+règlement",
                r"règlement\s+de\s+la\s+consultation",
                r"règlement\s+de\s+consultation",
                r"نظام\s+الاستشارة",
                r"conditions\s+requises\s+des\s+concurrents",
                r"contenu\s+du\s+dossier\s+des\s+concurrents",
                r"critères\s+d['']évaluation\s+des\s+offres",
                r"cautionnement\s+provisoire\s+.*article"
            ]
            matches = DocumentClassifier._count_matches(admin_patterns, sample)
            
            if matches > 2:
                return ClassificationResult(doc_type="administrative", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="administrative", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="administrative", confidence="low", step=2)
        
        return None
    
    def step3_classify(self, filename: str, content: str) -> Optional[ClassificationResult]:
        """
        Step 3: AI-based classification using OpenRouter.
        
        Args:
            filename: Original filename
            content: Document content
            
        Returns:
            ClassificationResult or None if AI fails
        """
        if not self.openrouter_client:
            logger.warning("OpenRouter client not available for Step 3")
            return None
        
        # Use first 5000 chars for AI classification
        sample = content[:5000]
        
        prompt = f"""You are a document classifier for Moroccan public tender documents.

Classify the following document into ONE of these categories:
- avis: Tender notice/announcement (Avis d'appel d'offres)
- administrative: Administrative regulation (Règlement de consultation)
- specification: Technical specifications (Cahier des Prescriptions Spéciales/CCTP)
- product: Bill of quantities/pricing (Bordereau des Prix/Détail Estimatif)
- form: Forms like declarations or engagement acts
- other: Any other document type

Document filename: {filename}
Document content (first 5000 chars):
{sample}

Respond with ONLY the category name (avis, administrative, specification, product, form, or other)."""

        try:
            messages = [
                {"role": "system", "content": "You are a document classification expert for Moroccan public tenders."},
                {"role": "user", "content": prompt}
            ]
            
            response = self.openrouter_client.chat_completion(
                messages=messages,
                temperature=0.0,
                json_mode=False
            )
            
            # Extract doc_type from response
            doc_type = response.strip().lower()
            
            # Validate response
            valid_types = ["avis", "administrative", "specification", "product", "form", "other"]
            if doc_type in valid_types:
                return ClassificationResult(doc_type=doc_type, confidence="ai", step=3)
            else:
                logger.warning(f"AI returned invalid doc_type: '{doc_type}'")
                return None
                
        except Exception as e:
            logger.error(f"Step 3 AI classification failed: {e}")
            return None
