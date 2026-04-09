# Multi-Signal Scoring Segmentation Engine — Design Spec

**Date:** 2026-04-09
**Status:** Draft
**Replaces:** `2024-05-22-robust-tender-classification-segmentation.md` (regex-only anchor approach)

---

## Problem

The current classification pipeline uses a two-phase approach:

1. `document_splitter.py` splits markdown by `# File:` headers
2. `missing_doc_detector.py` scans for embedded documents via regex + balise insertion

This fails in three ways that compound across the variety of tender sources:

- **No headers**: Merged/scanned PDFs arrive as a continuous stream with no `# File:` markers — the splitter treats everything as one document
- **Unhelpful filenames**: Even when headers exist, filenames like `doc1.pdf` or `scan.pdf` give no classification signal
- **Classification confusion**: Overlapping vocabulary between document types (`specification` vs `administrative`, `acte_engagement` vs `declaration`), OCR-mangled headers, and unusual table formats cause misclassification

The variety is extreme — even tenders from the same institution have inconsistent formatting. At hundreds of tenders per day, the solution must be fast (minimize LLM calls) while handling this diversity.

---

## Solution

Replace both `document_splitter.py` and `missing_doc_detector.py` with a unified **Multi-Signal Scoring Engine** that runs in 4 passes:

```
Input markdown (full text stream)
        |
   Pass 1: Line-Level Signal Extraction
   |  (regex anchors, structural markers, vocab features -- all computed once)
   |
   Pass 2: Boundary Scoring
   |  (combine signals into per-line scores, threshold to find split points)
   |
   Pass 3: Segment Classification
   |  (existing 3-step classify on each segment, with signal features as hints)
   |
   Pass 4: Validation & Merge
   |  (reject fragments, merge adjacent same-type, sanity checks)
   |
Output: List[Segment] with type, confidence, content, line range
```

The key insight: regex anchors work great when present, but the system degrades gracefully when they're absent by relying on structural, vocabulary, and statistical signals instead.

---

## Pass 1: Signal Extraction

Pass 1 scans every line once and produces a **signal matrix** — each line gets a dict of scores from four independent extractors.

### Signal 1: Regex Anchors (weight: high)

Expanded pattern set stored in `segmentation_config.json`:

- **Opening anchors**: Primary headers per doc type
  - `specification`: `CAHIER DES PRESCRIPTIONS`, `C.P.S`, `CCTP`
  - `administrative`: `REGLEMENT DE CONSULTATION`, `R.C`
  - `product`: `BORDEREAU DES PRIX`, `DETAIL ESTIMATIF`, `جدول الأثمان`
  - `avis_fr`: `AVIS D'APPEL D'OFFRES`
  - `avis_ar`: `إعلان عن طلب عروض`
  - `acte_engagement`: `ACTE D'ENGAGEMENT`, `MODELE D'ACTE`
  - `declaration`: `DECLARATION SUR L'HONNEUR`
  - `annexe`: `ANNEXE`
- **Closing anchors**: Formal endings — `Fait a`, `Lu et accepte`, `Le Titulaire`, `Signature et cachet`
- **Section anchors**: Internal markers that confirm type without indicating boundaries — `ARTICLE 1 : OBJET` (confirms specification)

Each match emits:
```python
{"type": str, "role": "open"|"close"|"internal", "strength": float}
```

Strength: 1.0 for exact primary matches, 0.5-0.8 for secondary/fuzzy. OCR tolerance via character class equivalences (`E|E|E` treated as equivalent).

### Signal 2: Structural Markers (weight: medium)

Layout-level discontinuities that suggest boundaries regardless of content:

- **Page breaks**: `## Page N`, `---`, form-feed characters
- **Blank-line gaps**: 3+ consecutive empty lines
- **Header-level resets**: H1 appearing after body text
- **`# File:` headers**: Backward-compatible with current splitter
- **OCR page markers**: Already recognized by current system

Each emits: `{"boundary_signal": float}` — stronger for `# File:` headers, weaker for blank-line gaps.

### Signal 3: Vocabulary Shift (weight: medium)

Sliding window (default ~50 lines) detects when dominant vocabulary changes. No LLM — purely statistical:

- Maintain **keyword buckets** per doc type (reuse existing pattern lists from `classifier.py` Step 1)
- For each window position, count keyword hits per bucket
- When the dominant bucket changes between adjacent windows, emit a shift signal proportional to the magnitude of change

Example: a window of `prix unitaire, montant, designation` shifts to `delai d'execution, clauses techniques` = strong shift from `product` to `specification`.

### Signal 4: Document Fingerprint (weight: low-medium)

