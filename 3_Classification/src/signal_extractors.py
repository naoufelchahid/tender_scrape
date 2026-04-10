"""
Pipeline Stage: Classification Container
Signal extractors for multi-signal segmentation engine.
Each extractor scans lines and emits typed signal dicts.
"""

import json
import re
from pathlib import Path
from typing import Dict, List

# Load config once at module level
_CONFIG_PATH = Path(__file__).parent / "segmentation_config.json"
with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
    SEGMENTATION_CONFIG = json.load(_f)


class AnchorExtractor:
    """
    Signal 1: Regex anchor detection.
    Scans each line for opening, closing, and internal anchor patterns.
    Emits: {"line_idx": int, "type": str, "role": "open"|"close"|"internal", "strength": float}
    """

    def __init__(self):
        self._compiled = {}
        anchors = SEGMENTATION_CONFIG["anchors"]
        for doc_type, roles in anchors.items():
            self._compiled[doc_type] = {}
            for role in ("open", "close", "internal"):
                patterns = roles.get(role, [])
                self._compiled[doc_type][role] = [
                    re.compile(p, re.IGNORECASE) for p in patterns
                ]

    def extract(self, lines: List[str]) -> List[Dict]:
        signals = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            for doc_type, roles in self._compiled.items():
                for role, compiled_patterns in roles.items():
                    for pat in compiled_patterns:
                        if pat.search(stripped):
                            strength = 1.0 if role == "open" else (0.8 if role == "close" else 0.5)
                            signals.append({
                                "line_idx": i,
                                "type": doc_type,
                                "role": role,
                                "strength": strength,
                            })
                            break  # one match per role per doc_type per line
        return signals


class StructuralExtractor:
    """
    Signal 2: Structural marker detection.
    Detects layout-level discontinuities: file headers, page breaks, blank gaps, H1 resets, page markers.
    Emits: {"line_idx": int, "boundary_signal": float}
    """

    _FILE_HEADER_RE = re.compile(r'^# File:\s+', re.IGNORECASE)
    _SEPARATOR_RE = re.compile(r'^-{3,}$')
    _PAGE_MARKER_RE = re.compile(r'^##\s+[Pp]age\s+\d+')
    _H1_RE = re.compile(r'^#\s+(?!#)')
    _BLANK_GAP_THRESHOLD = 3

    def extract(self, lines: List[str]) -> List[Dict]:
        signals = []
        blank_count = 0
        blank_start = -1

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Blank line tracking
            if not stripped:
                if blank_count == 0:
                    blank_start = i
                blank_count += 1
                continue
            else:
                if blank_count >= self._BLANK_GAP_THRESHOLD:
                    signals.append({
                        "line_idx": blank_start,
                        "boundary_signal": min(0.3 + 0.05 * blank_count, 0.6),
                    })
                blank_count = 0

            # File header — strongest structural signal
            if self._FILE_HEADER_RE.match(stripped):
                signals.append({"line_idx": i, "boundary_signal": 1.0})
                continue

            # Separator (---)
            if self._SEPARATOR_RE.match(stripped):
                signals.append({"line_idx": i, "boundary_signal": 0.4})
                continue

            # Page marker (## Page N)
            if self._PAGE_MARKER_RE.match(stripped):
                signals.append({"line_idx": i, "boundary_signal": 0.3})
                continue

            # H1 reset (# SOMETHING but not ## or # File:)
            if self._H1_RE.match(stripped) and not self._FILE_HEADER_RE.match(stripped):
                signals.append({"line_idx": i, "boundary_signal": 0.5})

        return signals


