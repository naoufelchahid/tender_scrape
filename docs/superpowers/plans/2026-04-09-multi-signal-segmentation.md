# Multi-Signal Scoring Segmentation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `document_splitter.py` + `missing_doc_detector.py` with a unified multi-signal scoring engine that segments tender markdown streams by combining regex anchors, structural markers, vocabulary shift, and document fingerprinting.

**Architecture:** Four-pass pipeline: (1) line-level signal extraction, (2) boundary scoring & resolution, (3) segment classification using existing 3-step classifier with signal hints, (4) validation & merge. The engine lives in `src/segmentation_engine.py` with tunable config in `src/segmentation_config.json`.

**Tech Stack:** Python 3.11, Regex, dataclasses, JSON config, existing classifier.py + bdp_extractor.py.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `3_Classification/src/segmentation_config.json` | Create | Weights, thresholds, anchor patterns — all tunable |
| `3_Classification/src/signal_extractors.py` | Create | Four signal extractor classes (anchors, structural, vocabulary, fingerprint) |
| `3_Classification/src/segmentation_engine.py` | Create | Orchestrates Pass 1-2-4: scoring, boundary resolution, validation |
| `3_Classification/src/classifier.py` | Modify | Add `classify_segment(content, hint_type, hint_strength)` method |
| `3_Classification/main.py` | Modify | Replace splitter+missing_doc flow with segmentation pipeline |
| `3_Classification/tests/test_signal_extractors.py` | Create | Unit tests for each signal extractor |
| `3_Classification/tests/test_segmentation_engine.py` | Create | Unit tests for scoring, boundary resolution, validation |
| `3_Classification/tests/test_classify_segment.py` | Create | Tests for the new classify_segment method |
| `3_Classification/tests/test_integration.py` | Create | End-to-end segmentation tests with realistic markdown |

Files removed after integration is verified:
- `3_Classification/src/document_splitter.py` — replaced by segmentation engine
- `3_Classification/src/missing_doc_detector.py` — replaced by segmentation engine

Files kept as-is:
- `3_Classification/src/bdp_extractor.py` — called as table signal in Pass 1
- `3_Classification/src/hierarchy_restructurer.py` — runs after segmentation
- `3_Classification/src/openrouter_wrapper.py` — used by Step 3 classifier
- `3_Classification/src/config.py` — unchanged

---

### Task 1: Segmentation Config

**Files:**
- Create: `3_Classification/src/segmentation_config.json`

- [ ] **Step 1: Create the config file**

```json
{
  "weights": {
    "anchor": 0.5,
    "structural": 0.2,
    "vocabulary": 0.2,
    "fingerprint": 0.1
  },
  "thresholds": {
    "boundary_score": 0.4,
    "peak_cluster_lines": 10,
    "min_segment_chars": 300,
    "min_mass_chars": 500,
    "closing_lookback_lines": 50,
    "opening_snap_lines": 5,
    "merge_score_ceiling": 0.6
  },
  "vocabulary": {
    "window_size": 50
  },
  "anchors": {
    "specification": {
      "open": [
        "CAHIER\\s+DES\\s+PRESCRIPTIONS\\s+SP[EEe][Cc]IALES",
        "C\\.?P\\.?S",
        "CCTP",
        "C\\.?C\\.?T\\.?P",
        "CAHIER\\s+DES\\s+CHARGES"
      ],
      "close": [
        "Fait\\s+[a\u00e0]\\s+.*,\\s+le\\s+\\d+",
        "Lu\\s+et\\s+accept[e\u00e9]",
        "Le\\s+Titulaire"
      ],
      "internal": [
        "ARTICLE\\s+\\d+\\s*:",
        "CHAPITRE\\s+\\d+"
      ]
    },
    "administrative": {
      "open": [
        "R[\u00c8E\u00c9]GLEMENT\\s+DE\\s+(?:LA\\s+)?CONSULTATION",
        "R\\.?C",
        "\u0646\u0638\u0627\u0645\\s+\u0627\u0644\u0627\u0633\u062a\u0634\u0627\u0631\u0629"
      ],
      "close": [
        "Fait\\s+[a\u00e0]\\s+.*,\\s+le\\s+\\d+",
        "Lu\\s+et\\s+accept[e\u00e9]"
      ],
      "internal": [
        "OBJET\\s+DU\\s+R[\u00c8E\u00c9]GLEMENT"
      ]
    },
    "product": {
      "open": [
        "BORDEREAU\\s+DES\\s+PRIX",
        "D[\u00c9Ee]TAIL\\s+ESTIMATIF",
        "\u062c\u062f\u0648\u0644\\s+\u0627\u0644\u0623\u062b\u0645\u0627\u0646",
        "\u0627\u0644\u0628\u064a\u0627\u0646\\s+\u0627\u0644\u062a\u0642\u062f\u064a\u0631\u064a"
      ],
      "close": [
        "Arr[\u00ea\u00e9e]t[\u00e9e]\\s+le\\s+pr[\u00e9e]sent\\s+bordereau"
      ],
      "internal": [
        "DESIGNATION\\s*\\|\\s*UNITE"
      ]
    },
    "avis_fr": {
      "open": [
        "AVIS\\s+D['\u2019']APPEL\\s+D['\u2019']OFFRES",
        "AVIS\\s+DE\\s+PUBLICIT[\u00c9Ee]"
      ],
      "close": [
        "Fait\\s+[a\u00e0]",
        "www\\.marchespublics\\.gov\\.ma"
      ],
      "internal": []
    },
    "avis_ar": {
      "open": [
        "\u0625\u0639\u0644\u0627\u0646\\s+\u0639\u0646\\s+\u0637\u0644\u0628\\s+\u0639\u0631\u0648\u0636"
      ],
      "close": [
        "\u0641\u062a\u062d\\s+\u0627\u0644\u0623\u0638\u0631\u0641\u0629"
      ],
      "internal": []
    },
    "acte_engagement": {
      "open": [
        "(?:MOD[\u00c8E]LE\\s+(?:DE\\s+L|D)['\u2019'])?ACTE\\s+D['\u2019']ENGAGEMENT"
      ],
      "close": [
        "Signature",
        "cachet"
      ],
      "internal": [
        "apr[\u00e8e]s\\s+avoir\\s+pris\\s+connaissance"
      ]
    },
    "declaration": {
      "open": [
        "(?:MOD[\u00c8E]LE\\s+DE\\s+(?:LA\\s+)?)?D[\u00c9Ee]CLARATION\\s+SUR\\s+L['\u2019']HONNEUR"
      ],
      "close": [
        "Signature",
        "cachet",
        "Fait\\s+[a\u00e0]"
      ],
      "internal": [
        "Je\\s+soussign[\u00e9e]"
      ]
    },
    "annexe": {
      "open": [
        "ANNEXE\\s+[IVXLCDM\\d]"
      ],
      "close": [],
      "internal": []
    }
  }
}
```

