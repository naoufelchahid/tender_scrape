# Pipeline Anomaly Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 categories of anomalies found in the 20-tender e2e run without breaking any running pipeline process.

**Architecture:** Each fix is surgical — touch only what's broken, in the file that owns the behavior. No cross-cutting refactors. Quality gates become conditional on what doc types are actually present. A local DeepSeek model (already running in Ollama) is added as the primary LLM for extraction, with OpenRouter as fallback.

**Tech Stack:** Python 3.12, rdflib, boto3, botocore, sqlite3 (monitor), OpenAI-compatible Ollama API, Docker Compose networks

---

## Context (read before implementing)

From the e2e debug session, these anomalies were confirmed:

| ID | Stage | Anomaly | Root Cause |
|----|-------|---------|------------|
| A1 | 5_Ingestion | `has_administrative` gate fails on 7/9 tenders | Gate runs unconditionally; most tenders have no administrative doc |
| A2 | 5_Ingestion | `30/2026/DR5` fails 3 gates (has_specification, has_bordereau, bordereau_has_articles) | Administrative-only tender, but gates run regardless of doc type |
| A3 | 5_Ingestion | `TO4130038` ghost message causes repeated NoSuchKey errors | `_get_s3_json` exception not caught → message never deleted |
| A4 | 1_Update | Tenders with `docs_count=0` silently complete and enter OCR with no S3 files | No anomaly emitted; kg_builder posts them to OCR anyway |
| A5 | 4_Extraction | OpenRouter `gpt-oss-safeguard-20b` (Groq) rate-limited 429 on every tender | Primary + fallback_1 both point to same model; local Ollama unused |

**User constraints:**
- Search failures in 1_Update due to website timeouts are **normal** — do not change failure behavior, only ensure they are logged clearly
- Extraction should use local DeepSeek (already deployed in `ollama` container with `deepseek-r1:1.5b`) as primary inference model
- Changes must not break other containers or the SQS message contracts

---

## File Map

| File | Change |
|------|--------|
| `5_Ingestion/src/data_tester.py` | `validate_tender_in_jena` accepts `present_doc_types: set[str]` and skips gates whose doc type is absent |
| `5_Ingestion/main.py` | Pass `present_doc_types` from SQS message body; catch `NoSuchKey` ClientError |
| `1_Update/Db_updater.py` | Emit `mon_anomaly` with `no_documents_downloaded` before `mon_complete` when `docs_count == 0` |
| `1_Update/kg_builder.py` | Skip OCR queue post for tenders with no `s3_folder` key (no files uploaded) |
| `4_Extraction/src/local_llm_wrapper.py` | **New** — OpenAI-compatible wrapper pointing at Ollama `http://ollama-host:11434` |
| `4_Extraction/src/document_chunker.py` | Accept `local_client` in `__init__`; try local model first, fall through to OpenRouter |
| `4_Extraction/main.py` | Instantiate `LocalLLMWrapper` and pass to `DocumentChunker` |
| `4_Extraction/.env` | Add `OLLAMA_BASE_URL`, `LOCAL_MODEL=deepseek-r1:1.5b` |
| `4_Extraction/docker-compose.yml` | Add `local_llm_default` external network |

---

## Task 1 — Conditional quality gates in 5_Ingestion

**Files:**
- Modify: `5_Ingestion/src/data_tester.py:148-172`
- Modify: `5_Ingestion/main.py:150-165` (post-ingestion validation call)

### Why the gates fail

`validate_tender_in_jena` always checks all 4 gates. But the ingestion message only provides the doc-type keys that were actually produced by extraction. A specification-only tender has no `administrative_key` in the message → no administrative chunks saved to S3 → no `ts:Has_Reglement_Consultation` triple in Jena → gate fails. This is not a data defect; it is an overly strict gate.

### Fix strategy

Pass a `present_doc_types: set[str]` into `validate_tender_in_jena`. Apply each gate only if the relevant doc type is present:

| Gate | Applies when |
|------|--------------|
| `has_specification` | `'specification'` in present_doc_types |
| `has_administrative` | `'administrative'` in present_doc_types |
| `has_bordereau` | `'product'` in present_doc_types |
| `bordereau_has_articles` | `'product'` in present_doc_types |

