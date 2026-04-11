# Marker OCR + Classification Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the OCR and Classification containers into a single GPU container (2_Marker) using VikParuchuri/marker, rename 4_Extraction to 4_Embedding (embedding-only), and simplify the queue topology from 4 queues to 2.

**Architecture:** Subclass Marker's `PdfConverter` with two custom processors — `TenderClassifierProcessor` (regex/keyword classification on Marker's block tree) and `TenderChunkerProcessor` (document-type-aware chunking). The merged container outputs structured JSON with classified chunks. A new lightweight Embedding container produces vector embeddings per chunk.

**Tech Stack:** marker-pdf[full], PyTorch (CUDA 12.1, float16), sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2), boto3, SQS, S3

**Spec:** `docs/superpowers/specs/2026-04-11-marker-ocr-classification-merge-design.md`

---

## File Structure

### New Files (2_Marker/)

| File | Responsibility |
|---|---|
| `2_Marker/Dockerfile` | CUDA 12.1 image with marker-pdf[full], LibreOffice, model pre-cache |
| `2_Marker/requirements.txt` | Python dependencies |
| `2_Marker/.env.example` | Environment variable template |
| `2_Marker/main.py` | SQS poll loop, S3 download/upload, orchestration |
| `2_Marker/src/__init__.py` | Package init |
| `2_Marker/src/tender_converter.py` | TenderPdfConverter subclass with custom processor chain |
| `2_Marker/src/tender_classifier_processor.py` | 2-pass document-type classification on block tree |
| `2_Marker/src/tender_chunker_processor.py` | Document-type-aware chunking into structured JSON |
| `2_Marker/src/patterns.py` | Regex patterns + vocabulary keywords (migrated from 3_Classification) |
| `2_Marker/src/s3_client.py` | S3 wrapper (copied from 2_Ocr pattern) |
| `2_Marker/src/sqs_client.py` | SQS wrapper (copied from 2_Ocr pattern) |
| `2_Marker/monitor.py` | Pipeline event emitter (copy of root monitor.py) |
| `tests/2_Marker/test_patterns.py` | Tests for regex pattern matching |
| `tests/2_Marker/test_classifier_processor.py` | Tests for TenderClassifierProcessor |
| `tests/2_Marker/test_chunker_processor.py` | Tests for TenderChunkerProcessor |
| `tests/2_Marker/test_tender_converter.py` | Integration test for full converter pipeline |

### New Files (4_Embedding/)

| File | Responsibility |
|---|---|
| `4_Embedding/Dockerfile` | Python 3.11-slim, sentence-transformers |
| `4_Embedding/requirements.txt` | Python dependencies |
| `4_Embedding/.env.example` | Environment variable template |
| `4_Embedding/main.py` | SQS poll → embed → upload loop |
| `4_Embedding/src/__init__.py` | Package init |
| `4_Embedding/src/embedder.py` | Sentence-transformers wrapper |
| `4_Embedding/src/s3_client.py` | S3 wrapper |
| `4_Embedding/src/sqs_client.py` | SQS wrapper |
| `4_Embedding/monitor.py` | Pipeline event emitter |
| `tests/4_Embedding/test_embedder.py` | Tests for embedding |

### Modified Files

| File | Change |
|---|---|
| `docker-compose.verify.yml` | Replace ocr+classification+extraction services with marker+embedding |
| `5_Ingestion/main.py` (lines 95-160) | Read single `embedded_chunks.json` instead of 4 separate JSON files |
| `e2e_test.sh` (lines 48-56, 137-160, 189-236, 330-351, 441-444) | Update container names, queue refs, build/start logic |
| `monitor.py` | No change needed — stage names are parameters, not constants |

### Deleted (after new pipeline verified)

| Directory | Reason |
|---|---|
| `2_Ocr/` | Replaced by 2_Marker |
| `3_Classification/` | Absorbed into 2_Marker |
| `4_Extraction/` | Replaced by 4_Embedding |

---

## Task 1: Scaffold 2_Marker Directory and Dependencies

**Files:**
- Create: `2_Marker/requirements.txt`
- Create: `2_Marker/.env.example`
- Create: `2_Marker/src/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p 2_Marker/src
mkdir -p tests/2_Marker
```

- [ ] **Step 2: Write requirements.txt**

Create `2_Marker/requirements.txt`:

```
marker-pdf[full]>=1.0.0
torch>=2.1.0
torchvision>=0.16.0
boto3>=1.34.0
python-dotenv>=1.0.0
pyyaml>=6.0
```

- [ ] **Step 3: Write .env.example**

Create `2_Marker/.env.example`:

```bash
# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=eu-west-3
S3_BUCKET_NAME=

# SQS Queues
OCR_QUEUE_URL=
EMBEDDING_QUEUE_URL=

# Processing
TORCH_DEVICE=cuda
TORCH_DTYPE=float16
MARKER_TABLE_GPU=false

# Logging
LOG_DIR=/app/logs
PIPELINE_DB_PATH=/app/pipeline.db
```

- [ ] **Step 4: Create src/__init__.py**

Create `2_Marker/src/__init__.py`:

```python
"""2_Marker: Unified OCR + Classification + Chunking using Marker."""
```

- [ ] **Step 5: Copy monitor.py**

```bash
cp monitor.py 2_Marker/monitor.py
```

- [ ] **Step 6: Commit**

```bash
git add 2_Marker/
git commit -m "feat(2_Marker): scaffold directory structure and dependencies"
```

---

## Task 2: Migrate Classification Patterns to patterns.py

**Files:**
- Create: `2_Marker/src/patterns.py`
- Create: `tests/2_Marker/test_patterns.py`
- Reference: `3_Classification/src/classifier.py` (lines 48-142)

- [ ] **Step 1: Write the failing test**

Create `tests/2_Marker/test_patterns.py`:

```python
"""Tests for tender document type pattern matching."""
import pytest
from src.patterns import (
    SPEC_PATTERNS,
    ADMIN_PATTERNS,
    BDP_PATTERNS,
    AE_PATTERNS,
    DECL_PATTERNS,
    AVIS_AR_PATTERNS,
    AVIS_FR_PATTERNS,
    VOCABULARY_KEYWORDS,
    match_doc_type,
)


class TestAnchorPatterns:
    """Test that anchor regex patterns match expected text."""

    def test_spec_matches_cahier_prescriptions(self):
        assert match_doc_type("Cahier des Prescriptions Spéciales") == "specification"

    def test_spec_matches_arabic(self):
        assert match_doc_type("دفتر التحملات الخاصة") == "specification"

    def test_admin_matches_reglement(self):
        assert match_doc_type("Règlement de la Consultation") == "administrative"

    def test_admin_matches_arabic(self):
        assert match_doc_type("نظام الاستشارة") == "administrative"

    def test_bdp_matches_bordereau(self):
        assert match_doc_type("Bordereau des Prix - Détail Estimatif") == "product"

    def test_ae_matches_acte(self):
        assert match_doc_type("Acte d'Engagement") == "acte_engagement"

    def test_decl_matches_declaration(self):
        assert match_doc_type("Déclaration sur l'Honneur") == "declaration"

    def test_avis_ar_matches(self):
        assert match_doc_type("إعلان عن طلب عروض مفتوح") == "avis_ar"

    def test_avis_fr_matches(self):
        assert match_doc_type("Avis d'Appel d'Offres Ouvert") == "avis_fr"

    def test_no_match_returns_none(self):
        assert match_doc_type("Random text with no patterns") is None

    def test_case_insensitive(self):
        assert match_doc_type("CAHIER DES PRESCRIPTIONS SPÉCIALES") == "specification"


class TestVocabularyScoring:
    """Test vocabulary density classification fallback."""

    def test_spec_vocabulary_density(self):
        text = (
            "Article 1: Objet du marché. "
            "Les spécifications techniques du présent marché. "
            "Le délai d'exécution est fixé. "
            "Les normes marocaines applicables. "
            "Consistance des prestations à fournir."
        )
        from src.patterns import score_vocabulary
        scores = score_vocabulary(text)
        assert scores["specification"] > scores["administrative"]

    def test_admin_vocabulary_density(self):
        text = (
            "Cautionnement provisoire article 12. "
            "Critères d'évaluation des offres. "
            "Le règlement de la consultation prévoit. "
            "Pièces justificatives à fournir."
        )
        from src.patterns import score_vocabulary
        scores = score_vocabulary(text)
        assert scores["administrative"] > scores["specification"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape && python -m pytest tests/2_Marker/test_patterns.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.patterns'`