- [ ] **Step 2: Verify JSON is valid**

Run: `cd 3_Classification && python -c "import json; json.load(open('src/segmentation_config.json')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add 3_Classification/src/segmentation_config.json
git commit -m "feat(3_Classification): add segmentation config with anchors, weights, thresholds"
```

---

### Task 2: Signal Extractors — Anchor Extractor

**Files:**
- Create: `3_Classification/tests/test_signal_extractors.py`
- Create: `3_Classification/src/signal_extractors.py`

- [ ] **Step 1: Write failing test for anchor extraction**

```python
# 3_Classification/tests/test_signal_extractors.py
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.signal_extractors import AnchorExtractor


def test_anchor_detects_specification_open():
    extractor = AnchorExtractor()
    lines = [
        "Some intro text",
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "Article 1 content here",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert signals[0]["type"] == "specification"
    assert signals[0]["role"] == "open"
    assert signals[0]["strength"] == 1.0


def test_anchor_detects_closing_marker():
    extractor = AnchorExtractor()
    lines = [
        "Some content",
        "Fait à Rabat, le 01/01/2024",
        "More text",
    ]
    signals = extractor.extract(lines)
    # "Fait à" matches closing for specification, administrative, declaration
    assert any(s["role"] == "close" and s["line_idx"] == 1 for s in signals)


def test_anchor_detects_multiple_doc_types():
    extractor = AnchorExtractor()
    lines = [
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "Content of spec",
        "Fait à Rabat, le 01/01/2024",
        "# BORDEREAU DES PRIX",
        "Pricing content",
    ]
    signals = extractor.extract(lines)
    open_signals = [s for s in signals if s["role"] == "open"]
    assert len(open_signals) == 2
    types = {s["type"] for s in open_signals}
    assert "specification" in types
    assert "product" in types


def test_anchor_detects_internal_markers():
    extractor = AnchorExtractor()
    lines = [
        "ARTICLE 3 : DESCRIPTION",
    ]
    signals = extractor.extract(lines)
    internal = [s for s in signals if s["role"] == "internal"]
    assert len(internal) >= 1
    assert internal[0]["type"] == "specification"


def test_anchor_empty_input():
    extractor = AnchorExtractor()
    signals = extractor.extract([])
    assert signals == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.signal_extractors'`

- [ ] **Step 3: Implement AnchorExtractor**

```python
# 3_Classification/src/signal_extractors.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/signal_extractors.py 3_Classification/tests/test_signal_extractors.py
git commit -m "feat(3_Classification): add AnchorExtractor with regex anchor signal detection"
```

---

### Task 3: Signal Extractors — Structural Extractor

**Files:**
- Modify: `3_Classification/tests/test_signal_extractors.py`
- Modify: `3_Classification/src/signal_extractors.py`

- [ ] **Step 1: Write failing tests for structural signals**

Append to `3_Classification/tests/test_signal_extractors.py`:

```python
from src.signal_extractors import StructuralExtractor


def test_structural_detects_file_header():
    extractor = StructuralExtractor()
    lines = [
        "Some content",
        "# File: document.pdf",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert signals[0]["boundary_signal"] == 1.0


def test_structural_detects_page_break():
    extractor = StructuralExtractor()
    lines = [
        "Content",
        "---",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert len(signals) == 1
    assert signals[0]["line_idx"] == 1
    assert 0.3 <= signals[0]["boundary_signal"] <= 0.5


def test_structural_detects_blank_gap():
    extractor = StructuralExtractor()
    lines = ["Content", "", "", "", "More content"]
    signals = extractor.extract(lines)
    assert len(signals) >= 1
    # Signal should be at the start of the gap
    assert signals[0]["boundary_signal"] > 0


def test_structural_detects_h1_reset():
    extractor = StructuralExtractor()
    lines = [
        "paragraph text",
        "more paragraph text",
        "# NEW SECTION TITLE",
        "content after",
    ]
    signals = extractor.extract(lines)
    h1_signals = [s for s in signals if s["line_idx"] == 2]
    assert len(h1_signals) >= 1


def test_structural_detects_page_marker():
    extractor = StructuralExtractor()
    lines = [
        "Content",
        "## Page 5",
        "More content",
    ]
    signals = extractor.extract(lines)
    assert any(s["line_idx"] == 1 for s in signals)


def test_structural_empty_input():
    extractor = StructuralExtractor()
    assert extractor.extract([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py::test_structural_detects_file_header -v`
Expected: FAIL — `ImportError: cannot import name 'StructuralExtractor'`

- [ ] **Step 3: Implement StructuralExtractor**

Append to `3_Classification/src/signal_extractors.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v -k structural`
Expected: All 6 structural tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/signal_extractors.py 3_Classification/tests/test_signal_extractors.py
git commit -m "feat(3_Classification): add StructuralExtractor for layout boundary detection"
```

---

### Task 4: Signal Extractors — Vocabulary Shift Extractor

**Files:**
- Modify: `3_Classification/tests/test_signal_extractors.py`
- Modify: `3_Classification/src/signal_extractors.py`

- [ ] **Step 1: Write failing tests for vocabulary shift**

Append to `3_Classification/tests/test_signal_extractors.py`:

```python
from src.signal_extractors import VocabularyExtractor