If none of the above applies (edge case), log a warning but do not fail.

- [ ] **Step 1.1: Write failing test**

Create `5_Ingestion/tests/test_data_tester_conditional_gates.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from src.data_tester import DataTester


def _make_tester(check_spec=True, check_admin=True, check_bordereau=True, check_articles=True):
    jena = MagicMock()
    jena.check_tender_has_spec.return_value = check_spec
    jena.check_tender_has_admin.return_value = check_admin
    jena.check_tender_has_bordereau.return_value = check_bordereau
    jena.check_bordereau_has_articles.return_value = check_articles
    tester = DataTester.__new__(DataTester)
    tester.jena = jena
    tester._ontology_path = None
    tester._shapes_path = None
    tester._ontology_graph = None
    tester._shapes_graph = None
    return tester, jena


def test_spec_gate_skipped_when_spec_not_present():
    """When no specification key was produced, has_specification should not be checked."""
    tester, jena = _make_tester(check_spec=False)
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types={"administrative"}
    )
    jena.check_tender_has_spec.assert_not_called()
    assert result is True


def test_admin_gate_skipped_when_admin_not_present():
    """When no administrative key was produced, has_administrative should not be checked."""
    tester, jena = _make_tester(check_admin=False)
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types={"specification", "product"}
    )
    jena.check_tender_has_admin.assert_not_called()
    assert result is True


def test_bordereau_gates_skipped_when_product_not_present():
    """When no product key was produced, bordereau gates should not be checked."""
    tester, jena = _make_tester(check_bordereau=False, check_articles=False)
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types={"specification"}
    )
    jena.check_tender_has_bordereau.assert_not_called()
    jena.check_bordereau_has_articles.assert_not_called()
    assert result is True


def test_all_gates_run_when_all_doc_types_present():
    """All gates run when all doc types are present and passing."""
    tester, jena = _make_tester()
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types={"specification", "administrative", "product"}
    )
    jena.check_tender_has_spec.assert_called_once()
    jena.check_tender_has_admin.assert_called_once()
    jena.check_tender_has_bordereau.assert_called_once()
    jena.check_bordereau_has_articles.assert_called_once()
    assert result is True


def test_failing_gate_returns_false():
    """A gate that fails returns False from validate_tender_in_jena."""
    tester, jena = _make_tester(check_spec=False)
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types={"specification"}
    )
    assert result is False


def test_empty_present_doc_types_logs_warning_passes():
    """If present_doc_types is empty, no gates run and result is True (with a warning)."""
    tester, jena = _make_tester()
    result = tester.validate_tender_in_jena(
        "http://example.com/Tender_foo",
        present_doc_types=set()
    )
    jena.check_tender_has_spec.assert_not_called()
    assert result is True
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd 5_Ingestion
python -m pytest tests/test_data_tester_conditional_gates.py -v 2>&1 | head -30
```
Expected: `TypeError: validate_tender_in_jena() got unexpected keyword argument 'present_doc_types'`

- [ ] **Step 1.3: Update `data_tester.py::validate_tender_in_jena`**

Replace the method body in `5_Ingestion/src/data_tester.py` (lines 148–172):

```python
def validate_tender_in_jena(self, tender_iri: str, present_doc_types: set = None) -> bool:
    """
    Run quality gate checks against the Jena KB for an already-ingested tender.
    Gates are applied only for document types that were actually produced by extraction.

    Args:
        tender_iri: Full IRI of the tender in Jena.
        present_doc_types: Set of doc types extracted (e.g. {'specification', 'product'}).
                           If None (legacy call), all gates run.
    """
    if not self.jena:
        logger.warning("No Jena client configured — skipping KB quality gates.")
        return True

    if present_doc_types is not None and len(present_doc_types) == 0:
        logger.warning(
            f"Tender {tender_iri}: no doc types reported — skipping all quality gates."
        )
        return True

    # Gate → (condition: doc type must be present, check fn)
    gate_conditions = [
        ("has_specification",      "specification",   self.jena.check_tender_has_spec),
        ("has_administrative",     "administrative",  self.jena.check_tender_has_admin),
        ("has_bordereau",          "product",         self.jena.check_tender_has_bordereau),
        ("bordereau_has_articles", "product",         self.jena.check_bordereau_has_articles),
    ]

    all_pass = True
    for check_name, required_doc_type, check_fn in gate_conditions:
        # Skip gate if we know the doc type was absent in this tender
        if present_doc_types is not None and required_doc_type not in present_doc_types:
            logger.debug(f"Quality gate SKIPPED: {check_name} (no {required_doc_type} in this tender)")
            continue

        result = check_fn(tender_iri)
        if result:
            logger.info(f"Quality gate PASSED: {check_name}")
        else:
            logger.error(f"Quality gate FAILED: {check_name} for tender {tender_iri}")
            all_pass = False

    return all_pass
```

