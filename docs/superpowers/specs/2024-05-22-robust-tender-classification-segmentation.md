# Design Spec: Robust Multi-Pass Semantic Segmentation for Tender Documents

## 1. Purpose
Public procurement tenders in Morocco often bundle multiple logical documents (Avis, CPS, RC, BDP) into a single physical PDF or spread them across generic filenames. This spec defines a **Semantic Segmentation Engine** that "un-mixes" these documents by treating the text as a continuous stream and identifying semantic boundaries.

## 2. Architecture: The Stream Processor
The classification logic transitions from a "File Classifier" to a "Stream Processor."

### Components
- **Stream Ingestor**: Concatenates all OCR-extracted markdown for a tender into a single logical buffer.
- **Anchor Scanner**: Identifies "Start Anchors" (Primary/Secondary) and "Exit Anchors" (Closing markers).
- **Boundary Resolver**: Heuristic-based logic to determine the exact cut-point between segments.
- **Segment Verifier**: Re-validates extracted blocks using existing pattern-matching and LLM fallback logic.
- **Config Manager**: Externalizes all regex patterns to allow for iterative tuning.

## 3. The 4-Pass Segmentation Logic

### Pass 1: Scanning & Anchor Detection
- Scan the entire markdown stream line-by-line.
- Match lines against **Primary Anchors** (e.g., "CAHIER DES PRESCRIPTIONS SPECIALES") and **Secondary Anchors** (e.g., "ARTICLE 1: OBJET").
- Store all matches with their line indices and confidence levels.

### Pass 2: Boundary Resolution (The "Look-Back" Logic)
For each detected **Start Anchor**:
1. Search backwards (up to 50 lines) for an **Exit Anchor** (e.g., "Fait à...", signature blocks).
2. If an Exit Anchor is found, the split point is established at the line *following* the Exit Anchor.
3. If no Exit Anchor is found, the split point is established at the line *immediately before* the Start Anchor.

### Pass 3: Segment Extraction
- Slice the stream into `VirtualDocument` objects based on the resolved boundaries.
- Assign a preliminary `doc_type` based on the Anchor that triggered the split.
- Ensure "Minimum Mass" (e.g., segments under 500 chars are discarded or merged to prevent fragmentation).

### Pass 4: Verification & Clustering
- Run each `VirtualDocument` through the existing **3-Step Classification** (Regex -> Content -> AI).
- If the verification type matches the Anchor type, mark as **High Confidence**.
- If they conflict, prioritize the Verification type (or use LLM to resolve).
- Merge consecutive segments of the same type into a single final document.

## 4. Configuration Schema (`anchors.json`)
The system will be driven by a JSON configuration to allow for rapid tuning after sampling:
```json
{
  "specification": {
    "primary": ["^#* CAHIER DES PRESCRIPTIONS", "^#* C\\.P\\.S"],
    "secondary": ["^#* ARTICLE 1\\s*:\\s*OBJET"],
    "closing": ["Lu et accepté", "Le Titulaire"]
  },
  "product": {
    "primary": ["^#* BORDEREAU DES PRIX", "^#* DETAIL ESTIMATIF"],
    "secondary": ["^DESIGNATION\\s*|\\s*UNITE"],
    "closing": ["Arrêté le présent bordereau"]
  }
}
```

## 5. Metadata Traceability
Each extracted segment will include:
- `original_source_file`: The filename from S3.
- `segment_range`: `[start_line, end_line]`.
- `segmentation_method`: `anchor_split` or `file_split`.
- `confidence_score`: Based on pass verification.

## 6. Error Handling & Safety
- **Contested Boundaries**: If anchors overlap, trigger a targeted LLM call: "Where does the CPS end and the BDP begin in this text?".
- **Orphan Content**: Any text not assigned to a segment is captured as a "Miscellaneous" document to avoid data loss.
- **Minimum Volume**: Prevent accidental splits on page headers/footers by requiring a gap of at least X pages between anchor points.

## 7. Success Criteria
- [ ] Correctly identifies a BDP starting in the middle of a CPS file.
- [ ] Correctly identifies an Avis embedded at the start of an Administrative file.
- [ ] Logic remains unchanged when adding new regex patterns to `anchors.json`.