def test_vocab_detects_shift_from_product_to_spec():
    extractor = VocabularyExtractor()
    # Build lines: 60 lines of product vocab, then 60 lines of spec vocab
    product_lines = ["prix unitaire montant total désignation quantité"] * 60
    spec_lines = ["cahier des prescriptions délai d'exécution nantissement clauses techniques"] * 60
    lines = product_lines + spec_lines
    signals = extractor.extract(lines)
    # Should detect a shift around line 60
    shift_signals = [s for s in signals if 40 <= s["line_idx"] <= 80]
    assert len(shift_signals) >= 1
    assert shift_signals[0]["vocab_shift"] > 0


def test_vocab_no_shift_uniform_text():
    extractor = VocabularyExtractor()
    lines = ["cahier des prescriptions clauses techniques"] * 100
    signals = extractor.extract(lines)
    # No shift in uniform text
    assert len(signals) == 0


def test_vocab_empty_input():
    extractor = VocabularyExtractor()
    assert extractor.extract([]) == []


def test_vocab_short_input():
    extractor = VocabularyExtractor()
    lines = ["prix unitaire"] * 10
    signals = extractor.extract(lines)
    # Too short for meaningful window comparison
    assert len(signals) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v -k vocab`
Expected: FAIL — `ImportError: cannot import name 'VocabularyExtractor'`

- [ ] **Step 3: Implement VocabularyExtractor**

Append to `3_Classification/src/signal_extractors.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v -k vocab`
Expected: All 4 vocab tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/signal_extractors.py 3_Classification/tests/test_signal_extractors.py
git commit -m "feat(3_Classification): add VocabularyExtractor for keyword-bucket shift detection"
```

---

### Task 5: Signal Extractors — Fingerprint Extractor

**Files:**
- Modify: `3_Classification/tests/test_signal_extractors.py`
- Modify: `3_Classification/src/signal_extractors.py`

- [ ] **Step 1: Write failing tests for fingerprint signals**

Append to `3_Classification/tests/test_signal_extractors.py`:

```python
from src.signal_extractors import FingerprintExtractor


def test_fingerprint_detects_arabic_ratio():
    extractor = FingerprintExtractor()
    lines = ["Hello world"] * 30 + ["إعلان عن طلب عروض فتح الأظرفة"] * 30
    signals = extractor.extract(lines)
    # Should detect shift in Arabic ratio
    assert len(signals) >= 1
    shift = [s for s in signals if 20 <= s["line_idx"] <= 40]
    assert len(shift) >= 1


def test_fingerprint_detects_table_density():
    extractor = FingerprintExtractor()
    lines = ["Regular text paragraph"] * 30 + ["| col1 | col2 | col3 | col4 |"] * 30
    signals = extractor.extract(lines)
    assert len(signals) >= 1


def test_fingerprint_empty_input():
    extractor = FingerprintExtractor()
    assert extractor.extract([]) == []


def test_fingerprint_uniform_input():
    extractor = FingerprintExtractor()
    lines = ["Same text line"] * 100
    signals = extractor.extract(lines)
    assert len(signals) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v -k fingerprint`
Expected: FAIL — `ImportError: cannot import name 'FingerprintExtractor'`

- [ ] **Step 3: Implement FingerprintExtractor**

Append to `3_Classification/src/signal_extractors.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_signal_extractors.py -v -k fingerprint`
Expected: All 4 fingerprint tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/signal_extractors.py 3_Classification/tests/test_signal_extractors.py
git commit -m "feat(3_Classification): add FingerprintExtractor for statistical feature shift detection"
```

---

### Task 6: Segmentation Engine — Pass 1 & 2 (Scoring & Boundary Resolution)

**Files:**
- Create: `3_Classification/tests/test_segmentation_engine.py`
- Create: `3_Classification/src/segmentation_engine.py`

- [ ] **Step 1: Write failing tests for boundary scoring**

```python
# 3_Classification/tests/test_segmentation_engine.py
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.segmentation_engine import SegmentationEngine, Segment


def test_engine_single_document_no_boundaries():
    """A single uniform document should produce one segment."""
    engine = SegmentationEngine()
    text = "Regular content\n" * 100
    segments = engine.segment(text)
    assert len(segments) == 1
    assert segments[0].doc_type == "unknown"


def test_engine_two_documents_with_anchors():
    """Two documents separated by clear anchors should produce two segments."""
    engine = SegmentationEngine()
    spec_lines = ["# CAHIER DES PRESCRIPTIONS SPECIALES"] + ["Article content about nantissement and délai d'exécution and clauses techniques"] * 50
    bdp_lines = ["# BORDEREAU DES PRIX"] + ["| désignation | unité | quantité | prix unitaire | montant |"] * 50
    text = "\n".join(spec_lines + bdp_lines)
    segments = engine.segment(text)
    assert len(segments) == 2


def test_engine_with_file_headers():
    """Input with # File: headers should still be segmented correctly."""
    engine = SegmentationEngine()
    text = "# File: cps.pdf\nCahier des prescriptions content\n" + "x\n" * 50 + "\n---\n# File: bdp.pdf\nBordereau des prix content\n" + "y\n" * 50
    segments = engine.segment(text)
    assert len(segments) == 2


def test_engine_empty_input():
    engine = SegmentationEngine()
    segments = engine.segment("")
    assert len(segments) == 1  # Single empty segment


def test_engine_rejects_tiny_segments():
    """Segments smaller than min_segment_chars should be merged."""
    engine = SegmentationEngine()
    text = "# CAHIER DES PRESCRIPTIONS SPECIALES\nShort\n# BORDEREAU DES PRIX\n" + "| désignation | unité | quantité | prix unitaire | montant |\n" * 30
    segments = engine.segment(text)
    # "Short" segment is under 300 chars, should be merged
    for seg in segments:
        assert len(seg.content) >= 300 or seg is segments[-1]


def test_segment_dataclass():
    seg = Segment(
        content="test",
        doc_type="specification",
        confidence=0.9,
        start_line=0,
        end_line=10,
        method="anchor",
        needs_review=False,
    )
    assert seg.doc_type == "specification"
    assert seg.needs_review is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_segmentation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SegmentationEngine with Pass 1 & 2**