Lightweight statistical features per sliding window:

- **Arabic character ratio**: High = `avis_ar`, low = French documents
- **Table density**: Pipe characters, `<table_start>` markers = `product`
- **Number density**: Lots of numbers = `product` or `acte_engagement`
- **Line length variance**: Forms have short uniform lines, specs have long paragraphs
- **Signature keyword density**: `soussigne`, `cachet`, `signature` = form-type documents

These reinforce or dampen other signals but don't trigger boundaries alone.

---

## Pass 2: Boundary Scoring & Resolution

### Scoring Formula

For each line `i`:

```
score(i) = w_anchor * anchor_signal(i)
         + w_struct * structural_signal(i)
         + w_vocab  * vocab_shift_signal(i)
         + w_finger * fingerprint_shift(i)
```

Default weights: `w_anchor=0.5, w_struct=0.2, w_vocab=0.2, w_finger=0.1`

Weights are configurable in `segmentation_config.json`.

### Boundary Selection

1. **Threshold**: Lines with `score > 0.4` are candidates
2. **Peak picking**: If multiple candidates cluster within 10 lines, pick the highest score
3. **Minimum segment size**: Segments under 300 characters merge with neighbor

### Boundary Refinement

Once candidates are identified, refine the exact split point:

- **Opening anchor nearby** (within 5 lines): Snap boundary to just before it
- **Closing anchor nearby** (look back up to 50 lines from next opening): Snap to just after closing
- **Neither**: Split at strongest structural marker (page break > blank gap > header reset)

### Edge Cases

- **No boundaries found** (score never crosses threshold): Treat entire content as single document — pass to classifier as-is. Matches current behavior for clean single-document tenders.
- **First segment has no opening anchor**: Mark as `preamble` — often cover pages or TOC. Gets classified normally in Pass 3.
- **Adjacent identical types**: Flag for merge in Pass 4.

---

## Pass 3: Segment Classification

Each segment gets classified using the existing 3-step logic from `classifier.py` with two enhancements:

### Enhancement 1: Signal Hints as Prior

The dominant doc type from Pass 1 signals is passed as `hint_type` with a `hint_strength` (0-1) to the classifier. Decision logic:

- **hint_strength >= 0.8 AND Steps 1-2 agree**: Use result, skip LLM. Confidence = max(step_confidence, hint_strength).
- **hint_strength >= 0.8 AND Steps 1-2 disagree or return "unknown"**: Use hint type. Confidence = hint_strength * 0.8.
- **hint_strength < 0.8 AND Steps 1-2 return a type**: Use Steps 1-2 result. Confidence = step_confidence.
- **hint_strength < 0.8 AND Steps 1-2 return "unknown"**: Invoke LLM (Step 3) with hint as context in the prompt.
- **No hint (hint_strength = 0)**: Current behavior — Steps 1-2-3 in sequence.

### Enhancement 2: Segment-Aware Content Sampling

Instead of always sampling the first 5000 chars:

- If an opening anchor was detected, sample from that anchor forward
- If segment is short (<5000 chars), use full content
- For BDP segments, include enough to capture table structure

---

## Pass 4: Validation & Merge

Post-classification cleanup:

1. **Merge adjacent same-type**: If two consecutive segments share a type and the boundary score between them was below 0.6 (i.e., within 1.5x of the threshold), merge them
2. **Minimum mass check**: Segments under 500 chars (after merge) that aren't form-type documents (`declaration`, `acte_engagement`, `avis_*`) get absorbed into predecessor
3. **Conflict resolution**: If classifier result contradicts signal hint with high confidence on both sides, flag as `needs_review` in YAML metadata
4. **Completeness check**: Compare final segment types against `ALL_DOCUMENT_TYPES` to produce the YAML checklist

---

## Data Model

```python
@dataclass
class Segment:
    content: str
    doc_type: str           # classified type
    confidence: float       # 0-1
    start_line: int
    end_line: int
    method: str             # "anchor", "scoring", "classifier", "llm"
    needs_review: bool      # True if signals contradicted classifier
```

Replaces both `LogicalDocument` from splitter and balise-based extraction from `missing_doc_detector.py`.

---

## File Changes

| File | Action | Notes |
|------|--------|-------|
| `src/segmentation_engine.py` | Create | Pass 1-2-4 logic, signal extractors, scoring |
| `src/segmentation_config.json` | Create | Weights, thresholds, anchor patterns (all tunable) |
| `src/classifier.py` | Modify | Add `classify_segment(content, hint_type)` method |
| `main.py` | Modify | Replace splitter+missing_doc flow with segmentation pipeline |
| `src/document_splitter.py` | Remove | Replaced by segmentation engine |
| `src/missing_doc_detector.py` | Remove | Replaced by segmentation engine |
| `src/bdp_extractor.py` | Keep | Called as signal extractor in Pass 1 for table detection |
| `src/hierarchy_restructurer.py` | Keep | Runs after segmentation for header restructuring |
| `tests/test_segmentation.py` | Create | Unit tests per signal extractor and scoring logic |