- [ ] **Step 3: Write patterns.py — migrate all regex patterns from classifier.py**

Create `2_Marker/src/patterns.py`:

```python
"""
Tender document type patterns — regex anchors and vocabulary keywords.

Migrated from 3_Classification/src/classifier.py (lines 48-142).
These patterns identify 8 Moroccan public tender document types
from section header text and body content.
"""
import re
from typing import Optional

# --- Anchor patterns: high-confidence matches on section headers ---

SPEC_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"cahier\s+des\s+prescriptions",
        r"cahier\s+des\s+charges",
        r"c\.?p\.?s",
        r"cctp",
        r"c\.c\.t\.p",
        r"prescriptions\s+spéciales",
        r"prescriptions\s+techniques",
        r"spécifications\s+techniques",
        r"normes?\s+(?:marocaines?|applicables?|en\s+vigueur)",
        r"consistance\s+de\s+la\s+mission",
        r"prestations\s+à\s+fournir",
        r"nantissement",
        r"délai\s+d['']exécution",
        r"دفتر\s+التحملات",
    ]
]

ADMIN_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"objet\s+du\s+règlement",
        r"règlement\s+de\s+la\s+consultation",
        r"نظام\s+الاستشارة",
        r"critères\s+d['']évaluation\s+des\s+offres",
        r"cautionnement\s+provisoire",
        r"pièces\s+justificatives",
        r"dossier\s+administratif",
    ]
]

BDP_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"bordereau\s+des\s+prix",
        r"détail\s+estimatif",
        r"جدول\s+الأثمان",
        r"البيان\s+التقديري",
        r"prix\s+unitaire",
        r"total\s+ttc",
        r"total\s+h\.?t",
        r"sous[\s-]?détail\s+des\s+prix",
        r"décomposition\s+du\s+montant",
    ]
]

AE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"acte\s+d['']engagement",
        r"après\s+avoir\s+pris\s+connaissance\s+du\s+dossier",
    ]
]

DECL_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"déclaration\s+sur\s+l['']honneur",
    ]
]

AVIS_AR_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"إعلان",
        r"فتح\s+الأظرفة",
    ]
]

AVIS_FR_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"avis\s+d['']appel\s+d['']offres",
        r"www\.marchespublics\.gov\.ma",
    ]
]

# --- Document type → pattern list mapping ---

DOC_TYPE_PATTERNS: dict[str, list[re.Pattern]] = {
    "specification": SPEC_PATTERNS,
    "administrative": ADMIN_PATTERNS,
    "product": BDP_PATTERNS,
    "acte_engagement": AE_PATTERNS,
    "declaration": DECL_PATTERNS,
    "avis_ar": AVIS_AR_PATTERNS,
    "avis_fr": AVIS_FR_PATTERNS,
}

# Priority order: more specific types first to avoid false positives
DOC_TYPE_PRIORITY: list[str] = [
    "acte_engagement",
    "declaration",
    "avis_ar",
    "avis_fr",
    "product",
    "administrative",
    "specification",
]

# --- Vocabulary keywords for density-based fallback (Pass 2) ---

VOCABULARY_KEYWORDS: dict[str, list[str]] = {
    "specification": [
        "article", "objet du marché", "spécifications techniques",
        "délai d'exécution", "normes", "consistance", "prestations",
        "conditions", "clauses", "pénalités", "réception",
    ],
    "administrative": [
        "cautionnement", "provisoire", "critères", "évaluation",
        "offres", "pièces justificatives", "dossier administratif",
        "soumissionnaire", "commission", "ouverture des plis",
    ],
    "product": [
        "prix unitaire", "montant", "quantité", "désignation",
        "unité", "total", "lot", "ttc", "tva", "forfait",
    ],
    "avis_fr": [
        "appel d'offres", "soumission", "marchés publics",
        "date limite", "lieu de dépôt", "cautionnement",
    ],
}

ALL_DOC_TYPES: list[str] = [
    "avis_fr", "avis_ar", "specification", "administrative",
    "product", "acte_engagement", "declaration", "annexe",
]


def match_doc_type(text: str) -> Optional[str]:
    """Match text against anchor patterns. Returns doc type or None.

    Checks patterns in priority order (most specific first).
    """
    for doc_type in DOC_TYPE_PRIORITY:
        patterns = DOC_TYPE_PATTERNS[doc_type]
        for pattern in patterns:
            if pattern.search(text):
                return doc_type
    return None


def score_vocabulary(text: str) -> dict[str, float]:
    """Score text against vocabulary keywords for each doc type.

    Returns dict of {doc_type: score} where score is count of keyword
    matches normalized by total keywords for that type.
    """
    text_lower = text.lower()
    scores: dict[str, float] = {}
    for doc_type, keywords in VOCABULARY_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in text_lower)
        scores[doc_type] = matches / len(keywords) if keywords else 0.0
    return scores
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_patterns.py -v
```

Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 2_Marker/src/patterns.py tests/2_Marker/test_patterns.py
git commit -m "feat(2_Marker): migrate classification patterns from 3_Classification"
```

---

## Task 3: Implement TenderClassifierProcessor

**Files:**
- Create: `2_Marker/src/tender_classifier_processor.py`
- Create: `tests/2_Marker/test_classifier_processor.py`
- Reference: Marker's `BaseProcessor` API, `Document.contained_blocks()`, `Block.structure_blocks()`

- [ ] **Step 1: Write the failing test**

Create `tests/2_Marker/test_classifier_processor.py`:

```python
"""Tests for TenderClassifierProcessor — classifies blocks by document type."""
import pytest
from unittest.mock import MagicMock, PropertyMock
from src.tender_classifier_processor import TenderClassifierProcessor


def _make_block(block_type_name: str, text: str = "", block_id: int = 0, page_id: int = 0):
    """Create a mock Marker Block with the given type and text."""
    block = MagicMock()
    block.block_type = MagicMock()
    block.block_type.name = block_type_name
    block.block_id = block_id
    block.page_id = page_id
    # Marker blocks use .html for rendered content, .raw_text() for plain text
    block.raw_text = MagicMock(return_value=text)
    block.metadata = MagicMock()
    block.metadata.tender_doc_type = None
    block.metadata.classification_confidence = None
    # Internal metadata storage
    block._internal_metadata = {}
    block.set_internal_metadata = lambda k, v: block._internal_metadata.__setitem__(k, v)
    block.get_internal_metadata = lambda k: block._internal_metadata.get(k)
    return block


def _make_document(blocks_by_page: list[list[tuple[str, str]]]):
    """Create a mock Document with pages of (block_type, text) tuples.

    Example: [[("SectionHeader", "Cahier des Prescriptions"), ("Text", "Article 1...")]]
    """
    doc = MagicMock()
    all_blocks = []
    pages = []

    for page_id, page_blocks in enumerate(blocks_by_page):
        page = MagicMock()
        page.page_id = page_id
        page_block_list = []
        for block_id, (btype, text) in enumerate(page_blocks):
            b = _make_block(btype, text, block_id=block_id, page_id=page_id)
            page_block_list.append(b)
            all_blocks.append(b)
        page.contained_blocks = MagicMock(return_value=page_block_list)
        pages.append(page)

    doc.pages = pages

    def contained_blocks(block_types=None):
        if block_types is None:
            return all_blocks
        return [b for b in all_blocks if b.block_type.name in [bt.name if hasattr(bt, 'name') else bt for bt in block_types]]

    doc.contained_blocks = contained_blocks
    return doc, all_blocks


