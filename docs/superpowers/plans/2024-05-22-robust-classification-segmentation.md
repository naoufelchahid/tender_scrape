# Robust Multi-Pass Semantic Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a semantic segmentation engine that "un-mixes" tender documents by treating text as a continuous stream and identifying semantic boundaries based on anchor headers and closing markers.

**Architecture:** Transition from file-based classification to stream-based segmentation. Use regex anchors for detection, heuristic look-back for boundary resolution, and re-validate segments using existing classification logic.

**Tech Stack:** Python 3.11, Regex, Pydantic, boto3.

---

### Task 1: Anchor Configuration

**Files:**
- Create: `3_Classification/src/anchors.json`
- Modify: `3_Classification/src/config.py`

- [ ] **Step 1: Create `anchors.json` with initial robust patterns**

```json
{
  "specification": {
    "primary": ["^#*\\s*CAHIER\\s+DES\\s+PRESCRIPTIONS\\s+SP[EÉ]CIALES", "^#*\\s*C\\.?P\\.?S"],
    "secondary": ["^#*\\s*ARTICLE\\s+1\\s*:\\s*OBJET"],
    "closing": ["Fait\\s+à\\s+.*,\\s+le\\s+\\d+", "Lu\\s+et\\s+accepté", "Le\\s+Titulaire"]
  },
  "administrative": {
    "primary": ["^#*\\s*R[EÈ]GLEMENT\\s+DE\\s+(?:LA\\s+)?CONSULTATION", "^#*\\s*R\\.?C"],
    "secondary": ["^#*\\s*OBJET\\s+DU\\s+R[EÈ]GLEMENT"],
    "closing": ["Fait\\s+à\\s+.*,\\s+le\\s+\\d+", "Lu\\s+et\\s+accepté"]
  },
  "product": {
    "primary": ["^#*\\s*BORDEREAU\\s+DES\\s+PRIX", "^#*\\s*D[EÉ]TAIL\\s+ESTIMATIF", "^#*\\s*جدول\\s+الأثمان"],
    "secondary": ["^DESIGNATION\\s*\\|\\s*UNITE"],
    "closing": ["Arrêté\\s+le\\s+présent\\s+bordereau"]
  },
  "declaration": {
    "primary": ["^#*\\s*(MOD[EÈ]LE\\s+DE\\s+(?:LA\\s+)?)?D[EÈ]CLARATION\\s+SUR\\s+L['’]HONNEUR"],
    "secondary": ["Je\\s+soussigné"],
    "closing": ["Signature", "cachet", "Fait\\s+à"]
  }
}
```

- [ ] **Step 2: Update `3_Classification/src/config.py` to load anchors**

```python
import json
import os
from pathlib import Path

# Add to existing Config class
def load_anchors():
    anchor_path = Path(__file__).parent / "anchors.json"
    if anchor_path.exists():
        with open(anchor_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

ANCHORS = load_anchors()
```

- [ ] **Step 3: Verify loading**

Run: `python -c "from src.config import ANCHORS; print('Anchors loaded' if ANCHORS else 'Fail')"`
Expected: `Anchors loaded`

- [ ] **Step 4: Commit**

```bash
git add 3_Classification/src/anchors.json 3_Classification/src/config.py
git commit -m "feat: add anchor configuration for segmentation"
```

---

### Task 2: Segmentation Engine (Pass 1 & 2)

**Files:**
- Create: `3_Classification/src/segmentation_engine.py`
- Test: `3_Classification/tests/test_segmentation.py`

- [ ] **Step 1: Write failing test for anchor detection**

```python
import pytest
from src.segmentation_engine import SegmentationEngine

def test_anchor_detection():
    engine = SegmentationEngine()
    text = "Some intro\n# CAHIER DES PRESCRIPTIONS SPECIALES\nContent\nFait à Rabat, le 01/01/2024\n# BORDEREAU DES PRIX\nTable"
    anchors = engine.scan_anchors(text)
    assert len(anchors) == 2
    assert anchors[0]['type'] == 'specification'
    assert anchors[1]['type'] == 'product'
```

- [ ] **Step 2: Implement Pass 1 (Scanning) in `segmentation_engine.py`**

```python
import re
from src.config import ANCHORS

class SegmentationEngine:
    def scan_anchors(self, text: str):
        lines = text.split('\n')
        detected = []
        for i, line in enumerate(lines):
            for doc_type, patterns in ANCHORS.items():
                for p in patterns.get('primary', []):
                    if re.search(p, line, re.IGNORECASE):
                        detected.append({'type': doc_type, 'line_idx': i, 'strength': 'primary'})
                for p in patterns.get('secondary', []):
                    if re.search(p, line, re.IGNORECASE):
                        # Avoid duplicates if primary already matched
                        if not any(d['line_idx'] == i for d in detected):
                            detected.append({'type': doc_type, 'line_idx': i, 'strength': 'secondary'})
        return detected
```

- [ ] **Step 3: Run test to verify fail (missing file/method)**

