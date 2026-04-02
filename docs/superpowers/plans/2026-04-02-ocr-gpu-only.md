# OCR GPU-Only Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force the OCR container to use CUDA GPU exclusively — fail-fast at startup if no GPU is detected, and pass an explicit CUDA device to Docling so it cannot silently fall back to CPU.

**Architecture:** Replace the decorative `_detect_gpu_availability()` function with `_assert_gpu_available()` that raises `RuntimeError` on no GPU. Pass `AcceleratorOptions(device=AcceleratorDevice.CUDA)` to Docling's `PdfPipelineOptions` so GPU is explicitly required at the ML framework level too. Remove the now-unused `USE_GPU`/`GPU_MEMORY_FRACTION` config fields.

**Tech Stack:** Python 3.11, PyTorch (torch.cuda), Docling 2.x (`AcceleratorOptions`, `AcceleratorDevice`), pytest, unittest.mock

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `2_Ocr/document_processor.py` | Modify | Replace GPU detection with fail-fast assertion; add explicit CUDA AcceleratorOptions; remove dead code |
| `2_Ocr/config.py` | Modify | Remove `USE_GPU` and `GPU_MEMORY_FRACTION` fields (GPU is no longer optional) |
| `2_Ocr/tests/__init__.py` | Create | Makes tests/ a package |
| `2_Ocr/tests/test_document_processor.py` | Create | Tests for GPU assertion behavior |

---

### Task 1: Create test scaffolding and write failing tests

**Files:**
- Create: `2_Ocr/tests/__init__.py`
- Create: `2_Ocr/tests/test_document_processor.py`

- [ ] **Step 1: Create the tests package**