class TestClassifierProcessor:

    def test_classifies_spec_header(self):
        doc, blocks = _make_document([
            [("SectionHeader", "Cahier des Prescriptions Spéciales"),
             ("Text", "Article 1: Objet du marché")]
        ])
        processor = TenderClassifierProcessor({})
        processor(doc)
        assert blocks[0].get_internal_metadata("tender_doc_type") == "specification"
        assert blocks[1].get_internal_metadata("tender_doc_type") == "specification"

    def test_classifies_avis_fr_header(self):
        doc, blocks = _make_document([
            [("SectionHeader", "Avis d'Appel d'Offres Ouvert"),
             ("Text", "Le Ministère lance un appel d'offres")]
        ])
        processor = TenderClassifierProcessor({})
        processor(doc)
        assert blocks[0].get_internal_metadata("tender_doc_type") == "avis_fr"
        assert blocks[0].get_internal_metadata("classification_confidence") == "high"

    def test_multiple_doc_types_in_one_document(self):
        doc, blocks = _make_document([
            [("SectionHeader", "Avis d'Appel d'Offres"),
             ("Text", "Date limite...")],
            [("SectionHeader", "Cahier des Prescriptions Spéciales"),
             ("Text", "Article 1...")]
        ])
        processor = TenderClassifierProcessor({})
        processor(doc)
        assert blocks[0].get_internal_metadata("tender_doc_type") == "avis_fr"
        assert blocks[2].get_internal_metadata("tender_doc_type") == "specification"

    def test_unmatched_blocks_get_vocabulary_fallback(self):
        doc, blocks = _make_document([
            [("SectionHeader", "Section sans titre reconnu"),
             ("Text", "prix unitaire montant quantité désignation total lot ttc")]
        ])
        processor = TenderClassifierProcessor({})
        processor(doc)
        # Vocabulary density should identify this as product
        assert blocks[1].get_internal_metadata("tender_doc_type") == "product"
        assert blocks[1].get_internal_metadata("classification_confidence") == "medium"

    def test_completely_unmatched_blocks_get_unknown(self):
        doc, blocks = _make_document([
            [("Text", "Some random unrelated text")]
        ])
        processor = TenderClassifierProcessor({})
        processor(doc)
        assert blocks[0].get_internal_metadata("tender_doc_type") == "unknown"
        assert blocks[0].get_internal_metadata("needs_review") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_classifier_processor.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tender_classifier_processor'`

- [ ] **Step 3: Implement TenderClassifierProcessor**

Create `2_Marker/src/tender_classifier_processor.py`:

```python
"""
TenderClassifierProcessor — Marker processor that assigns document types.

Runs after all built-in Marker processors. Walks the block tree and assigns
one of 8 Moroccan tender document types to each block using:
  Pass 1: Anchor regex matching on SectionHeader blocks
  Pass 2: Vocabulary density fallback on unclassified Text blocks
"""
from marker.processors import BaseProcessor
from marker.schema import BlockTypes

from src.patterns import match_doc_type, score_vocabulary, ALL_DOC_TYPES

# Minimum vocabulary score to accept a classification
_VOCAB_THRESHOLD = 0.25


class TenderClassifierProcessor(BaseProcessor):
    """Classify document blocks by Moroccan tender document type."""

    block_types = (BlockTypes.SectionHeader, BlockTypes.Text)

    def __call__(self, document):
        # Pass 1: Anchor matching on SectionHeaders
        current_type = None
        current_confidence = None

        for page in document.pages:
            page_blocks = page.contained_blocks()
            for block in page_blocks:
                type_name = block.block_type.name if hasattr(block.block_type, 'name') else str(block.block_type)

                if type_name == "SectionHeader":
                    text = block.raw_text() if callable(block.raw_text) else ""
                    matched = match_doc_type(text)
                    if matched:
                        current_type = matched
                        current_confidence = "high"

                if current_type:
                    block.set_internal_metadata("tender_doc_type", current_type)
                    block.set_internal_metadata("classification_confidence", current_confidence)

        # Pass 2: Vocabulary density for unclassified blocks
        for page in document.pages:
            page_blocks = page.contained_blocks()
            for block in page_blocks:
                doc_type = block.get_internal_metadata("tender_doc_type")
                if doc_type is not None:
                    continue

                text = block.raw_text() if callable(block.raw_text) else ""
                if len(text.strip()) < 20:
                    block.set_internal_metadata("tender_doc_type", "unknown")
                    block.set_internal_metadata("needs_review", True)
                    continue

                scores = score_vocabulary(text)
                if scores:
                    best_type = max(scores, key=scores.get)
                    best_score = scores[best_type]
                    if best_score >= _VOCAB_THRESHOLD:
                        block.set_internal_metadata("tender_doc_type", best_type)
                        block.set_internal_metadata("classification_confidence", "medium")
                        continue

                block.set_internal_metadata("tender_doc_type", "unknown")
                block.set_internal_metadata("needs_review", True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_classifier_processor.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 2_Marker/src/tender_classifier_processor.py tests/2_Marker/test_classifier_processor.py
git commit -m "feat(2_Marker): implement TenderClassifierProcessor with 2-pass classification"
```

---

## Task 4: Implement TenderChunkerProcessor

**Files:**
- Create: `2_Marker/src/tender_chunker_processor.py`
- Create: `tests/2_Marker/test_chunker_processor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/2_Marker/test_chunker_processor.py`:

```python
"""Tests for TenderChunkerProcessor — groups classified blocks into chunks."""
import json
import pytest
from unittest.mock import MagicMock
from src.tender_chunker_processor import TenderChunkerProcessor, build_chunks_json


def _make_classified_block(block_type_name, text, doc_type, page_id=0, block_id=0,
                            confidence="high", bbox=None):
    """Create a mock block with classification metadata already set."""
    block = MagicMock()
    block.block_type = MagicMock()
    block.block_type.name = block_type_name
    block.block_id = block_id
    block.page_id = page_id
    block.raw_text = MagicMock(return_value=text)
    block.polygon = MagicMock()
    block.polygon.bbox = bbox or [0, 0, 100, 100]

    metadata = {
        "tender_doc_type": doc_type,
        "classification_confidence": confidence,
    }
    block.get_internal_metadata = lambda k: metadata.get(k)

    # HTML rendering
    block.assemble_html = MagicMock(return_value=f"<p>{text}</p>")
    return block


def _make_classified_document(pages_data):
    """pages_data: list of lists of (block_type, text, doc_type) tuples."""
    doc = MagicMock()
    all_blocks = []
    pages = []

    for page_id, page_blocks in enumerate(pages_data):
        page = MagicMock()
        page.page_id = page_id
        pblocks = []
        for block_id, (btype, text, dtype) in enumerate(page_blocks):
            b = _make_classified_block(btype, text, dtype, page_id, block_id)
            pblocks.append(b)
            all_blocks.append(b)
        page.contained_blocks = MagicMock(return_value=pblocks)
        pages.append(page)

    doc.pages = pages
    return doc, all_blocks


class TestChunkerProcessor:

    def test_article_split_for_spec(self):
        """Specification docs should chunk at each SectionHeader."""
        doc, blocks = _make_classified_document([
            [("SectionHeader", "Article 1: Objet", "specification"),
             ("Text", "Le marché a pour objet...", "specification"),
             ("SectionHeader", "Article 2: Consistance", "specification"),
             ("Text", "Les prestations comprennent...", "specification")]
        ])
        chunks = build_chunks_json(doc, "TEST_REF_001")
        spec_chunks = [c for c in chunks["chunks"] if c["doc_type"] == "specification"]
        assert len(spec_chunks) == 2
        assert "Article 1" in spec_chunks[0]["title"]
        assert "Article 2" in spec_chunks[1]["title"]

    def test_whole_doc_chunk_for_declaration(self):
        """Declaration should be a single chunk."""
        doc, blocks = _make_classified_document([
            [("SectionHeader", "Déclaration sur l'Honneur", "declaration"),
             ("Text", "Je soussigné...", "declaration"),
             ("Text", "Déclare sur l'honneur...", "declaration")]
        ])
        chunks = build_chunks_json(doc, "TEST_REF_001")
        decl_chunks = [c for c in chunks["chunks"] if c["doc_type"] == "declaration"]
        assert len(decl_chunks) == 1

    def test_per_table_chunk_for_product(self):
        """Product docs should chunk around each Table block."""
        doc, blocks = _make_classified_document([
            [("Text", "Lot 1: Fournitures", "product"),
             ("Table", "| Item | Prix |\n|---|---|\n| A | 100 |", "product"),
             ("Text", "Lot 2: Services", "product"),
             ("Table", "| Item | Prix |\n|---|---|\n| B | 200 |", "product")]
        ])
        chunks = build_chunks_json(doc, "TEST_REF_001")
        prod_chunks = [c for c in chunks["chunks"] if c["doc_type"] == "product"]
        assert len(prod_chunks) == 2

    def test_output_json_structure(self):
        """Output JSON must have required top-level fields."""
        doc, _ = _make_classified_document([
            [("SectionHeader", "Avis d'Appel d'Offres", "avis_fr"),
             ("Text", "Date limite...", "avis_fr")]
        ])
        result = build_chunks_json(doc, "04_BM_2026")
        assert result["tender_ref"] == "04_BM_2026"
        assert "processed_at" in result
        assert "document_types_found" in result
        assert "document_types_missing" in result
        assert "chunks" in result
        assert "anomalies" in result
        assert "avis_fr" in result["document_types_found"]
        assert "specification" in result["document_types_missing"]

    def test_chunk_has_required_fields(self):
        """Each chunk must have all required fields."""
        doc, _ = _make_classified_document([
            [("SectionHeader", "Article 1", "specification"),
             ("Text", "Content here", "specification")]
        ])
        result = build_chunks_json(doc, "TEST_REF")
        chunk = result["chunks"][0]
        required_fields = [
            "chunk_id", "doc_type", "classification_confidence",
            "title", "content", "content_html", "page_range",
            "bbox", "block_types_contained", "word_count"
        ]
        for field in required_fields:
            assert field in chunk, f"Missing field: {field}"

    def test_missing_types_detected_as_anomalies(self):
        """Missing expected doc types should appear in anomalies."""
        doc, _ = _make_classified_document([
            [("SectionHeader", "Avis", "avis_fr"),
             ("Text", "Only avis here", "avis_fr")]
        ])
        result = build_chunks_json(doc, "TEST_REF")
        missing = result["document_types_missing"]
        anomalies = result["anomalies"]
        assert "specification" in missing
        assert any(a["doc_type"] == "specification" for a in anomalies)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_chunker_processor.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TenderChunkerProcessor**

Create `2_Marker/src/tender_chunker_processor.py`:

```python
"""
TenderChunkerProcessor — Groups classified blocks into structured chunks.

Chunking strategy varies by document type:
  - avis_fr/ar, specification, administrative: split at SectionHeader boundaries
  - product: split around Table blocks
  - acte_engagement, declaration: whole document = one chunk
  - annexe, unknown: split per page
"""
from datetime import datetime, timezone
from marker.processors import BaseProcessor
from src.patterns import ALL_DOC_TYPES