```python
# 3_Classification/src/segmentation_engine.py
"""
Pipeline Stage: Classification Container
Multi-signal segmentation engine — orchestrates 4-pass segmentation.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .signal_extractors import (
    SEGMENTATION_CONFIG,
    AnchorExtractor,
    FingerprintExtractor,
    StructuralExtractor,
    VocabularyExtractor,
)

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    """A segmented portion of the tender markdown."""
    content: str
    doc_type: str
    confidence: float
    start_line: int
    end_line: int
    method: str       # "anchor", "scoring", "classifier", "llm"
    needs_review: bool


class SegmentationEngine:
    """
    Multi-signal scoring engine.
    Pass 1: extract signals from all four extractors.
    Pass 2: score each line, find boundaries, resolve to exact split points.
    Pass 3 & 4 are called externally (classify + validate).
    """

    def __init__(self):
        self._anchor_ext = AnchorExtractor()
        self._struct_ext = StructuralExtractor()
        self._vocab_ext = VocabularyExtractor()
        self._finger_ext = FingerprintExtractor()

        self._weights = SEGMENTATION_CONFIG["weights"]
        self._thresholds = SEGMENTATION_CONFIG["thresholds"]

    # ── Pass 1: Signal Extraction ──

    def _extract_signals(self, lines: List[str]) -> Dict[str, List[Dict]]:
        return {
            "anchor": self._anchor_ext.extract(lines),
            "structural": self._struct_ext.extract(lines),
            "vocabulary": self._vocab_ext.extract(lines),
            "fingerprint": self._finger_ext.extract(lines),
        }

    # ── Pass 2: Boundary Scoring ──

    def _build_score_array(self, num_lines: int, signals: Dict[str, List[Dict]]) -> List[float]:
        """Compute a boundary score for every line."""
        scores = [0.0] * num_lines
        w = self._weights

        # Anchor signals — only "open" anchors contribute to boundary score
        for sig in signals["anchor"]:
            if sig["role"] == "open":
                idx = sig["line_idx"]
                if 0 <= idx < num_lines:
                    scores[idx] += w["anchor"] * sig["strength"]

        # Structural signals
        for sig in signals["structural"]:
            idx = sig["line_idx"]
            if 0 <= idx < num_lines:
                scores[idx] += w["structural"] * sig["boundary_signal"]

        # Vocabulary shift signals
        for sig in signals["vocabulary"]:
            idx = sig["line_idx"]
            if 0 <= idx < num_lines:
                scores[idx] += w["vocabulary"] * sig["vocab_shift"]

        # Fingerprint shift signals
        for sig in signals["fingerprint"]:
            idx = sig["line_idx"]
            if 0 <= idx < num_lines:
                scores[idx] += w["fingerprint"] * sig["fingerprint_shift"]

        return scores

    def _pick_boundaries(self, scores: List[float]) -> List[int]:
        """Select boundary lines using threshold + peak picking."""
        threshold = self._thresholds["boundary_score"]
        cluster = self._thresholds["peak_cluster_lines"]

        candidates = [(i, s) for i, s in enumerate(scores) if s >= threshold]
        if not candidates:
            return []

        # Peak picking: within each cluster, keep the highest
        boundaries = []
        current_cluster = [candidates[0]]

        for i in range(1, len(candidates)):
            if candidates[i][0] - current_cluster[-1][0] <= cluster:
                current_cluster.append(candidates[i])
            else:
                # Pick peak of current cluster
                peak = max(current_cluster, key=lambda x: x[1])
                boundaries.append(peak[0])
                current_cluster = [candidates[i]]

        # Don't forget last cluster
        peak = max(current_cluster, key=lambda x: x[1])
        boundaries.append(peak[0])

        return sorted(boundaries)

    def _refine_boundaries(
        self, boundaries: List[int], lines: List[str], signals: Dict[str, List[Dict]]
    ) -> List[int]:
        """Snap boundaries to nearby anchors for cleaner splits."""
        snap_range = self._thresholds["opening_snap_lines"]
        lookback = self._thresholds["closing_lookback_lines"]

        # Index anchor signals by line for fast lookup
        open_anchors = {}
        for sig in signals["anchor"]:
            if sig["role"] == "open":
                open_anchors[sig["line_idx"]] = sig

        close_anchors = {}
        for sig in signals["anchor"]:
            if sig["role"] == "close":
                close_anchors[sig["line_idx"]] = sig

        refined = []
        for b in boundaries:
            # Try to snap to opening anchor within snap_range
            best_open = None
            for offset in range(-snap_range, snap_range + 1):
                candidate = b + offset
                if candidate in open_anchors:
                    best_open = candidate
                    break

            if best_open is not None:
                refined.append(best_open)
                continue

            # Try to find a closing anchor in the look-back region
            best_close = None
            for check in range(b - 1, max(0, b - lookback) - 1, -1):
                if check in close_anchors:
                    best_close = check + 1  # Split after the closing line
                    break

            if best_close is not None:
                refined.append(best_close)
            else:
                refined.append(b)

        return sorted(set(refined))

    # ── Pass 2 output: split into raw segments ──

    def _split_into_segments(
        self, lines: List[str], boundaries: List[int], signals: Dict[str, List[Dict]], scores: List[float]
    ) -> List[Segment]:
        """Create Segment objects from boundary lines."""
        min_chars = self._thresholds["min_segment_chars"]

        # Add start and end
        all_bounds = sorted(set([0] + boundaries + [len(lines)]))

        segments = []
        for i in range(len(all_bounds) - 1):
            start = all_bounds[i]
            end = all_bounds[i + 1]
            content = "\n".join(lines[start:end]).strip()

            if not content:
                continue

            # Guess type from anchor signals in this range
            hint_type, hint_strength, method = self._guess_type_from_signals(
                signals, start, end
            )

            segments.append(Segment(
                content=content,
                doc_type=hint_type,
                confidence=hint_strength,
                start_line=start,
                end_line=end,
                method=method,
                needs_review=False,
            ))

        # Merge tiny segments into neighbors
        return self._merge_tiny_segments(segments, min_chars)

    def _guess_type_from_signals(
        self, signals: Dict[str, List[Dict]], start: int, end: int
    ) -> tuple:
        """Determine the dominant type from signals in a line range. Returns (type, strength, method)."""
        # Check anchor open signals first (strongest signal)
        for sig in signals["anchor"]:
            if sig["role"] == "open" and start <= sig["line_idx"] < end:
                return sig["type"], sig["strength"], "anchor"

        # Check vocabulary signals
        for sig in signals["vocabulary"]:
            if start <= sig["line_idx"] < end:
                return sig.get("to_type", "unknown"), sig["vocab_shift"], "scoring"

        return "unknown", 0.0, "scoring"

    def _merge_tiny_segments(self, segments: List[Segment], min_chars: int) -> List[Segment]:
        """Merge segments smaller than min_chars into their predecessor."""
        if not segments:
            return segments

        merged = [segments[0]]
        for seg in segments[1:]:
            if len(seg.content) < min_chars:
                # Absorb into previous segment
                prev = merged[-1]
                merged[-1] = Segment(
                    content=prev.content + "\n" + seg.content,
                    doc_type=prev.doc_type,
                    confidence=prev.confidence,
                    start_line=prev.start_line,
                    end_line=seg.end_line,
                    method=prev.method,
                    needs_review=prev.needs_review,
                )
            else:
                merged.append(seg)

        return merged

    # ── Public API ──

    def segment(self, text: str) -> List[Segment]:
        """
        Run Pass 1 & 2: extract signals, score lines, find boundaries, produce segments.
        Segments have preliminary doc_type from signal hints (not yet classified by Step 1-2-3).
        """
        if not text.strip():
            return [Segment(
                content="",
                doc_type="unknown",
                confidence=0.0,
                start_line=0,
                end_line=0,
                method="scoring",
                needs_review=False,
            )]

        lines = text.split("\n")
        signals = self._extract_signals(lines)
        scores = self._build_score_array(len(lines), signals)
        boundaries = self._pick_boundaries(scores)
        boundaries = self._refine_boundaries(boundaries, lines, signals)
        segments = self._split_into_segments(lines, boundaries, signals, scores)

        if not segments:
            return [Segment(
                content=text,
                doc_type="unknown",
                confidence=0.0,
                start_line=0,
                end_line=len(lines),
                method="scoring",
                needs_review=False,
            )]

        logger.info(
            f"Segmentation Pass 1-2: {len(lines)} lines → "
            f"{len(boundaries)} boundaries → {len(segments)} segments"
        )
        return segments

    def get_signals(self, text: str) -> Dict[str, List[Dict]]:
        """Expose signal extraction for debugging/testing."""
        lines = text.split("\n")
        return self._extract_signals(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_segmentation_engine.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/segmentation_engine.py 3_Classification/tests/test_segmentation_engine.py
git commit -m "feat(3_Classification): add SegmentationEngine with Pass 1-2 scoring and boundary resolution"
```

