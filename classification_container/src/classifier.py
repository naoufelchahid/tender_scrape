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
        
        # 1. SPECIFICATION (CPS/CCTP)
        # Priority 1
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
        
        # 2. ADMINISTRATIVE (RC)
        # Priority 2
        rc_keywords = [
            "rc", "réglement_consultation", "reglement_consultation", 
            "rgao", "rpao", "rcdg", "ccag", "ccafg",
            "reglement de consultation", "réglement de consultation",
            "reglement de la consultation", "réglement de la consultation"
        ]
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
        
        # 3. PRODUCT / BDP
        # Priority 3
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
        
        # 4. AVIS_FR
        # Priority 4
        avis_fr_keywords = ["avis"]
        if any(kw in fname_lower for kw in avis_fr_keywords):
            # Check if it's NOT Arabic (avis_ar takes precedence)
            if not ("ar" in fname_lower or "arabe" in fname_lower):
                # Verify with French content
                if re.search(r"il\s+sera\s+procédé", content_lower):
                    return ClassificationResult(doc_type="avis_fr", confidence="high", step=1)
        
        # 5. AVIS_AR
        # Priority 5
        avis_ar_keywords = ["avis", "ar"]
        # Must have both "avis" AND "ar" in filename
        if all(kw in fname_lower for kw in avis_ar_keywords):
            # Verify with Arabic content
            if re.search(r"إعلان", content_lower) or re.search(r"فتح\s+الأظرفة", content_lower):
                return ClassificationResult(doc_type="avis_ar", confidence="high", step=1)
        
        # 6. ACTE_ENGAGEMENT
        # Priority 6
        ae_keywords = ["model_acte_engagement", "ae", "acte_engagement", "acte_d_engagement", "a_e", "acte", "engagement"]
        if any(kw in fname_lower.replace("_", "").replace(" ", "") for kw in [k.replace("_", "") for k in ae_keywords]):
            ae_patterns = [
                r"après\s+avoir\s+pris\s+connaissance\s+du\s+dossier",
                r"acte\s+d['']engagemnt",
                r"acte\s+d['']engagement"
            ]
            matches = DocumentClassifier._count_matches(ae_patterns, content_lower)
            
            if matches >= 1:
                return ClassificationResult(doc_type="acte_engagement", confidence="high", step=1)
        
        # 7. DECLARATION
        # Priority 7
        decl_keywords = ["dsh", "déclaration_sur_l_honneur", "declaration_sur_l_honneur", "declaration", "honneur", "déclaration"]
        if any(kw in fname_lower.replace("_", "").replace(" ", "") for kw in [k.replace("_", "") for k in decl_keywords]):
            decl_patterns = [
                r"déclare\s+sur\s+l['']honneur",
                r"déclaration\s+sur\s+l['']honneur"
            ]
            matches = DocumentClassifier._count_matches(decl_patterns, content_lower)
            
            if matches >= 1:
                return ClassificationResult(doc_type="declaration", confidence="high", step=1)
        
        # 8. ANNEXE
        annexe_keywords = ["annexes", "annexe"]
        if any(kw in fname_lower for kw in annexe_keywords):
            # Check for both patterns
            ae_patterns = [
                r"après\s+avoir\s+pris\s+connaissance\s+du\s+dossier",
                r"acte\s+d['']engagemnt",
                r"acte\s+d['']engagement"
            ]
            decl_patterns = [
                r"déclare\s+sur\s+l['']honneur",
                r"déclaration\s+sur\s+l['']honneur"
            ]
            
            ae_matches = DocumentClassifier._count_matches(ae_patterns, content_lower)
            decl_matches = DocumentClassifier._count_matches(decl_patterns, content_lower)
            
            # If both patterns found, this will be split later - for now classify as annexe
            # But we can return a special marker or handle it differently
            if ae_matches >= 1 and decl_matches >= 1:
                # Contains both - will be split later
                return ClassificationResult(doc_type="annexe", confidence="high", step=1)
            elif decl_matches >= 1:
                return ClassificationResult(doc_type="declaration", confidence="high", step=1)
            elif ae_matches >= 1:
                return ClassificationResult(doc_type="acte_engagement", confidence="high", step=1)
            else:
                # Pure annexe
                return ClassificationResult(doc_type="annexe", confidence="medium", step=1)
        
        return None
    
    @staticmethod
    def step2_classify(filename: str, content: str) -> Optional[ClassificationResult]:
        """
        Step 2: Content-based classification for unknowns.
        
        Returns:
            ClassificationResult or None if no match
        """
        fname_lower = filename.lower()
        content_lower = content.lower()
        doc_length = len(content)
        
        # Short documents (<3000 chars)
        if doc_length < 3000:
            # Reordered Short Doc Checks: BDP (3) -> Avis FR (4) -> Avis AR (5) -> AE (6) -> Decl (7)
            
            # 3. Product / BDP
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
                
            # 4. Avis_FR
            avis_fr_patterns = [
                r"avis\s+d['']appel\s+d['']offres",
                r"avis\s+de\s+publicit[ée]",
                r"avis\s+d['']achat",
                r"il\s+sera\s+procédé",
                r"www\.marchespublics\.gov\.ma"
            ]
            matches = DocumentClassifier._count_matches(avis_fr_patterns, content_lower)
            
            if matches > 2:
                return ClassificationResult(doc_type="avis_fr", confidence="high", step=2)
            elif matches == 2:
                return ClassificationResult(doc_type="avis_fr", confidence="medium", step=2)
            elif matches == 1:
                return ClassificationResult(doc_type="avis_fr", confidence="low", step=2)
            
            # 5. Avis_AR
            avis_ar_patterns = [
                r"إعلان",
                r"فتح\s+الأظرفة"
            ]
            matches = DocumentClassifier._count_matches(avis_ar_patterns, content_lower)
            
            if matches >= 1:
                return ClassificationResult(doc_type="avis_ar", confidence="high", step=2)
            
            # 6. Acte d'Engagement
            ae_patterns = [
                r"après\s+avoir\s+pris\s+connaissance\s+du\s+dossier",
                r"acte\s+d['']engagemnt",
                r"acte\s+d['']engagement"
            ]
            matches = DocumentClassifier._count_matches(ae_patterns, content_lower)
            
            if matches >= 1:
                return ClassificationResult(doc_type="acte_engagement", confidence="high", step=2)
            
            # 7. Declaration
            decl_patterns = [
                r"déclare\s+sur\s+l['']honneur",
                r"déclaration\s+sur\s+l['']honneur"
            ]
            matches = DocumentClassifier._count_matches(decl_patterns, content_lower)
            
            if matches >= 1:
                return ClassificationResult(doc_type="declaration", confidence="high", step=2)
        
        # Long documents (>3000 chars) - use first 5000 chars
        else:
            sample = content[:5000].lower()
            
            # Reordered Long Doc Checks: Spec (1) -> Admin (2)
            
            # 1. Specification (CPS)
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
            
            # 2. Administrative (RC)
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
- avis_fr: French tender notice/announcement (Avis d'appel d'offres)
- avis_ar: Arabic tender notice/announcement (إعلان)
- administrative: Administrative regulation (Règlement de consultation)
- specification: Technical specifications (Cahier des Prescriptions Spéciales/CCTP)
- product: Bill of quantities/pricing (Bordereau des Prix/Détail Estimatif)
- acte_engagement: Engagement act (Acte d'engagement)
- declaration: Declaration sur l'honneur
- annexe: Annexe documents
- other: Any other document type

Document filename: {filename}
Document content (first 5000 chars):
{sample}

Respond with ONLY the category name (avis_fr, avis_ar, administrative, specification, product, acte_engagement, declaration, annexe, or other)."""

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
            valid_types = ["avis_fr", "avis_ar", "administrative", "specification", "product", "acte_engagement", "declaration", "annexe", "other"]
            if doc_type in valid_types:
                return ClassificationResult(doc_type=doc_type, confidence="ai", step=3)
            else:
                logger.warning(f"AI returned invalid doc_type: '{doc_type}'")
                return None
                
        except Exception as e:
            logger.error(f"Step 3 AI classification failed: {e}")
            return None