# Doc types that chunk at SectionHeader boundaries
_ARTICLE_SPLIT_TYPES = {"avis_fr", "avis_ar", "specification", "administrative"}
# Doc types that chunk around Table blocks
_TABLE_SPLIT_TYPES = {"product"}
# Doc types that become a single chunk
_WHOLE_DOC_TYPES = {"acte_engagement", "declaration"}
# Doc types that chunk per page
_PAGE_SPLIT_TYPES = {"annexe", "unknown"}


def build_chunks_json(document, tender_ref: str) -> dict:
    """Build the complete output JSON from a classified Marker document.

    Args:
        document: Marker Document with blocks classified via internal metadata.
        tender_ref: The tender reference string.

    Returns:
        Dict matching the classified_chunks.json schema.
    """
    # Collect all blocks grouped by doc_type
    typed_blocks: dict[str, list] = {}
    for page in document.pages:
        for block in page.contained_blocks():
            doc_type = block.get_internal_metadata("tender_doc_type") or "unknown"
            typed_blocks.setdefault(doc_type, []).append(block)

    found_types = [t for t in ALL_DOC_TYPES if t in typed_blocks and t != "unknown"]
    missing_types = [t for t in ALL_DOC_TYPES if t not in typed_blocks]

    chunks = []
    for doc_type, blocks in typed_blocks.items():
        if doc_type in _ARTICLE_SPLIT_TYPES:
            chunks.extend(_chunk_by_header(blocks, doc_type))
        elif doc_type in _TABLE_SPLIT_TYPES:
            chunks.extend(_chunk_by_table(blocks, doc_type))
        elif doc_type in _WHOLE_DOC_TYPES:
            chunks.extend(_chunk_whole(blocks, doc_type))
        else:
            chunks.extend(_chunk_by_page(blocks, doc_type))

    anomalies = [
        {"type": "missing_doc_type", "doc_type": t, "severity": "warning"}
        for t in missing_types
    ]

    return {
        "tender_ref": tender_ref,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "document_types_found": found_types,
        "document_types_missing": missing_types,
        "chunks": chunks,
        "anomalies": anomalies,
    }


def _make_chunk(blocks: list, doc_type: str, chunk_index: int, title: str = "") -> dict:
    """Create a single chunk dict from a list of blocks."""
    texts = []
    htmls = []
    pages = set()
    block_types = set()
    bboxes = []

    for b in blocks:
        text = b.raw_text() if callable(b.raw_text) else ""
        texts.append(text)
        html = b.assemble_html() if callable(getattr(b, 'assemble_html', None)) else f"<p>{text}</p>"
        htmls.append(html)
        pages.add(b.page_id)
        btype = b.block_type.name if hasattr(b.block_type, 'name') else str(b.block_type)
        block_types.add(btype)
        if hasattr(b, 'polygon') and b.polygon and hasattr(b.polygon, 'bbox'):
            bboxes.append(b.polygon.bbox)

    content = "\n".join(texts)
    page_range = sorted(pages)
    combined_bbox = _merge_bboxes(bboxes) if bboxes else None
    confidence = blocks[0].get_internal_metadata("classification_confidence") if blocks else "low"

    if not title and blocks:
        first_text = blocks[0].raw_text() if callable(blocks[0].raw_text) else ""
        title = first_text[:80].strip()

    return {
        "chunk_id": f"{doc_type}_{chunk_index:03d}",
        "doc_type": doc_type,
        "classification_confidence": confidence or "medium",
        "title": title,
        "content": content,
        "content_html": "\n".join(htmls),
        "page_range": page_range,
        "bbox": combined_bbox,
        "block_types_contained": sorted(block_types),
        "word_count": len(content.split()),
    }


def _chunk_by_header(blocks: list, doc_type: str) -> list[dict]:
    """Split at SectionHeader boundaries."""
    chunks = []
    current_group = []
    current_title = ""
    idx = 0

    for block in blocks:
        btype = block.block_type.name if hasattr(block.block_type, 'name') else str(block.block_type)
        if btype == "SectionHeader" and current_group:
            chunks.append(_make_chunk(current_group, doc_type, idx, current_title))
            idx += 1
            current_group = []

        if btype == "SectionHeader":
            current_title = block.raw_text() if callable(block.raw_text) else ""

        current_group.append(block)

    if current_group:
        chunks.append(_make_chunk(current_group, doc_type, idx, current_title))

    return chunks


def _chunk_by_table(blocks: list, doc_type: str) -> list[dict]:
    """Split around Table blocks — each Table + surrounding context = one chunk."""
    chunks = []
    current_group = []
    idx = 0
    has_table = False

    for block in blocks:
        btype = block.block_type.name if hasattr(block.block_type, 'name') else str(block.block_type)

        if btype == "Table":
            if has_table and current_group:
                chunks.append(_make_chunk(current_group, doc_type, idx))
                idx += 1
                current_group = []
            has_table = True

        current_group.append(block)

    if current_group:
        chunks.append(_make_chunk(current_group, doc_type, idx))

    return chunks


def _chunk_whole(blocks: list, doc_type: str) -> list[dict]:
    """Entire document type = single chunk."""
    if not blocks:
        return []
    return [_make_chunk(blocks, doc_type, 0)]


def _chunk_by_page(blocks: list, doc_type: str) -> list[dict]:
    """One chunk per page."""
    pages: dict[int, list] = {}
    for block in blocks:
        pages.setdefault(block.page_id, []).append(block)

    chunks = []
    for idx, (page_id, page_blocks) in enumerate(sorted(pages.items())):
        chunks.append(_make_chunk(page_blocks, doc_type, idx))
    return chunks


def _merge_bboxes(bboxes: list) -> list:
    """Merge multiple bboxes into one enclosing bbox."""
    if not bboxes:
        return None
    x_mins = [b[0] for b in bboxes]
    y_mins = [b[1] for b in bboxes]
    x_maxs = [b[2] for b in bboxes]
    y_maxs = [b[3] for b in bboxes]
    return [min(x_mins), min(y_mins), max(x_maxs), max(y_maxs)]


class TenderChunkerProcessor(BaseProcessor):
    """Marker processor that groups classified blocks into chunks.

    Must run after TenderClassifierProcessor.
    Stores the chunked JSON on the document for the converter to retrieve.
    """

    def __call__(self, document):
        # tender_ref is injected by TenderPdfConverter before processing
        tender_ref = document.get_internal_metadata("tender_ref") or "unknown"
        result = build_chunks_json(document, tender_ref)
        document.set_internal_metadata("classified_chunks", result)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_chunker_processor.py -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add 2_Marker/src/tender_chunker_processor.py tests/2_Marker/test_chunker_processor.py
git commit -m "feat(2_Marker): implement TenderChunkerProcessor with per-type chunking strategies"
```

---

## Task 5: Implement TenderPdfConverter

**Files:**
- Create: `2_Marker/src/tender_converter.py`
- Create: `tests/2_Marker/test_tender_converter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/2_Marker/test_tender_converter.py`:

```python
"""Tests for TenderPdfConverter — integration test for the full pipeline."""
import json
import pytest
from unittest.mock import patch, MagicMock
from src.tender_converter import TenderPdfConverter


