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

    def get_signals(self, text: str) -> Dict[str, List[Dict]]:
        """Expose signal extraction for debugging/testing."""
        lines = text.split("\n")
        return self._extract_signals(lines)
