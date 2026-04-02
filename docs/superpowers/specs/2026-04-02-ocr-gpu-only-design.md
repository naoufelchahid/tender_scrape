# OCR GPU-Only Enforcement Design

**Date:** 2026-04-02  
**Scope:** `2_Ocr/document_processor.py`  
**Status:** Approved

## Problem

The OCR container is configured for GPU (CUDA image, `USE_GPU=True`) but processes all documents on CPU. Two root causes:

1. `_detect_gpu_availability()` returns `True/False` but the result is **never passed to Docling** — it is stored in `self.gpu_available` which is only used for a log message. Docling and RapidOCR initialize with default settings and fall back to CPU.
2. No hard enforcement: if GPU is absent, the service silently runs on CPU, consuming large amounts of system RAM.

## Goal

Force GPU-only operation: fail loudly at container startup if no CUDA GPU is detected, and pass an explicit `AcceleratorDevice.CUDA` to Docling so it cannot silently fall back to CPU.

## Design

### Change 1 — Replace `_detect_gpu_availability()` with `_assert_gpu_available()`

**Current behavior:** returns `False` if no GPU, caller stores result and ignores it.

**New behavior:**
- Call `torch.cuda.is_available()`
- If `True`: log device name and VRAM, return normally
- If `False`: raise `RuntimeError("No CUDA GPU detected. This service requires GPU.")` — crashes the process at startup
- Remove the `USE_GPU` config flag check (GPU is no longer optional)

The `RuntimeError` propagates through `OCRService.__init__()` which already catches it:
```python
except Exception as e:
    logger.critical(f"Failed to initialize DocumentProcessor: {e}")
    raise
```
Container exits with non-zero code. ECS/Docker restarts it.

### Change 2 — Explicit GPU device in Docling pipeline

**Current behavior:** `PdfPipelineOptions` is created with no accelerator configuration. Docling picks its own device.

**New behavior:** Add to `DocumentProcessor.__init__()`:
```python
from docling.datamodel.pipeline_options import AcceleratorOptions, AcceleratorDevice

pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)
```

This forces Docling (and RapidOCR internally) to use CUDA instead of auto-detecting and falling back to CPU.

### Cleanup

- Remove `self.gpu_available` field (unused after this change)
- Remove `device_info = "GPU" if self.gpu_available else "CPU"` log line
- Replace with: `logger.info("✅ DocumentProcessor initialized with Docling (OCR enabled, Device: CUDA)")`

## Files Changed

| File | Change |
|------|--------|
| `2_Ocr/document_processor.py` | Replace `_detect_gpu_availability()`, add `AcceleratorOptions`, remove dead code |

## Files Unchanged

`main.py`, `config.py`, `s3_utils.py`, `sqs_utils.py`, `logger.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`

## Outcome

- Container crashes at startup if no GPU → ECS restarts, no silent CPU fallback
- Docling explicitly targets CUDA → GPU VRAM used instead of system RAM
- Removes ~15 lines of dead CPU-fallback code