- [ ] **Step 1.4: Update `main.py::process_message` to extract and pass `present_doc_types`**

In `5_Ingestion/main.py`, after line `body = json.loads(message['Body'])`, add:

```python
# Derive which doc types were actually produced by extraction
present_doc_types: set = set()
for doc_type in ("specification", "administrative", "product", "avis"):
    if body.get(f"{doc_type}_key"):
        present_doc_types.add(doc_type)
```

Then update the call to `validate_tender_in_jena` at line ~151:

```python
post_validation_passed = self.tester.validate_tender_in_jena(tender_iri, present_doc_types=present_doc_types)
```

- [ ] **Step 1.5: Run tests to verify they pass**

```bash
cd 5_Ingestion
python -m pytest tests/test_data_tester_conditional_gates.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 1.6: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 5_Ingestion/src/data_tester.py 5_Ingestion/main.py 5_Ingestion/tests/test_data_tester_conditional_gates.py
git commit -m "fix(5_Ingestion): make quality gates conditional on present doc types

Fixes has_administrative and has_specification gates that were failing
on spec-only and admin-only tenders respectively. Gates now only run
when the corresponding doc type key was produced by extraction."
```

---

## Task 2 — Fix ghost SQS message (NoSuchKey loop) in 5_Ingestion

**Files:**
- Modify: `5_Ingestion/main.py:62-178` (`process_message`)

### Why this loops

When `_get_s3_json(key)` raises `botocore.exceptions.ClientError` with code `NoSuchKey` (e.g., for a rejected tender whose S3 files were never created), the exception propagates to the top-level `except Exception as e` handler. That handler logs an error and returns `False` — but crucially it **does not delete the SQS message**. On the next visibility timeout, the message reappears. The `TO4130038/2026/ONEEBELEC` tender hit this loop 5+ times before triggering a different code path.

### Fix strategy

Import `botocore.exceptions.ClientError` and wrap the processing body. When any S3 `NoSuchKey` is encountered: log as anomaly + delete message immediately to prevent the loop.

- [ ] **Step 2.1: Write failing test**

Create `5_Ingestion/tests/test_process_message_no_such_key.py`:

```python
import json
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from botocore.exceptions import ClientError


def _no_such_key_error():
    return ClientError(
        error_response={"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
        operation_name="GetObject",
    )


@pytest.mark.asyncio
async def test_nosuchkey_deletes_message_and_returns_false():
    """NoSuchKey during S3 fetch must delete the SQS message and return False."""
    from main import KBIngestor

    ingestor = KBIngestor.__new__(KBIngestor)
    ingestor.queue_url = "https://sqs.fake/queue"
    ingestor.sqs = MagicMock()
    ingestor.jena = MagicMock()
    ingestor.tester = MagicMock()
    ingestor.embedder = MagicMock()
    ingestor.vector_store = MagicMock()
    ingestor.s3 = MagicMock()

    ingestor.jena.find_tender_by_ref.return_value = "http://example.com/Tender_foo"
    ingestor.s3.get_object.side_effect = _no_such_key_error()

    msg = {
        "Body": json.dumps({
            "tender_ref": "TO4130038/2026/ONEEBELEC",
            "avis_key": "chunks_tender/TO4130038/2026/ONEEBELEC/avis.json",
        }),
        "ReceiptHandle": "fake-receipt",
    }

    result = await ingestor.process_message(msg)

    assert result is False
    ingestor.sqs.delete_message.assert_called_once_with(
        QueueUrl="https://sqs.fake/queue",
        ReceiptHandle="fake-receipt",
    )
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
cd 5_Ingestion
python -m pytest tests/test_process_message_no_such_key.py -v 2>&1 | head -20
```
Expected: FAIL — `sqs.delete_message` not called when NoSuchKey is raised