Run: `pytest 3_Classification/tests/test_segmentation.py`
Expected: FAIL (or PASS if correctly implemented)

- [ ] **Step 4: Implement Pass 2 (Boundary Resolution)**

```python
    def resolve_boundaries(self, text: str, detected_anchors: list):
        lines = text.split('\n')
        boundaries = [0]
        for anchor in detected_anchors:
            start_search = max(0, anchor['line_idx'] - 50)
            split_point = anchor['line_idx']
            
            # Look back for closing markers
            closing_patterns = ANCHORS.get(anchor['type'], {}).get('closing', [])
            for i in range(anchor['line_idx'] - 1, start_search - 1, -1):
                if any(re.search(p, lines[i], re.IGNORECASE) for p in closing_patterns):
                    split_point = i + 1
                    break
            
            if split_point not in boundaries:
                boundaries.append(split_point)
        
        boundaries.append(len(lines))
        return sorted(list(set(boundaries)))
```

- [ ] **Step 5: Commit**

```bash
git add 3_Classification/src/segmentation_engine.py 3_Classification/tests/test_segmentation.py
git commit -m "feat: implement anchor scanning and boundary resolution"
```

---

### Task 3: Segment Extraction (Pass 3)

**Files:**
- Modify: `3_Classification/src/segmentation_engine.py`

- [ ] **Step 1: Write test for slicing segments**

```python
def test_segment_slicing():
    engine = SegmentationEngine()
    text = "Line 0\n# CPS\nLine 2\nFait à X\n# BDP\nLine 5"
    # Mock detected anchors
    anchors = [{'type': 'specification', 'line_idx': 1}, {'type': 'product', 'line_idx': 4}]
    segments = engine.segment_stream(text, anchors)
    assert len(segments) >= 2
    assert "CPS" in segments[0]['content']
    assert "BDP" in segments[1]['content']
```

- [ ] **Step 2: Implement `segment_stream`**

```python
    def segment_stream(self, text: str, anchors: list):
        boundaries = self.resolve_boundaries(text, anchors)
        lines = text.split('\n')
        segments = []
        
        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i+1]
            content = '\n'.join(lines[start:end]).strip()
            
            if len(content) < 500: # Minimum Mass check
                continue
                
            segments.append({
                'content': content,
                'start_line': start,
                'end_line': end,
                'initial_type': self._guess_type(anchors, start, end)
            })
        return segments

    def _guess_type(self, anchors, start, end):
        for a in anchors:
            if start <= a['line_idx'] < end:
                return a['type']
        return "unknown"
```

- [ ] **Step 3: Commit**

```bash
git add 3_Classification/src/segmentation_engine.py
git commit -m "feat: implement segment extraction logic"
```

---

### Task 4: Integration & Verification (Pass 4)

**Files:**
- Modify: `3_Classification/src/classifier.py`

- [ ] **Step 1: Modify `DocumentClassifier.classify` to support segments**

```python
from .segmentation_engine import SegmentationEngine

class DocumentClassifier:
    def __init__(self, ...):
        self.segmenter = SegmentationEngine()
        # ...

    def classify_stream(self, full_text: str):
        anchors = self.segmenter.scan_anchors(full_text)
        segments = self.segmenter.segment_stream(full_text, anchors)
        
        final_docs = []
        for seg in segments:
            # Run existing 3-step logic on the segment
            verification = self.classify("virtual_doc.md", seg['content'])
            doc_type = verification.doc_type if verification.doc_type != "unknown" else seg['initial_type']
            
            final_docs.append({
                'content': seg['content'],
                'doc_type': doc_type,
                'confidence': verification.confidence,
                'metadata': {
                    'start_line': seg['start_line'],
                    'method': 'segmentation'
                }
            })
        return final_docs
```

- [ ] **Step 2: Verify verification loop**

Run: `pytest 3_Classification/tests/test_segmentation.py` (add integration test case)
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add 3_Classification/src/classifier.py
git commit -m "feat: integrate segmentation engine into DocumentClassifier"
```

---

### Task 5: Main Loop Integration

**Files:**
- Modify: `3_Classification/main.py`

- [ ] **Step 1: Update SQS handler to use `classify_stream`**

```python
# In handle_message or process_tender
def process_tender(tender_ref, markdown_content):
    classifier = DocumentClassifier(...)
    # New flow: process full text as stream
    logical_docs = classifier.classify_stream(markdown_content)
    
    # Reconstruct final markdown with headers
    final_output = []
    for doc in logical_docs:
        header = f"# Segment: {doc['doc_type']}\n> Document Type: {doc['doc_type']}\n"
        final_output.append(header + doc['content'])
    
    return "\n---\n".join(final_output)
```

- [ ] **Step 2: Run smoke test**

Run: `python 3_Classification/src/smoke_test_classifier.py` (update if needed)
Expected: Successfully splits mixed sample text.

- [ ] **Step 3: Final Commit**

```bash
git add 3_Classification/main.py
git commit -m "feat: update main loop to use semantic segmentation"
```