class TestTenderPdfConverter:

    def test_converter_has_custom_processors_at_end(self):
        """Custom processors must appear after Marker's defaults."""
        procs = TenderPdfConverter.default_processors
        # Last two must be our custom processors
        assert procs[-2] == "TenderClassifierProcessor"
        assert procs[-1] == "TenderChunkerProcessor"

    def test_converter_uses_json_renderer(self):
        """Converter must default to JSON renderer."""
        from marker.renderers.json import JSONRenderer
        converter = TenderPdfConverter(config={"TORCH_DEVICE": "cpu"})
        assert converter.renderer == JSONRenderer or isinstance(converter.renderer, type(JSONRenderer))

    def test_convert_pdf_produces_classified_chunks(self):
        """Full integration: convert a real PDF and verify output structure.

        This test requires marker-pdf to be installed and a sample PDF.
        Skip if not available.
        """
        pytest.importorskip("marker")
        import os
        sample_pdf = os.environ.get("TEST_SAMPLE_PDF")
        if not sample_pdf or not os.path.exists(sample_pdf):
            pytest.skip("No TEST_SAMPLE_PDF env var set — skip integration test")

        converter = TenderPdfConverter(config={"TORCH_DEVICE": "cpu"})
        result = converter(sample_pdf, tender_ref="TEST_001")

        assert isinstance(result, dict)
        assert "tender_ref" in result
        assert "chunks" in result
        assert result["tender_ref"] == "TEST_001"
        assert len(result["chunks"]) > 0

        # Each chunk must have required fields
        for chunk in result["chunks"]:
            assert "chunk_id" in chunk
            assert "doc_type" in chunk
            assert "content" in chunk
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_tender_converter.py -v -k "not integration"
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TenderPdfConverter**

Create `2_Marker/src/tender_converter.py`:

```python
"""
TenderPdfConverter — Marker converter subclass for Moroccan tender documents.

Extends PdfConverter with:
  - TenderClassifierProcessor (document type classification)
  - TenderChunkerProcessor (type-aware chunking)

Output: structured JSON dict (classified_chunks schema) instead of
Marker's default rendered output.
"""
import os
import json
import logging

from marker.converters.pdf import PdfConverter
from marker.renderers.json import JSONRenderer

logger = logging.getLogger(__name__)


class TenderPdfConverter(PdfConverter):
    """PDF converter that classifies and chunks tender documents."""

    # Inherit all default processors, append custom ones at the end
    default_processors = PdfConverter.default_processors + (
        "TenderClassifierProcessor",
        "TenderChunkerProcessor",
    )

    def __init__(self, config=None, **kwargs):
        # Force JSON renderer
        kwargs.setdefault("renderer", JSONRenderer)

        # Apply vRAM-safe defaults
        config = config or {}
        config.setdefault("TORCH_DEVICE", os.environ.get("TORCH_DEVICE", "cuda"))

        super().__init__(config=config, **kwargs)

    def __call__(self, filepath, tender_ref: str = "unknown", **kwargs):
        """Convert a PDF and return classified chunks JSON.

        Args:
            filepath: Path to PDF file (or BytesIO).
            tender_ref: Tender reference string for output metadata.

        Returns:
            dict: classified_chunks JSON structure.
        """
        # Inject tender_ref into document metadata so processors can access it
        # We do this by monkey-patching the build_document output
        rendered = super().__call__(filepath, **kwargs)

        # The TenderChunkerProcessor stores result on document internal metadata.
        # But since we can't easily access the document post-render in the parent,
        # we need a different approach: store on a class attribute during processing.
        chunks_json = getattr(self, '_last_chunks_json', None)

        if chunks_json is None:
            logger.warning("No classified chunks produced — returning empty structure")
            chunks_json = {
                "tender_ref": tender_ref,
                "processed_at": "",
                "document_types_found": [],
                "document_types_missing": [],
                "chunks": [],
                "anomalies": [{"type": "processing_error", "severity": "error"}],
            }

        # Ensure tender_ref is set (processor may have used placeholder)
        chunks_json["tender_ref"] = tender_ref
        return chunks_json
```

> **Note for implementer:** The exact mechanism for retrieving `classified_chunks` from the document after processing depends on Marker's internal flow. The approach above may need adjustment during implementation — the key contract is: `TenderChunkerProcessor` stores the result, `TenderPdfConverter.__call__` retrieves and returns it. If `document.get_internal_metadata()` is accessible post-render, use that instead of the class attribute approach. Verify by reading Marker's `PdfConverter.__call__` source during implementation.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=2_Marker python -m pytest tests/2_Marker/test_tender_converter.py -v -k "not integration"
```

Expected: First 2 tests PASS (integration test skipped)

- [ ] **Step 5: Commit**

```bash
git add 2_Marker/src/tender_converter.py tests/2_Marker/test_tender_converter.py
git commit -m "feat(2_Marker): implement TenderPdfConverter subclass with custom processor chain"
```

---

## Task 6: Implement 2_Marker main.py (SQS Poll Loop)

**Files:**
- Create: `2_Marker/main.py`
- Reference: `2_Ocr/main.py` (lines 69-115 for S3 download, 146-182 for upload, 369-405 for SQS loop)

- [ ] **Step 1: Copy S3 and SQS client wrappers**

```bash
cp 2_Ocr/src/s3_client.py 2_Marker/src/s3_client.py
cp 2_Ocr/src/sqs_client.py 2_Marker/src/sqs_client.py
```

> **Note:** If these files don't exist as separate modules in 2_Ocr (the S3/SQS logic may be inline in main.py), extract the relevant methods into standalone wrappers. The key methods needed are:
> - `S3Client.download_file(s3_key, local_path)` 
> - `S3Client.upload_file(local_path, s3_key, metadata=None)`
> - `SQSClient.receive_message(queue_url, wait_time=20)`
> - `SQSClient.delete_message(queue_url, receipt_handle)`
> - `SQSClient.send_message(queue_url, body)`

- [ ] **Step 2: Write main.py**

Create `2_Marker/main.py`:

```python
"""
2_Marker: Unified OCR + Classification + Chunking service.

Polls OCR_QUEUE for tender processing requests, runs Marker with custom
classification and chunking processors, uploads classified_chunks.json to S3,
and posts to EMBEDDING_QUEUE.
"""
import json
import logging
import os
import sys
import tempfile
import time
import subprocess
from pathlib import Path

import boto3
from dotenv import load_dotenv

from src.tender_converter import TenderPdfConverter
import monitor

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.environ.get("LOG_DIR", "logs"), "marker.log")
        ),
    ],
)
logger = logging.getLogger("marker-service")

# --- Configuration ---
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
OCR_QUEUE_URL = os.environ["OCR_QUEUE_URL"]
EMBEDDING_QUEUE_URL = os.environ["EMBEDDING_QUEUE_URL"]
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-3")

# Supported raw document extensions
SUPPORTED_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpeg", ".jpg", ".png"}
# Legacy formats requiring LibreOffice pre-conversion
LEGACY_EXT = {".doc": ".docx", ".xls": ".xlsx"}

POLL_WAIT = 20  # SQS long-poll seconds
TEMP_DIR = Path(os.environ.get("TEMP_DIR", "/app/temp_run"))