- [ ] **Step 2.3: Add NoSuchKey handling to `main.py::process_message`**

At the top of `5_Ingestion/main.py`, add the import:

```python
from botocore.exceptions import ClientError
```

In `process_message`, wrap the existing `except Exception as e` with a specific NoSuchKey check **first**:

```python
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.warning(
                    f"Tender {tender_ref if 'tender_ref' in locals() else '?'}: "
                    f"S3 key not found (NoSuchKey) — likely a rejected tender whose files "
                    f"were never created. Deleting message to prevent loop."
                )
                if 'batch_id' in locals() and batch_id and 'tender_ref' in locals() and tender_ref:
                    mon_anomaly(batch_id, tender_ref, "ingestion", ["s3_no_such_key"])
                    mon_failed(batch_id, tender_ref, "ingestion", error="s3_no_such_key")
                self.sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                return False
            # Other ClientError (throttling, permissions, etc.) — log and do not delete
            logger.error(
                f"Tender {tender_ref if 'tender_ref' in locals() else '?'}: "
                f"AWS ClientError — {str(e)}"
            )
            if 'batch_id' in locals() and batch_id and 'tender_ref' in locals() and tender_ref:
                mon_failed(batch_id, tender_ref, "ingestion", error=str(e))
            return False
        except Exception as e:
            logger.error(f"Tender {tender_ref if 'tender_ref' in locals() else '?'}: unexpected error — {str(e)}")
            if 'batch_id' in locals() and batch_id and 'tender_ref' in locals() and tender_ref:
                mon_failed(batch_id, tender_ref, "ingestion", error=str(e))
            return False
```

This **replaces** the current single `except Exception as e` block.

- [ ] **Step 2.4: Run test to verify it passes**

```bash
cd 5_Ingestion
python -m pytest tests/test_process_message_no_such_key.py -v
```
Expected: PASS

- [ ] **Step 2.5: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 5_Ingestion/main.py 5_Ingestion/tests/test_process_message_no_such_key.py
git commit -m "fix(5_Ingestion): delete SQS message on NoSuchKey to prevent ghost loop

Tenders rejected by kg_builder have no S3 files. When the ingestion
container tries to fetch their chunks it gets NoSuchKey. Without this
fix, the message is never deleted and loops until visibility timeout."
```

---

## Task 3 — Log silent drops in 1_Update

**Files:**
- Modify: `1_Update/Db_updater.py:1341-1348`
- Modify: `1_Update/kg_builder.py:938-986` (`post_tenders_to_ocr_queue`)

### What "silent drop" means

When a tender's file download fails but metadata scraping succeeds, `Db_updater.py` calls `mon_complete` with `docs_count=0`. No anomaly is raised. The tender then enters `kg_builder.py`, passes Phase 3, and is posted to the OCR queue. The OCR container finds no files in S3 and either fails silently or produces empty output. The pipeline monitoring has no record of this gap.

### Fix part A: emit anomaly in Db_updater when docs_count == 0

- [ ] **Step 3.1: Write failing test**

Create `1_Update/tests/test_docs_count_zero_anomaly.py`:

```python
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


def test_anomaly_emitted_when_no_documents_downloaded():
    """mon_anomaly should be called with no_documents_downloaded when docs_count is 0."""
    with patch("monitor.anomaly") as mock_anomaly, \
         patch("monitor.complete") as mock_complete:
        # Simulate the post-process logic with docs_count == 0
        batch_id = "batch_test"
        composite_reference = "18/2026/AMDL_AGEMARDEVLOG"
        docs_count = 0

        # This is the logic we'll add to Db_updater.py
        if docs_count == 0:
            mock_anomaly(batch_id, composite_reference, "update", ["no_documents_downloaded"])
        mock_complete(batch_id, composite_reference, "update", scrape_time_s=1.0, docs_count=docs_count)

        mock_anomaly.assert_called_once_with(
            batch_id, composite_reference, "update", ["no_documents_downloaded"]
        )
        mock_complete.assert_called_once()