---

## Integration

### main.py Flow

Current:
```
download -> split_by_headers -> classify_each -> detect_missing -> extract_balised -> restructure -> upload
```

New:
```
download -> segment(pass1->2->3->4) -> restructure -> upload
```

### No Interface Changes

- SQS message format: unchanged
- S3 paths and prefixes: unchanged
- YAML frontmatter structure: unchanged (adds optional `needs_review` field)
- S3 metadata format: unchanged
- Monitoring hooks (`mon_enter`, `mon_complete`, `mon_anomaly`): same call sites
- Output to `EXTRACTION_QUEUE`: same message format

### Backward Compatibility

- Clean `# File:` headers: Structural signal picks them up with high weight — behaves like current splitter
- Single-document tenders: No boundaries found = single segment, classified normally
- YAML checklist and S3 metadata: identical format

---

## Configuration: segmentation_config.json

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
    "opening_snap_lines": 5
  },
  "vocabulary": {
    "window_size": 50
  },
  "anchors": {
    "specification": {
      "open": ["CAHIER\\s+DES\\s+PRESCRIPTIONS\\s+SP[EE]CIALES", "C\\.?P\\.?S", "CCTP", "C\\.?C\\.?T\\.?P"],
      "close": ["Fait\\s+[aà]\\s+.*,\\s+le\\s+\\d+", "Lu\\s+et\\s+accept[eé]", "Le\\s+Titulaire"],
      "internal": ["ARTICLE\\s+\\d+\\s*:", "CHAPITRE\\s+\\d+"]
    },
    "administrative": {
      "open": ["R[EÈE]GLEMENT\\s+DE\\s+(?:LA\\s+)?CONSULTATION", "R\\.?C"],
      "close": ["Fait\\s+[aà]\\s+.*,\\s+le\\s+\\d+", "Lu\\s+et\\s+accept[eé]"],
      "internal": ["OBJET\\s+DU\\s+R[EÈE]GLEMENT"]
    },
    "product": {
      "open": ["BORDEREAU\\s+DES\\s+PRIX", "D[EÉE]TAIL\\s+ESTIMATIF", "جدول\\s+الأثمان"],
      "close": ["Arr[eê]t[eé]\\s+le\\s+pr[eé]sent\\s+bordereau"],
      "internal": ["DESIGNATION\\s*\\|\\s*UNITE"]
    },
    "avis_fr": {
      "open": ["AVIS\\s+D[''']APPEL\\s+D[''']OFFRES", "AVIS\\s+DE\\s+PUBLICIT[EÉ]"],
      "close": ["Fait\\s+[aà]", "www\\.marchespublics\\.gov\\.ma"],
      "internal": []
    },
    "avis_ar": {
      "open": ["إعلان\\s+عن\\s+طلب\\s+عروض"],
      "close": ["فتح\\s+الأظرفة"],
      "internal": []
    },
    "acte_engagement": {
      "open": ["(?:MOD[EÈ]LE\\s+(?:DE\\s+)?)?ACTE\\s+D[''']ENGAGEMENT"],
      "close": ["Signature", "cachet"],
      "internal": ["apr[eè]s\\s+avoir\\s+pris\\s+connaissance"]
    },
    "declaration": {
      "open": ["(?:MOD[EÈ]LE\\s+DE\\s+(?:LA\\s+)?)?D[EÉ]CLARATION\\s+SUR\\s+L[''']HONNEUR"],
      "close": ["Signature", "cachet", "Fait\\s+[aà]"],
      "internal": ["Je\\s+soussign[eé]"]
    },
    "annexe": {
      "open": ["ANNEXE\\s+[IVXLCDM\\d]"],
      "close": [],
      "internal": []
    }
  }
}
```

---

## Testing Strategy

- **Unit tests per signal extractor**: Feed known text patterns, assert correct signal emission
- **Unit tests for scoring**: Feed crafted signal matrices, assert correct boundary placement
- **Integration tests**: Feed real tender markdown samples, assert correct segment count and types
- **Regression tests**: Current test fixtures from `smoke_test_classifier.py` and `verify_nested.py` must still pass
- **Edge case tests**: Empty input, single-doc input, all-Arabic input, OCR-heavy noise