class VocabularyExtractor:
    """
    Signal 3: Vocabulary shift detection.
    Uses sliding windows to detect when the dominant keyword bucket changes.
    Emits: {"line_idx": int, "vocab_shift": float, "from_type": str, "to_type": str}
    """

    # Keyword buckets per doc type — reuses classifier's domain knowledge
    _BUCKETS = {
        "specification": [
            "cahier des prescriptions", "cahier des charges", "clauses techniques",
            "clauses générales", "nantissement", "délai d'exécution", "cctp",
            "consistance du projet", "mode de passation",
        ],
        "administrative": [
            "règlement de consultation", "conditions requises des concurrents",
            "contenu du dossier", "critères d'évaluation", "cautionnement provisoire",
        ],
        "product": [
            "prix unitaire", "montant", "désignation", "quantité", "unité",
            "bordereau des prix", "détail estimatif", "total ttc", "total ht",
        ],
        "acte_engagement": [
            "acte d'engagement", "après avoir pris connaissance", "je soussigné",
        ],
        "declaration": [
            "déclaration sur l'honneur", "déclare sur l'honneur", "je soussigné",
        ],
        "avis_fr": [
            "avis d'appel d'offres", "il sera procédé", "marchespublics",
        ],
        "avis_ar": [
            "إعلان", "طلب عروض", "فتح الأظرفة",
        ],
    }

    def __init__(self):
        self._window_size = SEGMENTATION_CONFIG["vocabulary"]["window_size"]

    def _score_window(self, text: str) -> Dict[str, int]:
        text_lower = text.lower()
        scores = {}
        for doc_type, keywords in self._BUCKETS.items():
            scores[doc_type] = sum(1 for kw in keywords if kw in text_lower)
        return scores

    def _dominant_type(self, scores: Dict[str, int]) -> str:
        if not scores or max(scores.values()) == 0:
            return "none"
        return max(scores, key=scores.get)

    def extract(self, lines: List[str]) -> List[Dict]:
        signals = []
        w = self._window_size

        if len(lines) < w * 2:
            return signals

        # Pre-join windows for efficiency
        prev_text = "\n".join(lines[0:w])
        prev_scores = self._score_window(prev_text)
        prev_dominant = self._dominant_type(prev_scores)

        step = max(1, w // 4)  # slide by quarter-window

        for start in range(step, len(lines) - w + 1, step):
            curr_text = "\n".join(lines[start:start + w])
            curr_scores = self._score_window(curr_text)
            curr_dominant = self._dominant_type(curr_scores)

            if curr_dominant != prev_dominant and curr_dominant != "none" and prev_dominant != "none":
                # Compute shift magnitude: how much the distribution changed
                prev_total = max(sum(prev_scores.values()), 1)
                curr_total = max(sum(curr_scores.values()), 1)
                magnitude = abs(
                    (prev_scores.get(prev_dominant, 0) / prev_total)
                    - (curr_scores.get(prev_dominant, 0) / curr_total)
                )
                if magnitude > 0.2:
                    signals.append({
                        "line_idx": start,
                        "vocab_shift": min(magnitude, 1.0),
                        "from_type": prev_dominant,
                        "to_type": curr_dominant,
                    })

            prev_scores = curr_scores
            prev_dominant = curr_dominant

        return signals


class FingerprintExtractor:
    """
    Signal 4: Document fingerprint shift detection.
    Computes statistical features per sliding window and detects shifts.
    Features: Arabic ratio, table density, number density, line length variance, signature keywords.
    Emits: {"line_idx": int, "fingerprint_shift": float}
    """

    _SIGNATURE_KEYWORDS = {"soussigné", "soussignés", "cachet", "signature"}
    _ARABIC_RE = re.compile(r'[\u0600-\u06FF]')
    _NUMBER_RE = re.compile(r'\d+')
    _PIPE_RE = re.compile(r'\|')

    def __init__(self):
        self._window_size = SEGMENTATION_CONFIG["vocabulary"]["window_size"]

    def _compute_features(self, lines: List[str]) -> Dict[str, float]:
        if not lines:
            return {"arabic": 0, "table": 0, "number": 0, "line_var": 0, "signature": 0}

        total_chars = sum(len(l) for l in lines) or 1
        arabic_chars = sum(len(self._ARABIC_RE.findall(l)) for l in lines)
        pipe_count = sum(len(self._PIPE_RE.findall(l)) for l in lines)
        number_count = sum(len(self._NUMBER_RE.findall(l)) for l in lines)

        lengths = [len(l) for l in lines]
        mean_len = sum(lengths) / len(lengths)
        variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
        # Normalize variance to 0-1 range (cap at 10000)
        norm_variance = min(variance / 10000, 1.0)

        text_lower = "\n".join(lines).lower()
        sig_count = sum(1 for kw in self._SIGNATURE_KEYWORDS if kw in text_lower)

        return {
            "arabic": arabic_chars / total_chars,
            "table": min(pipe_count / (len(lines) * 2), 1.0),
            "number": min(number_count / len(lines), 1.0),
            "line_var": norm_variance,
            "signature": min(sig_count / len(self._SIGNATURE_KEYWORDS), 1.0),
        }

    def extract(self, lines: List[str]) -> List[Dict]:
        signals = []
        w = self._window_size

        if len(lines) < w * 2:
            return signals

        prev_features = self._compute_features(lines[0:w])
        step = max(1, w // 4)

        for start in range(step, len(lines) - w + 1, step):
            curr_features = self._compute_features(lines[start:start + w])

            # Compute euclidean distance between feature vectors
            dist = sum(
                (curr_features[k] - prev_features[k]) ** 2
                for k in curr_features
            ) ** 0.5

            if dist > 0.3:
                signals.append({
                    "line_idx": start,
                    "fingerprint_shift": min(dist, 1.0),
                })

            prev_features = curr_features

        return signals