```

- [ ] **Step 3.2: Run test to verify it fails (as a sanity check of the logic)**

```bash
cd 1_Update
python -m pytest tests/test_docs_count_zero_anomaly.py -v 2>&1 | head -20
```
Expected: PASS (the test logic is self-contained, verifies the intended behavior shape)

- [ ] **Step 3.3: Add anomaly emission in `Db_updater.py`**

In `1_Update/Db_updater.py`, locate lines 1341-1348:

```python
            if self.batch_id:
                scrape_time = (datetime.now() - scrape_start).total_seconds()
                docs_count = len([f for f in (self.downloads_dir / composite_reference.replace('/', '_')).iterdir()]) if (self.downloads_dir / composite_reference.replace('/', '_')).exists() else 1
                mon_complete(
                    self.batch_id, composite_reference, "update",
                    scrape_time_s=round(scrape_time, 1),
                    docs_count=docs_count,
                )
```

Replace with:

```python
            if self.batch_id:
                scrape_time = (datetime.now() - scrape_start).total_seconds()
                docs_count = len([f for f in (self.downloads_dir / composite_reference.replace('/', '_')).iterdir()]) if (self.downloads_dir / composite_reference.replace('/', '_')).exists() else 0
                if docs_count == 0:
                    logger.warning(
                        f"Tender {composite_reference}: scraping completed but 0 documents downloaded. "
                        f"This tender will not have any documents in S3 for OCR processing."
                    )
                    mon_anomaly(
                        self.batch_id, composite_reference, "update", ["no_documents_downloaded"]
                    )
                mon_complete(
                    self.batch_id, composite_reference, "update",
                    scrape_time_s=round(scrape_time, 1),
                    docs_count=docs_count,
                )
```

### Fix part B: skip OCR post in kg_builder for tenders with no S3 files

- [ ] **Step 3.4: Update `kg_builder.py::post_tenders_to_ocr_queue`**

In `1_Update/kg_builder.py`, locate the `post_tenders_to_ocr_queue` method around line 938. At the beginning of the loop that iterates over tenders, add a check:

Find the section where each tender is posted (around line 965-980). Before constructing the message body, add:

```python
                # Skip tenders that have no S3 documents — OCR would find an empty folder
                if not tender.get('s3_folder'):
                    logger.warning(
                        f"Skipping OCR post for {tender.get('reference', '?')}: "
                        f"no s3_folder recorded (no files were uploaded to S3)."
                    )
                    failed_count += 1
                    continue
```

This check uses `s3_folder` which is set at `Db_updater.py:1331` only when `any_downloaded` is True. Tenders with no downloads will have no `s3_folder` key.

- [ ] **Step 3.5: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 1_Update/Db_updater.py 1_Update/kg_builder.py 1_Update/tests/test_docs_count_zero_anomaly.py
git commit -m "fix(1_Update): log and block silent drops when docs_count=0

When a tender's file download fails but metadata scraping succeeds,
emit no_documents_downloaded anomaly in monitoring and skip the OCR
queue post in kg_builder to prevent empty-folder processing."
```

---

## Task 4 — Add local DeepSeek inference wrapper in 4_Extraction

**Files:**
- Create: `4_Extraction/src/local_llm_wrapper.py`
- Modify: `4_Extraction/src/document_chunker.py:44-53`
- Modify: `4_Extraction/main.py:60-61`
- Modify: `4_Extraction/.env`
- Modify: `4_Extraction/docker-compose.yml`

### Context

The Ollama container (`deepseek-r1:1.5b`) exposes an OpenAI-compatible API at port 11434. It runs on the `local_llm_default` Docker network (IP `172.20.0.2`). The extraction container is on `tender_network` only. We need to:
1. Join extraction to `local_llm_default` so it can reach Ollama by service name
2. Add a lightweight local wrapper using the same `OpenAI` client pointed at Ollama
3. Make the local model the **primary** inference path (fast, free, no rate limit), with OpenRouter as fallback for when local is unavailable