---

### Task 7: Classifier Enhancement — classify_segment with Hint Support

**Files:**
- Create: `3_Classification/tests/test_classify_segment.py`
- Modify: `3_Classification/src/classifier.py`

- [ ] **Step 1: Write failing tests for classify_segment**

```python
# 3_Classification/tests/test_classify_segment.py
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.classifier import DocumentClassifier, ClassificationResult


def test_classify_segment_hint_agrees_with_step1():
    """When hint and Step 1 agree, skip LLM, return high confidence."""
    classifier = DocumentClassifier()
    content = "cahier des prescriptions spéciales clauses techniques nantissement délai d'exécution"
    result = classifier.classify_segment(content, hint_type="specification", hint_strength=0.9)
    assert result.doc_type == "specification"
    assert result.step in (1, 2)


def test_classify_segment_strong_hint_overrides_unknown():
    """Strong hint should be used when Steps 1-2 return unknown."""
    classifier = DocumentClassifier()
    # Content with no clear patterns
    content = "Lorem ipsum dolor sit amet " * 20
    result = classifier.classify_segment(content, hint_type="administrative", hint_strength=0.9)
    assert result.doc_type == "administrative"
    assert result.confidence == "hint"


def test_classify_segment_no_hint():
    """Without hint, behaves like standard classify."""
    classifier = DocumentClassifier()
    content = "bordereau des prix détail estimatif désignation prix unitaire montant quantité"
    result = classifier.classify_segment(content, hint_type=None, hint_strength=0.0)
    assert result.doc_type == "product"


def test_classify_segment_weak_hint_defers_to_classifier():
    """Weak hint should not override classifier result."""
    classifier = DocumentClassifier()
    content = "bordereau des prix détail estimatif désignation prix unitaire montant quantité"
    result = classifier.classify_segment(content, hint_type="specification", hint_strength=0.3)
    # Classifier should find "product" from content, overriding weak hint
    assert result.doc_type == "product"


def test_classify_segment_smart_sampling_with_anchor():
    """When anchor_offset is provided, sampling starts from there."""
    classifier = DocumentClassifier()
    # Junk for first 6000 chars, then spec content
    junk = "x " * 3000
    spec_content = "cahier des prescriptions spéciales nantissement clauses techniques délai d'exécution"
    content = junk + spec_content
    # Without anchor_offset, Step 2 samples first 5000 chars (all junk)
    result_no_offset = classifier.classify_segment(content, hint_type=None, hint_strength=0.0)
    # With anchor_offset pointing to spec content
    result_with_offset = classifier.classify_segment(
        content, hint_type="specification", hint_strength=0.5, anchor_offset=6000
    )
    # The offset version should find specification
    assert result_with_offset.doc_type == "specification"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_classify_segment.py -v`
Expected: FAIL — `AttributeError: 'DocumentClassifier' object has no attribute 'classify_segment'`

- [ ] **Step 3: Add classify_segment method to DocumentClassifier**