```bash
mkdir -p /home/naoufel/projects/tender_scrape/2_Ocr/tests
touch /home/naoufel/projects/tender_scrape/2_Ocr/tests/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `2_Ocr/tests/test_document_processor.py`:

```python
"""
Tests for GPU assertion logic in document_processor.py.
All tests mock torch.cuda to avoid requiring real GPU hardware in CI.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestAssertGpuAvailable:
    """Tests for _assert_gpu_available() fail-fast behavior."""

    def test_raises_if_no_cuda(self):
        """Should raise RuntimeError when torch.cuda.is_available() returns False."""
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False

            from document_processor import _assert_gpu_available
            with pytest.raises(RuntimeError, match="No CUDA GPU detected"):
                _assert_gpu_available()

    def test_passes_if_cuda_available(self):
        """Should return without error when GPU is detected."""
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_name.return_value = "Tesla T4"
            mock_props = MagicMock()
            mock_props.total_memory = 16 * 1024**3  # 16 GB
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.version.cuda = "12.1"

            from document_processor import _assert_gpu_available
            _assert_gpu_available()  # must not raise

    def test_logs_device_info_on_success(self, caplog):
        """Should log GPU name and VRAM when GPU is detected."""
        import logging
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_name.return_value = "Tesla T4"
            mock_props = MagicMock()
            mock_props.total_memory = 16 * 1024**3
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.version.cuda = "12.1"

            with caplog.at_level(logging.INFO, logger="document_processor"):
                from document_processor import _assert_gpu_available
                _assert_gpu_available()

            assert "Tesla T4" in caplog.text
```

- [ ] **Step 3: Run tests to verify they fail (function doesn't exist yet)**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
pip install pytest -q
pytest tests/test_document_processor.py -v 2>&1 | head -40
```

Expected: `ImportError` or `AttributeError` — `_assert_gpu_available` does not exist yet.

- [ ] **Step 4: Commit the failing tests**

```bash
cd /home/naoufel/projects/tender_scrape
git add 2_Ocr/tests/
git commit -m "test(2_Ocr): add failing tests for GPU-only assertion"
```

---

### Task 2: Implement `_assert_gpu_available()` and explicit CUDA device

**Files:**
- Modify: `2_Ocr/document_processor.py`

- [ ] **Step 1: Replace `_detect_gpu_availability()` with `_assert_gpu_available()`**

In `2_Ocr/document_processor.py`, replace lines 1–53 (imports + `_detect_gpu_availability`) with:

```python
"""
Unified Document Processor using Docling.
Replaces legacy disparate processors for PDF, DOCX, XLSX, and Images.
"""
import os
import re
import yaml
import subprocess
import shutil
from pathlib import Path

import torch
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableStructureOptions,
    AcceleratorOptions,
    AcceleratorDevice,
)
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

from logger import logger
from config import Config


def _assert_gpu_available() -> None:
    """
    Assert that a CUDA GPU is available. Raises RuntimeError at startup if not.
    This service requires GPU — there is no CPU fallback.
    """
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA GPU detected. This service requires GPU. "
            "Ensure the container is started with --gpus all or equivalent."
        )

    device_name = torch.cuda.get_device_name(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    logger.info("=" * 80)
    logger.info(f"🚀 GPU DETECTED: {device_name}")
    logger.info(f"📊 VRAM: {total_memory:.2f} GB")
    logger.info(f"🔧 CUDA Version: {torch.version.cuda}")
    logger.info("=" * 80)
```

- [ ] **Step 2: Update `DocumentProcessor.__init__()` to use `_assert_gpu_available()` and explicit CUDA device**

Replace the `__init__` method (lines 63–87 in the original):

```python
    def __init__(self):
        """Initialize Docling converter with OCR and Table options."""
        # Fail fast if no GPU — this service does not support CPU fallback
        _assert_gpu_available()

        # Configure Pipeline Options for OCR and Tables
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True

        # Explicitly target CUDA — Docling must not fall back to CPU
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA
        )

        # Configure Table Options
        table_options = TableStructureOptions()
        pipeline_options.table_structure_options = table_options

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend
                )
            }
        )

        logger.info("✅ DocumentProcessor initialized with Docling (OCR enabled, Device: CUDA)")
```

- [ ] **Step 3: Run the tests — they should now pass**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
pytest tests/test_document_processor.py -v
```

Expected output:
```
PASSED tests/test_document_processor.py::TestAssertGpuAvailable::test_raises_if_no_cuda
PASSED tests/test_document_processor.py::TestAssertGpuAvailable::test_passes_if_cuda_available
PASSED tests/test_document_processor.py::TestAssertGpuAvailable::test_logs_device_info_on_success
3 passed
```

- [ ] **Step 4: Commit the implementation**

```bash
cd /home/naoufel/projects/tender_scrape
git add 2_Ocr/document_processor.py
git commit -m "feat(2_Ocr): enforce GPU-only — fail-fast + explicit CUDA AcceleratorOptions

- Replace _detect_gpu_availability() with _assert_gpu_available() that raises
  RuntimeError if torch.cuda.is_available() is False
- Pass AcceleratorOptions(device=AcceleratorDevice.CUDA) to PdfPipelineOptions
  so Docling cannot silently fall back to CPU
- Remove self.gpu_available flag (unused after this change)"
```

---

### Task 3: Remove dead GPU config fields from `config.py`

**Files:**
- Modify: `2_Ocr/config.py`

- [ ] **Step 1: Remove `USE_GPU` and `GPU_MEMORY_FRACTION` from `Config`**

In `2_Ocr/config.py`, delete these two lines (around line 44–45):

```python
    # GPU Configuration
    USE_GPU: bool = os.getenv('USE_GPU', 'true').lower() == 'true'
    GPU_MEMORY_FRACTION: float = float(os.getenv('GPU_MEMORY_FRACTION', '0.8'))
```

Also remove their `print_config` entries (around lines 87–88):

```python
        print(f"  USE_GPU: {cls.USE_GPU}")
        print(f"  GPU_MEMORY_FRACTION: {cls.GPU_MEMORY_FRACTION}")
```

- [ ] **Step 2: Verify no remaining references to `Config.USE_GPU` or `Config.GPU_MEMORY_FRACTION`**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
grep -r "USE_GPU\|GPU_MEMORY_FRACTION" . --include="*.py"
```

Expected: no output (zero matches).

- [ ] **Step 3: Run all tests to confirm nothing broke**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
pytest tests/test_document_processor.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 2_Ocr/config.py
git commit -m "chore(2_Ocr): remove USE_GPU and GPU_MEMORY_FRACTION config fields

GPU is now required, not optional — these flags are no longer meaningful."
```

---

### Task 4: Rebuild container and verify fail-fast behavior

**Files:** None (validation only)

- [ ] **Step 1: Rebuild the Docker image**

```bash
cd /home/naoufel/projects/tender_scrape/2_Ocr
docker build -t tender-scrape-ocr:gpu-only .
```

Expected: build succeeds.

- [ ] **Step 2: Verify fail-fast behavior — run WITHOUT `--gpus` flag**

```bash
docker run --rm --env-file .env tender-scrape-ocr:gpu-only 2>&1 | head -20
```

Expected output contains:
```
CRITICAL - Failed to initialize DocumentProcessor: No CUDA GPU detected. ...
```
And the container exits with a non-zero exit code:
```bash
echo "Exit code: $?"
# Exit code: 1
```

- [ ] **Step 3: Commit verification note**

```bash
cd /home/naoufel/projects/tender_scrape
git commit --allow-empty -m "chore(2_Ocr): verified GPU-only fail-fast behavior in container"
```