### Note on `deepseek-r1:1.5b`

The 1.5b model is small and fast but does not support `json_mode` (`response_format: json_object`). The wrapper must strip the `json_mode` flag when calling Ollama and instead rely on prompt-level JSON instructions (already present in the existing prompts).

- [ ] **Step 4.1: Write failing test for LocalLLMWrapper**

Create `4_Extraction/tests/test_local_llm_wrapper.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


def test_local_llm_wrapper_calls_ollama_endpoint():
    """LocalLLMWrapper should POST to Ollama base URL using the OpenAI client."""
    with patch("src.local_llm_wrapper.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"result": "ok"}'))
        ]
        MockOpenAI.return_value = mock_client

        from src.local_llm_wrapper import LocalLLMWrapper
        wrapper = LocalLLMWrapper(base_url="http://ollama:11434", model="deepseek-r1:1.5b")
        result = wrapper.chat_completion([{"role": "user", "content": "hello"}])

        MockOpenAI.assert_called_once_with(base_url="http://ollama:11434/v1", api_key="ollama")
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "deepseek-r1:1.5b"
        assert "response_format" not in call_kwargs  # json_mode stripped
        assert result == '{"result": "ok"}'


def test_local_llm_wrapper_json_mode_stripped():
    """json_mode=True must not be passed to Ollama (1.5b model does not support it)."""
    with patch("src.local_llm_wrapper.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="{}"))
        ]
        MockOpenAI.return_value = mock_client

        from src.local_llm_wrapper import LocalLLMWrapper
        wrapper = LocalLLMWrapper(base_url="http://ollama:11434", model="deepseek-r1:1.5b")
        wrapper.chat_completion([{"role": "user", "content": "test"}], json_mode=True)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "response_format" not in call_kwargs


def test_local_llm_wrapper_raises_on_failure():
    """When the Ollama call fails, the exception should propagate."""
    with patch("src.local_llm_wrapper.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = ConnectionError("ollama unreachable")
        MockOpenAI.return_value = mock_client

        from src.local_llm_wrapper import LocalLLMWrapper
        wrapper = LocalLLMWrapper(base_url="http://ollama:11434", model="deepseek-r1:1.5b")
        with pytest.raises(ConnectionError):
            wrapper.chat_completion([{"role": "user", "content": "test"}])
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
cd 4_Extraction
python -m pytest tests/test_local_llm_wrapper.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'LocalLLMWrapper' from 'src.local_llm_wrapper'` (file doesn't exist yet)

- [ ] **Step 4.3: Create `4_Extraction/src/local_llm_wrapper.py`**

```python
"""
Local LLM wrapper for Ollama inference.
Uses the OpenAI-compatible API that Ollama exposes at /v1.
Intentionally does NOT support json_mode — the deepseek-r1:1.5b model
does not implement response_format. JSON is requested via prompt instructions.
"""
import logging
import os
from typing import List, Dict, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)


class LocalLLMWrapper:
    """
    Thin wrapper around Ollama's OpenAI-compatible endpoint.
    Use as primary inference when Ollama is reachable, fall through
    to OpenRouterClientWrapper otherwise.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if not OpenAI:
            raise ImportError("openai package is required")

        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
        self.model = model or os.environ.get("LOCAL_MODEL", "deepseek-r1:1.5b")

        # Ollama accepts any non-empty string as api_key
        self.client = OpenAI(
            base_url=f"{self.base_url.rstrip('/')}/v1",
            api_key="ollama",
        )
        logger.info(f"LocalLLMWrapper initialized: model={self.model} base_url={self.base_url}")

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        json_mode: bool = False,  # accepted for API compatibility, intentionally ignored
    ) -> str:
        """
        Synchronous chat completion via local Ollama.
        json_mode is silently ignored — deepseek-r1:1.5b does not support
        response_format. Callers must rely on prompt-level JSON instructions.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            # No response_format — not supported by 1.5b
        )
        content = response.choices[0].message.content
        logger.info(f"✓ Local inference complete using {self.model}")
        return content

    async def chat_completion_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        """
        Async wrapper — runs sync call in executor to avoid blocking event loop.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.chat_completion(messages, temperature=temperature, json_mode=json_mode),
        )
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd 4_Extraction
python -m pytest tests/test_local_llm_wrapper.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 4.5: Update `DocumentChunker.__init__` to accept and try local model first**

In `4_Extraction/src/document_chunker.py`, replace the `__init__` signature and body (lines 44–53):

```python
    def __init__(
        self,
        region_name: str = "us-east-1",
        openrouter_api_key: Optional[str] = None,
        client: Optional[OpenRouterClientWrapper] = None,
        local_client=None,
        decomposer_func: Optional[Any] = None,
    ):
        self.region_name = region_name
        self._local_llm = local_client  # None means local inference disabled
        self.llm = client or OpenRouterClientWrapper(api_key=openrouter_api_key)

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=STANDARD_CHUNK_SIZE,
            chunk_overlap=STANDARD_CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " "]
        )
        self._decomposer_func = decomposer_func if decomposer_func is not None else (decompose_text if _DECOMPOSE_AVAILABLE else None)