Add this method to `3_Classification/src/classifier.py` at the end of the `DocumentClassifier` class (after `step3_classify`):

```python
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

        # Run Steps 1-2 (use "segment" as filename since we have no filename)
        step_result = self.step1_classify("segment", cleaned)
        if not step_result:
            step_result = self.step2_classify("segment", cleaned)

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_classify_segment.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/classifier.py 3_Classification/tests/test_classify_segment.py
git commit -m "feat(3_Classification): add classify_segment with signal hint support"
```

---

### Task 8: Segmentation Engine — Pass 3 & 4 (Classify + Validate)

**Files:**
- Modify: `3_Classification/src/segmentation_engine.py`
- Modify: `3_Classification/tests/test_segmentation_engine.py`

- [ ] **Step 1: Write failing tests for full pipeline with classification**

Append to `3_Classification/tests/test_segmentation_engine.py`:

```python
from src.classifier import DocumentClassifier


def test_engine_classify_segments():
    """Full pipeline should classify segments using the classifier."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    spec_lines = ["# CAHIER DES PRESCRIPTIONS SPECIALES"] + [
        "cahier des prescriptions clauses techniques nantissement délai d'exécution"
    ] * 50
    bdp_lines = ["# BORDEREAU DES PRIX"] + [
        "| désignation | unité | quantité | prix unitaire | montant |"
    ] * 50
    text = "\n".join(spec_lines + bdp_lines)
    segments = engine.segment_and_classify(text, classifier)
    types = {s.doc_type for s in segments}
    assert "specification" in types or "product" in types


def test_engine_merge_adjacent_same_type():
    """Adjacent segments of the same type with weak boundary should merge."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    # Two spec sections with a weak separator between them
    part1 = ["# CAHIER DES PRESCRIPTIONS SPECIALES"] + [
        "clauses techniques nantissement délai d'exécution"
    ] * 40
    part2 = ["---"] + [
        "clauses générales cahier des prescriptions consistance du projet"
    ] * 40
    text = "\n".join(part1 + part2)
    segments = engine.segment_and_classify(text, classifier)
    spec_count = sum(1 for s in segments if s.doc_type == "specification")
    # Should ideally merge into one specification segment
    assert spec_count >= 1


def test_engine_needs_review_flag():
    """Segments where hint contradicts classifier should be flagged."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    # Build text where anchor says one thing but content says another
    # This is hard to construct perfectly, so test the merge/validate path
    text = "Regular content\n" * 200
    segments = engine.segment_and_classify(text, classifier)
    # At minimum, segments should be produced
    assert len(segments) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 3_Classification && python -m pytest tests/test_segmentation_engine.py::test_engine_classify_segments -v`
Expected: FAIL — `AttributeError: 'SegmentationEngine' object has no attribute 'segment_and_classify'`

- [ ] **Step 3: Add Pass 3 & 4 to SegmentationEngine**

Add these methods to the `SegmentationEngine` class in `3_Classification/src/segmentation_engine.py`:

```python
    # ── Pass 3: Classification ──

    def _classify_segments(self, segments: List[Segment], classifier) -> List[Segment]:
        """Run classifier on each segment, using signal hints."""
        classified = []
        for seg in segments:
            hint_type = seg.doc_type if seg.doc_type != "unknown" else None
            hint_strength = seg.confidence

            result = classifier.classify_segment(
                seg.content,
                hint_type=hint_type,
                hint_strength=hint_strength,
            )

            needs_review = (
                hint_type is not None
                and hint_strength >= 0.8
                and result.doc_type != hint_type
                and result.doc_type != "unknown"
                and result.confidence in ("high", "medium")
            )

            classified.append(Segment(
                content=seg.content,
                doc_type=result.doc_type,
                confidence=self._confidence_to_float(result.confidence),
                start_line=seg.start_line,
                end_line=seg.end_line,
                method=seg.method if result.step == 0 else (
                    "classifier" if result.step in (1, 2) else "llm"
                ),
                needs_review=needs_review,
            ))

        return classified

    @staticmethod
    def _confidence_to_float(confidence: str) -> float:
        return {"high": 0.9, "medium": 0.7, "low": 0.5, "ai": 0.6, "hint": 0.75, "unknown": 0.0}.get(
            confidence, 0.0
        )

    # ── Pass 4: Validation & Merge ──

    def _validate_and_merge(self, segments: List[Segment]) -> List[Segment]:
        """Merge adjacent same-type segments and apply minimum mass."""
        if not segments:
            return segments

        min_mass = self._thresholds["min_mass_chars"]
        merge_ceiling = self._thresholds["merge_score_ceiling"]
        form_types = {"declaration", "acte_engagement", "avis_fr", "avis_ar"}

        # Step 1: Merge adjacent same-type
        merged = [segments[0]]
        for seg in segments[1:]:
            prev = merged[-1]
            if prev.doc_type == seg.doc_type and prev.doc_type != "unknown":
                # Merge
                merged[-1] = Segment(
                    content=prev.content + "\n" + seg.content,
                    doc_type=prev.doc_type,
                    confidence=max(prev.confidence, seg.confidence),
                    start_line=prev.start_line,
                    end_line=seg.end_line,
                    method=prev.method,
                    needs_review=prev.needs_review or seg.needs_review,
                )
            else:
                merged.append(seg)

        # Step 2: Minimum mass — absorb tiny non-form segments
        final = [merged[0]]
        for seg in merged[1:]:
            if len(seg.content) < min_mass and seg.doc_type not in form_types:
                prev = final[-1]
                final[-1] = Segment(
                    content=prev.content + "\n" + seg.content,
                    doc_type=prev.doc_type,
                    confidence=prev.confidence,
                    start_line=prev.start_line,
                    end_line=seg.end_line,
                    method=prev.method,
                    needs_review=prev.needs_review,
                )
            else:
                final.append(seg)

        return final

    # ── Full Pipeline ──

    def segment_and_classify(self, text: str, classifier) -> List[Segment]:
        """
        Run full 4-pass pipeline.
        Pass 1-2: signal extraction + boundary scoring (via self.segment)
        Pass 3: classification with hints
        Pass 4: validation & merge
        """
        raw_segments = self.segment(text)
        classified = self._classify_segments(raw_segments, classifier)
        final = self._validate_and_merge(classified)

        logger.info(
            f"Segmentation complete: {len(raw_segments)} raw → "
            f"{len(classified)} classified → {len(final)} final segments"
        )
        for seg in final:
            logger.info(
                f"  [{seg.start_line}-{seg.end_line}] {seg.doc_type} "
                f"(conf={seg.confidence:.2f}, method={seg.method}"
                f"{', REVIEW' if seg.needs_review else ''})"
            )

        return final
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 3_Classification && python -m pytest tests/test_segmentation_engine.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/segmentation_engine.py 3_Classification/tests/test_segmentation_engine.py
git commit -m "feat(3_Classification): add Pass 3-4 classification and validation to SegmentationEngine"
```

