"""
Pipeline Stage: Classification Container
Document classifier implementing 3-step classification logic
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple
from dataclasses import dataclass
import logging

try:
    from decompose import decompose_text
    _DECOMPOSE_AVAILABLE = True
except ImportError:
    _DECOMPOSE_AVAILABLE = False

logger = logging.getLogger(__name__)

if not _DECOMPOSE_AVAILABLE:
    logger.warning("decompose-mcp not installed. Document cleaning disabled.")


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

    _SAMPLE_SIZE = 5000
    _MIN_CLEAN_RATIO = 0.30
    _DECOMPOSE_CONTEXT = (
        "Identify document type for Moroccan public tender: "
        "technical specifications, administrative regulations, "
        "price tables, engagement acts, or declarations"
    )

    _SPEC_PATTERNS = (
        # Universal / all tender types
        r"cahier\s+des\s+prescriptions",
        r"cahier\s+des\s+charges",
        r"دفتر\s+التحملات",
        r"consistance\s+du\s+projet",
        r"clauses\s+générales",
        r"clauses\s+techniques",
        r"description\s+technique\s+des\s+prix",
        r"mode\s+de\s+passation\s+du\s+marché",
        r"cctp",
        r"c\.c\.t\.p",
        # Travaux-specific
        r"nantissement",
        r"délai\s+d['']exécution",
        # Fournitures-specific
        r"spécifications\s+techniques",
        r"caractéristiques\s+techniques",
        r"normes?\s+(?:marocaines?|applicables?|en\s+vigueur)",
        r"livraison",
        r"garantie\s+(?:minimale|de\s+\d+\s+an)",
        # Services-specific
        r"consistance\s+de\s+la\s+mission",
        r"prestations\s+à\s+fournir",
        r"livrables?",
        r"mission\s+de\s+(?:maîtrise|suivi|contrôle|coordination)",
        r"rapport\s+d['']études",
    )

    _ADMIN_PATTERNS = (
        r"objet\s+du\s+règlement",
        r"règlement\s+de\s+la\s+consultation",
        r"règlement\s+de\s+consultation",
        r"نظام\s+الاستشارة",
        r"conditions\s+requises\s+des\s+concurrents",
        r"contenu\s+du\s+dossier\s+des\s+concurrents",
        r"critères\s+d['']évaluation\s+des\s+offres",
    )

    _BDP_PATTERNS_STEP1 = (
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
    )

    _BDP_PATTERNS_STEP2 = (
        r"bordereau\s+des\s+prix",
        r"détail\s+estimatif",
        r"جدول\s+الأثمان",
        r"البيان\s+التقديري",
        r"désignation\s+des\s+prestations",
        r"prix\s+unitaire",
        r"total\s+ttc",
        r"total\s+h\.?t",
        r"quantité",
        r"unité",
    )

    _AE_PATTERNS = (
        r"après\s+avoir\s+pris\s+connaissance\s+du\s+dossier",
        r"acte\s+d['']engagemnt",
        r"acte\s+d['']engagement",
    )

    _DECL_PATTERNS = (
        r"déclare\s+sur\s+l['']honneur",
        r"déclaration\s+sur\s+l['']honneur",
    )

    _AVIS_AR_PATTERNS = (
        r"إعلان",
        r"فتح\s+الأظرفة",
    )

    _AVIS_FR_PATTERNS_STEP2 = (
        r"avis\s+d['']appel\s+d['']offres",
        r"avis\s+de\s+publicit[ée]",
        r"avis\s+d['']achat",
        r"il\s+sera\s+procédé",
        r"www\.marchespublics\.gov\.ma",
    )

    def __init__(self, openrouter_client=None, decomposer_func=None):
        """
        Initialize classifier.
        
        Args:
            openrouter_client: OpenRouter client for Step 3 (optional)
            decomposer_func: Function for noise cleaning (optional, defaults to decompose_text)
        """
        self.openrouter_client = openrouter_client
        self._decomposer_func = decomposer_func or (decompose_text if _DECOMPOSE_AVAILABLE else None)

    @staticmethod
    def _count_matches(patterns: Iterable[str], text: str) -> int:
        """Count how many patterns match in text."""
        return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))

    @staticmethod
    def _normalize_filename(fname: str) -> str:
        """Normalize filename for keyword matching."""
        return fname.lower().replace("_", "").replace(" ", "")

    @staticmethod
    def _classify_by_pattern_count(
        matches: int, doc_type: str, step: int
    ) -> Optional[ClassificationResult]:
        """Convert match count to ClassificationResult with appropriate confidence."""
        if matches > 2:
            return ClassificationResult(doc_type=doc_type, confidence="high", step=step)
        if matches == 2:
            return ClassificationResult(doc_type=doc_type, confidence="medium", step=step)
        if matches == 1:
            return ClassificationResult(doc_type=doc_type, confidence="low", step=step)
        return None
    
    def _clean_content_for_classification(self, content: str) -> str:
        """
        Use decompose to clean noise from document content.
        
        Args:
            content: Raw document content
            
        Returns:
            Cleaned content or original content on failure
        """
        if not self._decomposer_func:
            return content
            
        try:
            # Clean content using decompose (remove OCR artifacts, headers, etc.)
            # The current version of decompose-mcp (0.1.0) returns a dict with units.
            # We join the units to get the "cleaned" content.
            result = self._decomposer_func(
                content,
                compact=True
            )
            
            if not result or "units" not in result:
                return content
                
            # Filter units: exclude those with 0 attention if they seem like noise
            # For now, let's just join all semantic units found.
            cleaned = "\n\n".join(unit["text"] for unit in result["units"])
            
            # Simple validation: if cleaning removed too MUCH content, fall back
            if cleaned and len(cleaned) > len(content) * self._MIN_CLEAN_RATIO:
                logger.info(f"Decompose cleaned content: {len(content)} -> {len(cleaned)} chars")
                return cleaned
            else:
                logger.warning("Decompose output too short or empty, falling back to original content")
                return content
                
        except Exception as e:
            logger.error(f"Decompose cleaning failed: {e}")
            return content

    @staticmethod
    def _pseudo_filename_from_content(content: str) -> str:
        """
        Derive a pseudo-filename from the segment's first H1 heading so that
        Step 1's filename-keyword matching works during segmentation mode
        (where no real filename is available).

        Scans the first 20 lines for the first markdown H1 (# Title) and
        normalises it into a slug. Falls back to "segment" if no H1 is found.
        """
        for line in content.splitlines()[:20]:
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                # Remove the leading # and normalise
                heading = stripped[2:].strip()
                return DocumentClassifier._normalize_filename(heading)
        return "segment"

    def classify(self, filename: str, content: str) -> ClassificationResult:
        """
        Classify document using 3-step process with noise cleaning.
        
        Args:
            filename: Original filename
            content: Document content
            
        Returns:
            ClassificationResult with doc_type, confidence, and step
        """
        # Phase 2: Pre-process with decompose to clean noise
        cleaned_content = self._clean_content_for_classification(content)
        
        # Step 1: High-confidence filename + content
        result = self.step1_classify(filename, cleaned_content)
        if result:
            logger.info(f"Step 1 classified '{filename}' as '{result.doc_type}' (confidence: {result.confidence})")
            return result
        
        # Step 2: Content-based for unknowns
        result = self.step2_classify(filename, cleaned_content)
        if result:
            logger.info(f"Step 2 classified '{filename}' as '{result.doc_type}' (confidence: {result.confidence})")
            return result
        
        # Step 3: AI-based classification
        if self.openrouter_client:
            result = self.step3_classify(filename, cleaned_content)
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
        fname_norm = DocumentClassifier._normalize_filename(filename)
        content_lower = content.lower()
        
        # 1. SPECIFICATION (CPS/CCTP)
        if any(kw in fname_norm for kw in ["cps", "cctp", "cahierdescharges"]):
            matches = DocumentClassifier._count_matches(DocumentClassifier._SPEC_PATTERNS, content_lower)
            result = DocumentClassifier._classify_by_pattern_count(matches, "specification", step=1)
            if result:
                return result
        
        # 2. ADMINISTRATIVE (RC)
        rc_keywords = [
            "rc", "reglementconsultation", 
            "rgao", "rpao", "rcdg", "ccag", "ccafg",
            "reglementdeconsultation",
            "reglementdelaconsultation"
        ]
        if any(kw in fname_norm for kw in rc_keywords):
            matches = DocumentClassifier._count_matches(DocumentClassifier._ADMIN_PATTERNS, content_lower)
            result = DocumentClassifier._classify_by_pattern_count(matches, "administrative", step=1)
            if result:
                return result
        
        # 3. PRODUCT / BDP
        bdp_keywords = ["bordereaudesprix", "bdp", "detailestimatif", "bordereau", "bpu", "bdpe", "bp", "dqe", "bordereaux"]
        if any(kw in fname_norm for kw in bdp_keywords):
            matches = DocumentClassifier._count_matches(DocumentClassifier._BDP_PATTERNS_STEP1, content_lower)
            result = DocumentClassifier._classify_by_pattern_count(matches, "product", step=1)
            if result:
                return result
        
        # 4. AVIS_FR
        if "avis" in fname_norm:
            # Check if it's NOT Arabic (avis_ar takes precedence)
            if not ("ar" in fname_norm or "arabe" in fname_norm):
                # Verify with French content
                if re.search(r"il\s+sera\s+procédé", content_lower):
                    return ClassificationResult(doc_type="avis_fr", confidence="high", step=1)
        
        # 5. AVIS_AR
        # Must have both "avis" AND "ar" in filename
        if "avis" in fname_norm and ("ar" in fname_norm or "arabe" in fname_norm):
            # Verify with Arabic content
            matches = DocumentClassifier._count_matches(DocumentClassifier._AVIS_AR_PATTERNS, content_lower)
            if matches >= 1:
                return ClassificationResult(doc_type="avis_ar", confidence="high", step=1)
        
        # 6. ACTE_ENGAGEMENT
        ae_keywords = ["modelacteengagement", "ae", "acteengagement", "actedengagement", "acte", "engagement"]
        if any(kw in fname_norm for kw in ae_keywords):
            matches = DocumentClassifier._count_matches(DocumentClassifier._AE_PATTERNS, content_lower)
            if matches >= 1:
                return ClassificationResult(doc_type="acte_engagement", confidence="high", step=1)
        
        # 7. DECLARATION
        decl_keywords = ["dsh", "declarationsurlhonneur", "declaration", "honneur", "declaration"]
        if any(kw in fname_norm for kw in decl_keywords):
            matches = DocumentClassifier._count_matches(DocumentClassifier._DECL_PATTERNS, content_lower)
            if matches >= 1:
                return ClassificationResult(doc_type="declaration", confidence="high", step=1)
        
        # 8. ANNEXE
        if "annexe" in fname_norm:
            ae_matches = DocumentClassifier._count_matches(DocumentClassifier._AE_PATTERNS, content_lower)
            decl_matches = DocumentClassifier._count_matches(DocumentClassifier._DECL_PATTERNS, content_lower)
            
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

        Specification and administrative are checked at all lengths (short or long)
        because segment chunks can be any size. BDP, avis, acte, and declaration
        use full content for short docs and a leading sample for long docs.

        Returns:
            ClassificationResult or None if no match
        """
        content_lower = content.lower()
        doc_length = len(content)
        sample = content[:DocumentClassifier._SAMPLE_SIZE].lower() if doc_length > DocumentClassifier._SAMPLE_SIZE else content_lower

        # 1. Specification (CPS) — checked at all lengths
        matches = DocumentClassifier._count_matches(DocumentClassifier._SPEC_PATTERNS, sample)
        result = DocumentClassifier._classify_by_pattern_count(matches, "specification", step=2)
        if result:
            return result

        # 2. Administrative (RC) — checked at all lengths
        admin_patterns_step2 = list(DocumentClassifier._ADMIN_PATTERNS) + [r"cautionnement\s+provisoire\s+.*article"]
        matches = DocumentClassifier._count_matches(admin_patterns_step2, sample)
        result = DocumentClassifier._classify_by_pattern_count(matches, "administrative", step=2)
        if result:
            return result

        # 3. Product / BDP
        matches = DocumentClassifier._count_matches(DocumentClassifier._BDP_PATTERNS_STEP2, sample)
        result = DocumentClassifier._classify_by_pattern_count(matches, "product", step=2)
        if result:
            return result

        # 4. Avis_FR
        matches = DocumentClassifier._count_matches(DocumentClassifier._AVIS_FR_PATTERNS_STEP2, content_lower)
        result = DocumentClassifier._classify_by_pattern_count(matches, "avis_fr", step=2)
        if result:
            return result

        # 5. Avis_AR
        matches = DocumentClassifier._count_matches(DocumentClassifier._AVIS_AR_PATTERNS, content_lower)
        if matches >= 1:
            return ClassificationResult(doc_type="avis_ar", confidence="high", step=2)

        # 6. Acte d'Engagement
        matches = DocumentClassifier._count_matches(DocumentClassifier._AE_PATTERNS, content_lower)
        if matches >= 1:
            return ClassificationResult(doc_type="acte_engagement", confidence="high", step=2)

        # 7. Declaration
        matches = DocumentClassifier._count_matches(DocumentClassifier._DECL_PATTERNS, content_lower)
        if matches >= 1:
            return ClassificationResult(doc_type="declaration", confidence="high", step=2)

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
        
        # Use first _SAMPLE_SIZE chars for AI classification
        sample = content[:DocumentClassifier._SAMPLE_SIZE]
        
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
Document content (first {DocumentClassifier._SAMPLE_SIZE} chars):
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

    def classify_segment(
        self,
        content: str,
        hint_type: str = None,
        hint_strength: float = 0.0,
        anchor_offset: int = None,
    ) -> ClassificationResult:
        """
        Classify a segment with optional signal hint from segmentation engine.

        Decision logic:
        - hint_strength >= 0.8 AND Steps 1-2 agree: use result, skip LLM
        - hint_strength >= 0.8 AND Steps 1-2 disagree/unknown: use hint
        - hint_strength < 0.8 AND Steps 1-2 return a type: use Steps 1-2
        - hint_strength < 0.8 AND Steps 1-2 unknown: invoke LLM with hint context
        - No hint: standard Steps 1-2-3

        Args:
            content: Segment content
            hint_type: Dominant doc type from signal extractors (or None)
            hint_strength: Confidence of the hint (0.0-1.0)
            anchor_offset: Character offset of the opening anchor for smart sampling

        Returns:
            ClassificationResult
        """
        # Smart sampling: if anchor_offset given, use content from that point
        if anchor_offset is not None and anchor_offset < len(content):
            sample_content = content[anchor_offset:anchor_offset + self._SAMPLE_SIZE]
        else:
            sample_content = content

        cleaned = self._clean_content_for_classification(sample_content)

        # Extract a pseudo-filename from the segment's first H1 heading so that
        # Step 1's filename-keyword fast-paths are active during segmentation.
        pseudo_filename = self._pseudo_filename_from_content(cleaned)

        # Run Steps 1-2
        step_result = self.step1_classify(pseudo_filename, cleaned)
        if not step_result:
            step_result = self.step2_classify(pseudo_filename, cleaned)

        has_hint = hint_type is not None and hint_strength > 0
        has_step_result = step_result is not None and step_result.doc_type != "unknown"

        # Decision matrix
        if has_hint and hint_strength >= 0.8:
            if has_step_result and step_result.doc_type == hint_type:
                # Agreement: high confidence, skip LLM
                return ClassificationResult(
                    doc_type=step_result.doc_type,
                    confidence=max(step_result.confidence, "high"),
                    step=step_result.step,
                )
            else:
                # Strong hint overrides unknown or disagreeing steps
                return ClassificationResult(
                    doc_type=hint_type,
                    confidence="hint",
                    step=0,
                )

        if has_step_result:
            # Weak or no hint, but steps found something
            return step_result

        # Steps returned nothing — try LLM if available
        if self.openrouter_client:
            llm_result = self.step3_classify("segment", cleaned)
            if llm_result:
                return llm_result

        # Last resort: use weak hint if available
        if has_hint:
            return ClassificationResult(
                doc_type=hint_type,
                confidence="hint",
                step=0,
            )

        return ClassificationResult(doc_type="unknown", confidence="unknown", step=0)