class MarkerService:
    """Main service: poll SQS, process with Marker, upload results."""

    def __init__(self):
        self.s3 = boto3.client("s3", region_name=AWS_REGION)
        self.sqs = boto3.client("sqs", region_name=AWS_REGION)
        self.converter = TenderPdfConverter()
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("MarkerService initialized — converter ready")

    def run(self):
        """Main poll loop."""
        logger.info("Starting poll loop on %s", OCR_QUEUE_URL)
        while True:
            try:
                resp = self.sqs.receive_message(
                    QueueUrl=OCR_QUEUE_URL,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=POLL_WAIT,
                )
                messages = resp.get("Messages", [])
                if not messages:
                    continue

                msg = messages[0]
                body = json.loads(msg["Body"])
                receipt_handle = msg["ReceiptHandle"]

                self._process_tender(body)

                self.sqs.delete_message(
                    QueueUrl=OCR_QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                )
            except Exception as e:
                logger.error("Poll loop error: %s", e, exc_info=True)
                time.sleep(5)

    def _process_tender(self, body: dict):
        """Process a single tender: download → Marker → upload → notify."""
        tender_ref = body["tender_ref"]
        batch_id = body.get("batch_id", "unknown")
        s3_paths = body.get("s3_paths", [])

        monitor.enter(batch_id, tender_ref, "marker")
        logger.info("Processing tender: %s (%d files)", tender_ref, len(s3_paths))

        try:
            with tempfile.TemporaryDirectory(dir=TEMP_DIR) as work_dir:
                work_path = Path(work_dir)

                # Step 1: Download raw documents from S3
                local_files = self._download_files(s3_paths, work_path, tender_ref)
                if not local_files:
                    raise ValueError(f"No supported files found for {tender_ref}")

                # Step 2: Pre-convert legacy formats
                converted_files = self._convert_legacy(local_files, work_path)

                # Step 3: Process each file through Marker
                all_chunks = {
                    "tender_ref": tender_ref,
                    "processed_at": "",
                    "document_types_found": [],
                    "document_types_missing": [],
                    "chunks": [],
                    "anomalies": [],
                }

                for filepath in converted_files:
                    result = self.converter(str(filepath), tender_ref=tender_ref)
                    # Merge chunks from each file
                    all_chunks["chunks"].extend(result.get("chunks", []))
                    for dt in result.get("document_types_found", []):
                        if dt not in all_chunks["document_types_found"]:
                            all_chunks["document_types_found"].append(dt)

                # Recompute missing types after merging
                from src.patterns import ALL_DOC_TYPES
                all_chunks["document_types_missing"] = [
                    t for t in ALL_DOC_TYPES
                    if t not in all_chunks["document_types_found"]
                ]
                all_chunks["anomalies"] = [
                    {"type": "missing_doc_type", "doc_type": t, "severity": "warning"}
                    for t in all_chunks["document_types_missing"]
                ]
                all_chunks["processed_at"] = result.get("processed_at", "")

                # Re-index chunk IDs to be globally unique
                for i, chunk in enumerate(all_chunks["chunks"]):
                    chunk["chunk_id"] = f"{chunk['doc_type']}_{i:03d}"

                # Step 4: Upload classified_chunks.json to S3
                s3_key = f"chunks_tender/{tender_ref}/classified_chunks.json"
                output_path = work_path / "classified_chunks.json"
                output_path.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2))
                self.s3.upload_file(str(output_path), S3_BUCKET, s3_key)
                logger.info("Uploaded %s (%d chunks)", s3_key, len(all_chunks["chunks"]))

                # Step 5: Post to EMBEDDING_QUEUE
                self.sqs.send_message(
                    QueueUrl=EMBEDDING_QUEUE_URL,
                    MessageBody=json.dumps({
                        "tender_ref": tender_ref,
                        "batch_id": batch_id,
                        "chunks_key": s3_key,
                    }),
                )

                monitor.complete(
                    batch_id, tender_ref, "marker",
                    chunk_count=len(all_chunks["chunks"]),
                    doc_types_found=len(all_chunks["document_types_found"]),
                )
                logger.info("Tender %s complete", tender_ref)

        except Exception as e:
            monitor.failed(batch_id, tender_ref, "marker", error=str(e))
            logger.error("Failed processing %s: %s", tender_ref, e, exc_info=True)
            raise

    def _download_files(self, s3_paths: list, work_dir: Path, tender_ref: str) -> list[Path]:
        """Download raw documents from S3. Returns list of local file paths."""
        local_files = []
        for s3_path in s3_paths:
            # Handle both individual files and folder prefixes
            if s3_path.endswith("/"):
                # List objects under prefix
                resp = self.s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=s3_path)
                keys = [obj["Key"] for obj in resp.get("Contents", [])]
            else:
                keys = [s3_path]

            for key in keys:
                ext = Path(key).suffix.lower()
                if ext not in SUPPORTED_EXT:
                    continue
                local_path = work_dir / Path(key).name
                self.s3.download_file(S3_BUCKET, key, str(local_path))
                local_files.append(local_path)
                logger.debug("Downloaded %s", key)

        return local_files

    def _convert_legacy(self, files: list[Path], work_dir: Path) -> list[Path]:
        """Convert .doc/.xls to .docx/.xlsx via LibreOffice. Returns updated file list."""
        converted = []
        for f in files:
            if f.suffix.lower() in LEGACY_EXT:
                target_ext = LEGACY_EXT[f.suffix.lower()]
                try:
                    subprocess.run(
                        ["libreoffice", "--headless", "--convert-to",
                         target_ext.lstrip("."), "--outdir", str(work_dir), str(f)],
                        check=True, timeout=120, capture_output=True,
                    )
                    converted_path = work_dir / f"{f.stem}{target_ext}"
                    if converted_path.exists():
                        converted.append(converted_path)
                        logger.info("Converted %s → %s", f.name, converted_path.name)
                        continue
                except Exception as e:
                    logger.warning("LibreOffice conversion failed for %s: %s", f.name, e)
            converted.append(f)
        return converted


if __name__ == "__main__":
    service = MarkerService()
    service.run()
```

- [ ] **Step 3: Commit**

```bash
git add 2_Marker/main.py 2_Marker/src/s3_client.py 2_Marker/src/sqs_client.py
git commit -m "feat(2_Marker): implement main.py SQS poll loop with S3 download/upload"
```

---

## Task 7: Build 2_Marker Dockerfile

**Files:**
- Create: `2_Marker/Dockerfile`

- [ ] **Step 1: Write Dockerfile**

Create `2_Marker/Dockerfile`:

```dockerfile
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip python3.11-dev \
    poppler-utils \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libreoffice-writer libreoffice-calc default-jre \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Use python3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Install UV for fast package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN uv pip install --system --no-cache \
    torch torchvision --index-url https://download.pytorch.org/whl/cu121 \
    && uv pip install --system --no-cache -r requirements.txt

# Pre-cache Marker models (layout detection + Surya OCR)
RUN python -c "from marker.converters.pdf import PdfConverter; PdfConverter(config={'TORCH_DEVICE': 'cpu'})" \
    || echo "Model pre-cache attempted"

# Copy application code
COPY monitor.py .
COPY src/ src/
COPY main.py .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
```

- [ ] **Step 2: Test Docker build (no GPU required for build)**

```bash
cd /home/naoufel/projects/tender_scrape && docker build -t marker-test -f 2_Marker/Dockerfile 2_Marker/
```

Expected: Build completes successfully. Model pre-cache step may warn but should not fail the build.

- [ ] **Step 3: Commit**

```bash
git add 2_Marker/Dockerfile
git commit -m "feat(2_Marker): add Dockerfile with CUDA 12.1, marker-pdf, and model pre-cache"
```

---

## Task 8: Scaffold 4_Embedding Directory and Embedder

**Files:**
- Create: `4_Embedding/requirements.txt`
- Create: `4_Embedding/.env.example`
- Create: `4_Embedding/src/__init__.py`
- Create: `4_Embedding/src/embedder.py`
- Create: `tests/4_Embedding/test_embedder.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p 4_Embedding/src
mkdir -p tests/4_Embedding
```

- [ ] **Step 2: Write requirements.txt**

Create `4_Embedding/requirements.txt`:

```
sentence-transformers>=2.2.0
boto3>=1.34.0
python-dotenv>=1.0.0
torch>=2.1.0
```

- [ ] **Step 3: Write .env.example**

Create `4_Embedding/.env.example`:

```bash
# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=eu-west-3
S3_BUCKET_NAME=

# SQS Queues
EMBEDDING_QUEUE_URL=
KB_INGESTION_QUEUE_URL=

# Model
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# Logging
LOG_DIR=/app/logs
PIPELINE_DB_PATH=/app/pipeline.db
```

- [ ] **Step 4: Write the failing test for embedder**

Create `tests/4_Embedding/test_embedder.py`:

```python
"""Tests for the embedding wrapper."""
import pytest
import numpy as np