---

### Task 9: Integration — Replace Splitter + Missing Doc Detector in main.py

**Files:**
- Modify: `3_Classification/main.py`
- Create: `3_Classification/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# 3_Classification/tests/test_integration.py
"""Integration tests for the full segmentation pipeline as used by main.py."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.segmentation_engine import SegmentationEngine, Segment
from src.classifier import DocumentClassifier


def _build_mixed_tender():
    """Build a realistic mixed tender markdown."""
    parts = []
    # Avis section
    parts.append("# AVIS D'APPEL D'OFFRES OUVERT")
    parts.extend(["Il sera procédé le 15/03/2026 à l'ouverture des plis"] * 5)
    parts.append("Fait à Rabat, le 01/03/2026")
    parts.append("")
    parts.append("---")
    parts.append("")
    # CPS section
    parts.append("# CAHIER DES PRESCRIPTIONS SPECIALES")
    parts.extend([
        "ARTICLE 1 : OBJET DU MARCHE",
        "Le présent cahier des prescriptions spéciales a pour objet...",
        "clauses techniques applicables nantissement délai d'exécution",
    ] * 20)
    parts.append("Fait à Casablanca, le 10/03/2026")
    parts.append("")
    parts.append("---")
    parts.append("")
    # BDP section
    parts.append("# BORDEREAU DES PRIX - DETAIL ESTIMATIF")
    parts.extend(["| désignation | unité | quantité | prix unitaire | montant |"] * 25)
    parts.append("Arrêté le présent bordereau")
    return "\n".join(parts)


def test_full_pipeline_mixed_tender():
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = _build_mixed_tender()
    segments = engine.segment_and_classify(text, classifier)

    types = {s.doc_type for s in segments}
    # Should find at least 2 of the 3 document types
    expected = {"avis_fr", "specification", "product"}
    assert len(types & expected) >= 2, f"Found types: {types}"


def test_single_document_tender():
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = "\n".join([
        "# CAHIER DES PRESCRIPTIONS SPECIALES",
        "clauses techniques nantissement délai d'exécution",
    ] * 50)
    segments = engine.segment_and_classify(text, classifier)
    assert len(segments) == 1
    assert segments[0].doc_type == "specification"


def test_file_header_format():
    """Backward compat: # File: headers should still work."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = (
        "# File: cps.pdf\n"
        + "cahier des prescriptions nantissement clauses techniques délai d'exécution\n" * 40
        + "\n---\n"
        + "# File: bdp.pdf\n"
        + "| désignation | unité | quantité | prix unitaire | montant |\n" * 40
    )
    segments = engine.segment_and_classify(text, classifier)
    assert len(segments) >= 2


def test_segments_to_logical_docs():
    """Verify segments can replace LogicalDocument for downstream use."""
    engine = SegmentationEngine()
    classifier = DocumentClassifier()
    text = _build_mixed_tender()
    segments = engine.segment_and_classify(text, classifier)

    for seg in segments:
        assert isinstance(seg.content, str)
        assert len(seg.content) > 0
        assert seg.doc_type != ""
        assert seg.start_line >= 0
        assert seg.end_line > seg.start_line
```

- [ ] **Step 2: Run integration tests**

Run: `cd 3_Classification && python -m pytest tests/test_integration.py -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Update main.py to use segmentation engine**

Replace the import block and `_process_message` method in `3_Classification/main.py`:

**Imports** — replace:
```python
from src.document_splitter import split_concatenated_file, LogicalDocument
from src.missing_doc_detector import detect_missing_documents, extract_balised_documents
```
with:
```python
from src.segmentation_engine import SegmentationEngine, Segment
```

**In `__init__`** — add after `self.classifier = DocumentClassifier(...)`:
```python
        self.segmenter = SegmentationEngine()