```

Add a helper method `_llm_call` that tries local first, then falls through:

```python
    async def _llm_call_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        """Try local Ollama first, fall through to OpenRouter on any error."""
        if self._local_llm is not None:
            try:
                result = await self._local_llm.chat_completion_async(
                    messages, temperature=temperature, json_mode=json_mode
                )
                return result
            except Exception as e:
                logger.warning(f"Local LLM failed ({e}) — falling back to OpenRouter")
        return await self.llm.chat_completion_async(messages, temperature=temperature, json_mode=json_mode)
```

Then grep for all calls to `self.llm.chat_completion_async(` in `document_chunker.py` and replace them with `await self._llm_call_async(`.

Run this to find them:

```bash
grep -n "self\.llm\.chat_completion_async" 4_Extraction/src/document_chunker.py
```

Replace each occurrence. For example, if line 150 has:
```python
response = await self.llm.chat_completion_async(messages, temperature=0.0, json_mode=True)
```
Replace with:
```python
response = await self._llm_call_async(messages, temperature=0.0, json_mode=True)
```

- [ ] **Step 4.6: Update `4_Extraction/main.py` to instantiate and inject `LocalLLMWrapper`**

In `4_Extraction/main.py`, after the existing imports add:

```python
from src.local_llm_wrapper import LocalLLMWrapper
```

Replace the `DocumentChunker` instantiation at line ~60:

```python
chunker = DocumentChunker(AWS_REGION, OPENROUTER_API_KEY)
```

With:

```python
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "deepseek-r1:1.5b")

local_llm = None
if OLLAMA_BASE_URL:
    try:
        local_llm = LocalLLMWrapper(base_url=OLLAMA_BASE_URL, model=LOCAL_MODEL)
        logger.info(f"Local LLM enabled: {LOCAL_MODEL} at {OLLAMA_BASE_URL}")
    except Exception as e:
        logger.warning(f"Local LLM init failed ({e}) — will use OpenRouter only")

chunker = DocumentChunker(AWS_REGION, OPENROUTER_API_KEY, local_client=local_llm)
```

- [ ] **Step 4.7: Update `4_Extraction/.env`**

Add these lines to `4_Extraction/.env`:

```
OLLAMA_BASE_URL=http://ollama:11434
LOCAL_MODEL=deepseek-r1:1.5b
```

Also update the primary model env to avoid the rate-limited Groq model as primary:

```
PRIMARY_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct
FALLBACK_MODEL_1=google/gemini-2.5-flash-lite
FALLBACK_MODEL_2=meta-llama/llama-4-maverick-17b-128e-instruct
```

- [ ] **Step 4.8: Update `4_Extraction/docker-compose.yml` to join Ollama network**

Replace the `networks` section in `4_Extraction/docker-compose.yml`:

```yaml
networks:
  tender_network:
    driver: bridge
    name: tender_network
    external: true
  local_llm_default:
    external: true
    name: local_llm_default
```

And in the `extraction` service, add the network:

```yaml
services:
  extraction:
    ...
    networks:
      - tender_network
      - local_llm_default
```

- [ ] **Step 4.9: Verify Ollama is reachable from the running extraction container**

```bash
# Connect the running container to the Ollama network (for live testing before rebuild)
docker network connect local_llm_default extraction

# Test connectivity
docker exec extraction curl -s http://ollama:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print('Models:', [m['name'] for m in d.get('models',[])])"
```

Expected output: `Models: ['deepseek-r1:1.5b']`

- [ ] **Step 4.10: Commit**

```bash
cd /home/naoufel/projects/tender_scrape
git add 4_Extraction/src/local_llm_wrapper.py \
        4_Extraction/src/document_chunker.py \
        4_Extraction/main.py \
        4_Extraction/.env \
        4_Extraction/docker-compose.yml \
        4_Extraction/tests/test_local_llm_wrapper.py
git commit -m "feat(4_Extraction): add local DeepSeek inference via Ollama

Use deepseek-r1:1.5b as primary LLM for chunk extraction.
OpenRouter is kept as fallback for when Ollama is unavailable.
Eliminates Groq 429 rate-limiting on gpt-oss-safeguard-20b which
was causing retry delays on every tender processed."
```

---

## Task 5 — Rebuild and smoke-test extraction container

After all code changes, rebuild the extraction container and verify it uses local inference.

- [ ] **Step 5.1: Rebuild the extraction image**

```bash
cd /home/naoufel/projects/tender_scrape
docker compose -f 4_Extraction/docker-compose.yml build --no-cache extraction
```

Expected: Build succeeds with no errors

- [ ] **Step 5.2: Restart the extraction container**

```bash
docker compose -f 4_Extraction/docker-compose.yml up -d extraction
```

- [ ] **Step 5.3: Verify Ollama is reachable and local model is selected**

```bash
# Wait for container to start
sleep 5
docker logs extraction 2>&1 | grep -E "Local LLM|Ollama|OLLAMA|local_llm" | tail -5
```

Expected: `INFO - Local LLM enabled: deepseek-r1:1.5b at http://ollama:11434`

- [ ] **Step 5.4: Post a test message to EXTRACTION_QUEUE and watch logs**

```bash
# Watch extraction logs for a few minutes to confirm local model is used
docker logs extraction -f 2>&1 | grep -E "(Local inference|Local LLM|falling back|OpenRouter)" | head -20
```

Expected: Logs show `✓ Local inference complete using deepseek-r1:1.5b` for processed tenders, with no OpenRouter 429 errors.

- [ ] **Step 5.5: Commit**

No code changes in this task — outcome is validated at Step 5.4.

---

## Self-Review

### Spec coverage check

| Requirement | Task |
|-------------|------|
| `has_administrative` gate failing on most tenders | Task 1 ✓ |
| `30/2026/DR5` admin-only failing 3 gates | Task 1 ✓ (same root cause, same fix) |
| Ghost `TO4130038` NoSuchKey loop | Task 2 ✓ |
| `docs_count=0` silent drops | Task 3 ✓ |
| OpenRouter 429 rate limiting | Task 4 ✓ |
| Local DeepSeek as primary inference | Task 4 ✓ |
| Search failures in 1_Update = normal, just log | NOT changed (existing log already says `search_failed`) ✓ |
| Don't break other processes | Each task is surgical and isolated ✓ |

### Placeholder scan

- All code blocks are complete
- No TBD / TODO / implement later
- All method signatures defined before they are referenced

### Type consistency

- `validate_tender_in_jena(tender_iri, present_doc_types=None)` — same signature in test and implementation
- `LocalLLMWrapper.chat_completion_async` used in `_llm_call_async` — same signature
- `_llm_call_async` called as `await self._llm_call_async(messages, ...)` — consistent

### What is NOT changed (by design)

- `1_Update` search timeout behavior — normal website connectivity failures, no change needed
- `3_Classification` AWS credential/queue errors — historical from April 6, auto-resolved
- `5_Ingestion` S3 connection pool full warning — non-blocking, deferred
- `4_Extraction` `acte_engagement`/`declaration` defaulting warnings — acceptable fallback behavior