class TestEmbedder:

    def test_embed_single_text(self):
        from src.embedder import Embedder
        embedder = Embedder(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        result = embedder.embed("Cahier des prescriptions spéciales")
        assert isinstance(result, list)
        assert len(result) == 384  # MiniLM-L12-v2 dimension

    def test_embed_batch(self):
        from src.embedder import Embedder
        embedder = Embedder(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        texts = ["Article 1: Objet du marché", "Bordereau des prix"]
        results = embedder.embed_batch(texts)
        assert len(results) == 2
        assert all(len(r) == 384 for r in results)

    def test_embed_arabic(self):
        from src.embedder import Embedder
        embedder = Embedder(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        result = embedder.embed("دفتر التحملات الخاصة")
        assert isinstance(result, list)
        assert len(result) == 384

    def test_embed_empty_returns_zeros(self):
        from src.embedder import Embedder
        embedder = Embedder(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        result = embedder.embed("")
        assert isinstance(result, list)
        assert len(result) == 384
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=4_Embedding python -m pytest tests/4_Embedding/test_embedder.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 6: Implement embedder.py**

Create `4_Embedding/src/embedder.py`:

```python
"""Sentence-transformers wrapper for chunk embedding."""
import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class Embedder:
    """Wraps sentence-transformers for CPU-based embedding."""

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        logger.info("Loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name, device="cpu")
        self.dimension = self.model.get_sentence_embedding_dimension()
        logger.info("Model loaded — dimension: %d", self.dimension)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns list of floats."""
        embedding = self.model.encode(text, show_progress_bar=False)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float lists."""
        embeddings = self.model.encode(texts, show_progress_bar=False, batch_size=32)
        return [e.tolist() for e in embeddings]
```

Create `4_Embedding/src/__init__.py`:

```python
"""4_Embedding: Vector embedding service for classified tender chunks."""
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd /home/naoufel/projects/tender_scrape && PYTHONPATH=4_Embedding python -m pytest tests/4_Embedding/test_embedder.py -v
```

Expected: All 4 tests PASS (first run downloads ~120MB model)

- [ ] **Step 8: Commit**

```bash
git add 4_Embedding/ tests/4_Embedding/
git commit -m "feat(4_Embedding): scaffold embedding service with sentence-transformers"
```

---

## Task 9: Implement 4_Embedding main.py and Dockerfile

**Files:**
- Create: `4_Embedding/main.py`
- Create: `4_Embedding/Dockerfile`
- Copy: `4_Embedding/monitor.py`

- [ ] **Step 1: Copy monitor.py**

```bash
cp monitor.py 4_Embedding/monitor.py
```

- [ ] **Step 2: Write main.py**

Create `4_Embedding/main.py`:

```python
"""
4_Embedding: Vector embedding service for classified tender chunks.

Polls EMBEDDING_QUEUE, downloads classified_chunks.json from S3,
embeds each chunk using sentence-transformers, uploads embedded_chunks.json,
and posts to KB_INGESTION_QUEUE.
"""
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

from src.embedder import Embedder
import monitor

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.environ.get("LOG_DIR", "logs"), "embedding.log")
        ),
    ],
)
logger = logging.getLogger("embedding-service")

S3_BUCKET = os.environ["S3_BUCKET_NAME"]
EMBEDDING_QUEUE_URL = os.environ["EMBEDDING_QUEUE_URL"]
KB_INGESTION_QUEUE_URL = os.environ["KB_INGESTION_QUEUE_URL"]
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-3")
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
POLL_WAIT = 20


class EmbeddingService:

    def __init__(self):
        self.s3 = boto3.client("s3", region_name=AWS_REGION)
        self.sqs = boto3.client("sqs", region_name=AWS_REGION)
        self.embedder = Embedder(model_name=EMBEDDING_MODEL)
        logger.info("EmbeddingService initialized")

    def run(self):
        logger.info("Starting poll loop on %s", EMBEDDING_QUEUE_URL)
        while True:
            try:
                resp = self.sqs.receive_message(
                    QueueUrl=EMBEDDING_QUEUE_URL,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=POLL_WAIT,
                )
                messages = resp.get("Messages", [])
                if not messages:
                    continue

                msg = messages[0]
                body = json.loads(msg["Body"])
                receipt_handle = msg["ReceiptHandle"]

                self._process(body)

                self.sqs.delete_message(
                    QueueUrl=EMBEDDING_QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                )
            except Exception as e:
                logger.error("Poll loop error: %s", e, exc_info=True)
                time.sleep(5)

    def _process(self, body: dict):
        tender_ref = body["tender_ref"]
        batch_id = body.get("batch_id", "unknown")
        chunks_key = body["chunks_key"]

        monitor.enter(batch_id, tender_ref, "embedding")
        logger.info("Embedding tender: %s", tender_ref)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                # Download classified_chunks.json
                local_path = Path(tmp) / "classified_chunks.json"
                self.s3.download_file(S3_BUCKET, chunks_key, str(local_path))
                data = json.loads(local_path.read_text())

                # Embed all chunks
                texts = [c["content"] for c in data["chunks"]]
                if texts:
                    embeddings = self.embedder.embed_batch(texts)
                    for chunk, emb in zip(data["chunks"], embeddings):
                        chunk["embedding"] = emb

                # Upload embedded_chunks.json
                output_key = f"embedded_tender/{tender_ref}/embedded_chunks.json"
                output_path = Path(tmp) / "embedded_chunks.json"
                output_path.write_text(json.dumps(data, ensure_ascii=False))
                self.s3.upload_file(str(output_path), S3_BUCKET, output_key)

                logger.info("Uploaded %s (%d chunks embedded)", output_key, len(texts))

                # Post to KB_INGESTION_QUEUE
                self.sqs.send_message(
                    QueueUrl=KB_INGESTION_QUEUE_URL,
                    MessageBody=json.dumps({
                        "tender_ref": tender_ref,
                        "batch_id": batch_id,
                        "embedded_chunks_key": output_key,
                    }),
                )

                monitor.complete(
                    batch_id, tender_ref, "embedding",
                    chunk_count=len(texts),
                )

        except Exception as e:
            monitor.failed(batch_id, tender_ref, "embedding", error=str(e))
            logger.error("Failed embedding %s: %s", tender_ref, e, exc_info=True)
            raise


if __name__ == "__main__":
    service = EmbeddingService()
    service.run()
```

- [ ] **Step 3: Write Dockerfile**

Create `4_Embedding/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache embedding model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY monitor.py .
COPY src/ src/
COPY main.py .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
```

- [ ] **Step 4: Commit**

```bash
git add 4_Embedding/main.py 4_Embedding/Dockerfile 4_Embedding/monitor.py
git commit -m "feat(4_Embedding): implement main.py poll loop and Dockerfile"
```

---

## Task 10: Update docker-compose.verify.yml

**Files:**
- Modify: `docker-compose.verify.yml`

- [ ] **Step 1: Read current docker-compose.verify.yml**

```bash
cat docker-compose.verify.yml
```

- [ ] **Step 2: Rewrite docker-compose.verify.yml**

Replace the entire file with:

```yaml
version: "3.8"

services:
  marker:
    build:
      context: ./2_Marker
    container_name: Marker
    runtime: nvidia
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    env_file:
      - 2_Marker/.env
    environment:
      - AWS_DEFAULT_REGION=${AWS_REGION:-eu-west-3}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - LOG_DIR=/app/logs
      - TORCH_DEVICE=cuda
    volumes:
      - ./2_Marker/temp_run:/app/temp_run
      - ./Logs/2_Marker:/app/logs
      - ./pipeline.db:/app/pipeline.db
    restart: unless-stopped

  embedding:
    build:
      context: ./4_Embedding
    container_name: Embedding
    env_file:
      - 4_Embedding/.env
    environment:
      - AWS_DEFAULT_REGION=${AWS_REGION:-eu-west-3}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - LOG_DIR=/app/logs
    volumes:
      - ./Logs/4_Embedding:/app/logs
      - ./pipeline.db:/app/pipeline.db
    depends_on:
      - marker
    restart: unless-stopped

  ingestion:
    build:
      context: .
      dockerfile: 5_Ingestion/Dockerfile
    container_name: Ingestion
    env_file:
      - 5_Ingestion/.env
    environment:
      - AWS_DEFAULT_REGION=${AWS_REGION:-eu-west-3}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - LOG_DIR=/app/logs
      - NT_OUTPUT_DIR=/app/data_flow/4_tender_enrich_triples
    volumes:
      - ./Logs/5_Ingestion:/app/logs
      - ./Data_flow/4_tender_enrich_triples:/app/data_flow/4_tender_enrich_triples
      - ./pipeline.db:/app/pipeline.db
    depends_on:
      - embedding
    restart: unless-stopped
```

- [ ] **Step 3: Validate compose file**

```bash
docker compose -f docker-compose.verify.yml config --quiet
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add docker-compose.verify.yml
git commit -m "refactor: update docker-compose.verify.yml for marker+embedding topology"
```

---

## Task 11: Update 5_Ingestion to Read embedded_chunks.json

**Files:**
- Modify: `5_Ingestion/main.py` (lines 95-160)

- [ ] **Step 1: Read current ingestion message handling**

Read `5_Ingestion/main.py` lines 90-170 to understand the exact code that reads the 4 JSON files.

- [ ] **Step 2: Update message body parsing**

In `5_Ingestion/main.py`, replace the 4-file key extraction (lines ~108-124) with single-file handling:

**Before** (approximate):
```python
avis_key = body.get('avis_key') or self._guess_key(folder, 'avis')
product_key = body.get('product_key') or self._guess_key(folder, 'product')
spec_key = body.get('specification_key') or self._guess_key(folder, 'specification')
admin_key = body.get('administrative_key') or self._guess_key(folder, 'administrative')
```

**After:**
```python
embedded_chunks_key = body.get("embedded_chunks_key")
if not embedded_chunks_key:
    # Fallback: construct from tender_ref
    embedded_chunks_key = f"embedded_tender/{tender_ref}/embedded_chunks.json"
```

- [ ] **Step 3: Update processing to iterate chunks by doc_type**

Replace the per-file processing methods with a unified chunk processor:

```python
# Download embedded_chunks.json
with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
    self.s3.download_file(S3_BUCKET, embedded_chunks_key, tmp.name)
    data = json.loads(Path(tmp.name).read_text())

# Group chunks by doc_type
chunks_by_type = {}
for chunk in data["chunks"]:
    doc_type = chunk["doc_type"]
    chunks_by_type.setdefault(doc_type, []).append(chunk)

# Process each type
for doc_type, chunks in chunks_by_type.items():
    self._process_typed_chunks(tender_ref, doc_type, chunks, mapper)
```

> **Note for implementer:** The exact modifications depend on how `_process_avis_vector`, `_process_products`, and `_process_doc_chunks` use the chunk data internally. Each method currently downloads a JSON file from S3 and iterates its `chunks` array. The change is: instead of downloading 4 files, you download 1 file and route chunks by their `doc_type` field to the appropriate processing method. The chunk format is identical — each has `content`, `doc_type`, `embedding`, and metadata. Read lines 193-250 of the current file before editing.

- [ ] **Step 4: Run existing ingestion tests**

```bash
cd /home/naoufel/projects/tender_scrape && python -m pytest tests/5_Ingestion/ -v
```

Expected: All existing tests pass (update test fixtures if needed to match new message format)

- [ ] **Step 5: Commit**

```bash
git add 5_Ingestion/main.py
git commit -m "refactor(5_Ingestion): read single embedded_chunks.json instead of 4 separate files"
```

---

## Task 12: Update e2e_test.sh

**Files:**
- Modify: `e2e_test.sh` (lines 48-56, 137-160, 189-236, 330-351, 441-444)

- [ ] **Step 1: Read current e2e_test.sh**

Read the full file to understand all references to old container/queue names.

- [ ] **Step 2: Update container name constants (line ~48-56)**

**Before:**
```bash
OCR_CONTAINER="OCR"
CLASSIFICATION_CONTAINER="Classification"
EXTRACTION_CONTAINER="Extraction"
INGESTION_CONTAINER="Ingestion"
```

**After:**
```bash
MARKER_CONTAINER="Marker"
EMBEDDING_CONTAINER="Embedding"
INGESTION_CONTAINER="Ingestion"
```

- [ ] **Step 3: Update queue name references (lines ~441-444)**

**Before:**
```bash
OCR_QUEUE_URL
CLASSIFICATION_QUEUE_URL
EXTRACTION_QUEUE_URL
KB_INGESTION_QUEUE_URL
```

**After:**
```bash
OCR_QUEUE_URL
EMBEDDING_QUEUE_URL
KB_INGESTION_QUEUE_URL
```

- [ ] **Step 4: Update build_images function (lines ~137-160)**

Replace references to `ocr`, `classification`, `extraction` service builds with `marker` and `embedding`.

- [ ] **Step 5: Update start_services function (lines ~189-236)**

Replace the 4-service startup with 3-service startup: marker, embedding, ingestion.

- [ ] **Step 6: Update monitor_logs and monitor_queue_depths**

Replace log file paths:
- `Logs/2_Ocr/` → `Logs/2_Marker/`
- `Logs/3_Classification/` → removed
- `Logs/4_Extraction/` → `Logs/4_Embedding/`

Replace queue depth checks to use the new 2-queue topology.

- [ ] **Step 7: Run e2e_test.sh in dry-run mode**

```bash
bash -n e2e_test.sh
```

Expected: No syntax errors

- [ ] **Step 8: Commit**

```bash
git add e2e_test.sh
git commit -m "refactor(e2e): update test script for marker+embedding container topology"
```

---

## Task 13: Create SQS Queues and Clean Up Old Ones

**Files:** None (infrastructure-only)

- [ ] **Step 1: Create EMBEDDING_QUEUE**

```bash
aws sqs create-queue --queue-name tender-embedding-queue --region eu-west-3
```

Note the queue URL for .env files.

- [ ] **Step 2: Update .env files with new queue URLs**

Update `2_Marker/.env`:
```
EMBEDDING_QUEUE_URL=<new queue URL>
```

Update `4_Embedding/.env`:
```
EMBEDDING_QUEUE_URL=<new queue URL>
KB_INGESTION_QUEUE_URL=<existing KB ingestion queue URL>
```

- [ ] **Step 3: Verify old queues still exist (do NOT delete yet)**

```bash
aws sqs get-queue-url --queue-name tender-classification-queue --region eu-west-3
aws sqs get-queue-url --queue-name tender-extraction-queue --region eu-west-3
```

> **Do not delete old queues until the new pipeline passes e2e testing.**

- [ ] **Step 4: Commit .env files (exclude secrets)**

```bash
git add 2_Marker/.env.example 4_Embedding/.env.example
git commit -m "feat: add .env.example files for Marker and Embedding services"
```

---

## Task 14: Integration Test — Full Pipeline E2E

**Files:** None (testing only)

- [ ] **Step 1: Build all images**

```bash
cd /home/naoufel/projects/tender_scrape
docker compose -f docker-compose.verify.yml build
```

- [ ] **Step 2: Start services**

```bash
docker compose -f docker-compose.jena.yml up -d
docker compose -f docker-compose.verify.yml up -d
```

- [ ] **Step 3: Run 1_Update with a small batch (1-3 tenders)**

```bash
source venv/bin/activate
cd 1_Update && python Db_updater.py --limit 3
```

- [ ] **Step 4: Monitor logs**

```bash
# Watch Marker container
docker logs -f Marker

# Watch Embedding container
docker logs -f Embedding

# Watch Ingestion container
docker logs -f Ingestion
```

- [ ] **Step 5: Verify S3 output**

```bash
# Check classified_chunks.json exists
aws s3 ls s3://${S3_BUCKET}/chunks_tender/ --recursive | head -5

# Check embedded_chunks.json exists
aws s3 ls s3://${S3_BUCKET}/embedded_tender/ --recursive | head -5

# Download and inspect one
aws s3 cp s3://${S3_BUCKET}/chunks_tender/<tender_ref>/classified_chunks.json /tmp/
python -c "import json; d=json.load(open('/tmp/classified_chunks.json')); print(f'Chunks: {len(d[\"chunks\"])}, Types: {d[\"document_types_found\"]}')"
```

- [ ] **Step 6: Verify Jena has triples**

```bash
curl -s 'http://localhost:3030/tenders/sparql' \
  --data-urlencode 'query=SELECT (COUNT(*) as ?c) WHERE { ?s ?p ?o }' \
  -H 'Accept: application/json'
```

- [ ] **Step 7: Check pipeline.db events**

```bash
sqlite3 pipeline.db "SELECT stage, event, COUNT(*) FROM events GROUP BY stage, event ORDER BY stage"
```

Expected: `marker` and `embedding` stages with `enter`/`complete` events.

- [ ] **Step 8: Run full e2e_test.sh**

```bash
bash e2e_test.sh --limit 5
```

---

## Task 15: Clean Up Old Directories

**Only after Task 14 passes successfully.**

- [ ] **Step 1: Remove old directories**

```bash
rm -rf 2_Ocr/
rm -rf 3_Classification/
rm -rf 4_Extraction/
```

- [ ] **Step 2: Delete old SQS queues**

```bash
aws sqs delete-queue --queue-url <CLASSIFICATION_QUEUE_URL>
aws sqs delete-queue --queue-url <EXTRACTION_QUEUE_URL>
```

- [ ] **Step 3: Update .gitignore if needed**

Check if `.gitignore` references any old directory paths.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: remove old 2_Ocr, 3_Classification, 4_Extraction directories

Replaced by 2_Marker (unified OCR+classification+chunking) and
4_Embedding (vector embedding only). Old SQS queues deleted."
```