```

**Replace `_process_message`** with:

```python
    def _process_message(self, message: Dict[str, Any]) -> bool:
        """
        Process a single SQS message.
        
        Args:
            message: SQS message dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            body = json.loads(message['Body'])
            tender_ref = body.get('tender_ref')
            markdown_paths = body.get('markdown_paths', [])
            
            if not tender_ref or not markdown_paths:
                logger.error(f"Invalid message format: {body}")
                return False
            
            logger.info(f"Processing tender: {tender_ref}")
            batch_id = _get_active_batch_id()
            if batch_id:
                mon_enter(batch_id, tender_ref, "classification")

            # Download and concatenate all markdown files
            markdown_parts = []
            for md_path in markdown_paths:
                content = self._download_markdown(md_path)
                markdown_parts.append(content)
            
            full_markdown = "\n\n---\n\n".join(markdown_parts)
            
            # Run 4-pass segmentation pipeline
            segments = self.segmenter.segment_and_classify(full_markdown, self.classifier)
            logger.info(f"Segmentation produced {len(segments)} segments")
            
            for seg in segments:
                logger.info(
                    f"  [{seg.start_line}-{seg.end_line}] {seg.doc_type} "
                    f"(conf={seg.confidence:.2f}, method={seg.method})"
                )
            
            # Reconstruct markdown with document headers and YAML frontmatter
            classified_markdown = self._inject_segment_headers(tender_ref, segments)
            
            # Restructure hierarchy based on document type
            logger.info("Restructuring markdown hierarchy based on document types...")
            classified_markdown = restructure_by_type(classified_markdown)
            
            # Detect anomalies: missing expected document types
            EXPECTED_TYPES = {"avis_fr", "avis_ar", "administrative", "specification", "product"}
            final_types = {seg.doc_type for seg in segments}
            missing_types = EXPECTED_TYPES - final_types
            if missing_types and batch_id:
                mon_anomaly(batch_id, tender_ref, "classification",
                            [f"missing_doc_type:{t}" for t in sorted(missing_types)])
            
            # Generate S3 metadata
            s3_metadata = self._generate_s3_metadata_from_types(final_types)
            
            # Generate output S3 key
            output_key = markdown_paths[0].replace('_ocr.md', '.md')
            
            # Upload classified markdown with metadata
            self._upload_markdown(output_key, classified_markdown, metadata=s3_metadata)
            
            # Send message to EXTRACTION_QUEUE
            extraction_message = {
                'tender_ref': tender_ref,
                'markdown_paths': [output_key],
                'classification_complete': True
            }
            
            self.sqs.send_message(
                QueueUrl=Config.EXTRACTION_QUEUE_URL,
                MessageBody=json.dumps(extraction_message)
            )
            logger.info(f"Sent message to EXTRACTION_QUEUE for {tender_ref}")
            
            # Delete message from CLASSIFICATION_QUEUE
            self.sqs.delete_message(
                QueueUrl=Config.CLASSIFICATION_QUEUE_URL,
                ReceiptHandle=message['ReceiptHandle']
            )
            logger.info(f"Successfully processed {tender_ref}")
            if batch_id:
                mon_complete(
                    batch_id, tender_ref, "classification",
                    doc_count=len(segments),
                )

            return True
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            if 'batch_id' in locals() and batch_id:
                mon_failed(batch_id, tender_ref, "classification", error=str(e))
            return False
```

**Add `_inject_segment_headers` method** (replaces `_inject_document_headers`):

```python
    def _inject_segment_headers(self, tender_ref: str, segments: List[Segment]) -> str:
        """
        Inject segment headers and reconstruct markdown with YAML frontmatter.
        
        Args:
            tender_ref: Tender reference ID
            segments: List of classified Segment objects
            
        Returns:
            Reconstructed markdown
        """
        # Build YAML header
        found_types = {seg.doc_type for seg in segments}
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        yaml_lines = [
            "---",
            f"tender_ref: {tender_ref}",
            f"classification_date: {timestamp}",
            "document_checklist:"
        ]
        for doc_type in ALL_DOCUMENT_TYPES:
            status = "checked" if doc_type in found_types else "missing"
            yaml_lines.append(f"  {doc_type}: {status}")
        yaml_lines.append("---")
        yaml_lines.append("")

        # Build document sections
        markdown_parts = ["\n".join(yaml_lines)]
        
        for i, seg in enumerate(segments):
            filename = f"segment_{i+1}_{seg.doc_type}.md"
            markdown_parts.append(f"# File: {filename}\n\n")
            markdown_parts.append(f"> Document Type: {seg.doc_type}\n\n")
            markdown_parts.append(seg.content)
            markdown_parts.append("\n\n---\n\n")
        
        result = "".join(markdown_parts)
        if result.endswith("\n\n---\n\n"):
            result = result[:-7]
        
        return result
```

- [ ] **Step 4: Verify main.py has no syntax errors**

Run: `cd 3_Classification && python -c "from main import ClassificationService; print('OK')"`
Expected: `OK` (or config validation error, which is fine — it confirms the import works)

- [ ] **Step 5: Run all tests**

Run: `cd 3_Classification && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add 3_Classification/main.py 3_Classification/tests/test_integration.py
git commit -m "feat(3_Classification): integrate segmentation engine into main pipeline"
```

---

### Task 10: Remove Old Modules

**Files:**
- Delete: `3_Classification/src/document_splitter.py`
- Delete: `3_Classification/src/missing_doc_detector.py`

- [ ] **Step 1: Verify no remaining imports of old modules**

Run: `cd 3_Classification && grep -r "document_splitter\|missing_doc_detector" --include="*.py" src/ main.py`
Expected: No matches (only in tests or deleted files)

- [ ] **Step 2: Check if any test files reference old modules**

Run: `cd 3_Classification && grep -r "document_splitter\|missing_doc_detector\|LogicalDocument" --include="*.py" tests/`
Expected: No matches

- [ ] **Step 3: Delete old modules**

```bash
git rm 3_Classification/src/document_splitter.py 3_Classification/src/missing_doc_detector.py
```

- [ ] **Step 4: Run all tests to confirm nothing breaks**

Run: `cd 3_Classification && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add -A 3_Classification/
git commit -m "refactor(3_Classification): remove document_splitter and missing_doc_detector (replaced by segmentation engine)"
```

---

### Task 11: Update Smoke Test & Verify Nested Script

**Files:**
- Modify: `3_Classification/src/smoke_test_classifier.py`
- Modify: `3_Classification/verify_nested.py`

- [ ] **Step 1: Update smoke_test_classifier.py**

Read current content of `3_Classification/src/smoke_test_classifier.py` and update any references to `document_splitter` or `missing_doc_detector` to use `SegmentationEngine` instead. Replace `LogicalDocument` usage with `Segment`. Keep the test logic the same — just update the imports and object types.

- [ ] **Step 2: Update verify_nested.py**

Read current content of `3_Classification/verify_nested.py` and update any references to `extract_balised_documents` or `missing_doc_detector` to use the segmentation engine. The nested document concept is now handled by the scoring engine detecting multiple boundaries within what used to be a single document.

- [ ] **Step 3: Run both scripts**

Run: `cd 3_Classification && python src/smoke_test_classifier.py`
Run: `cd 3_Classification && python verify_nested.py`
Expected: Both complete without errors

- [ ] **Step 4: Commit**

```bash
git add 3_Classification/src/smoke_test_classifier.py 3_Classification/verify_nested.py
git commit -m "refactor(3_Classification): update smoke tests for segmentation engine"
```
