#!/usr/bin/env bash
# =============================================================================
# run_updates.sh  — 13-Step Tender Pipeline Orchestrator
# =============================================================================
#
# Steps:
#   PHASE 1 (ref_updater.py):
#     1. Fetch known tender references from Apache Jena
#     2. Fetch live tender references from marchespublics.gov.ma
#     3. Compare and extract new references → new_references.json
#
#   PHASE 2 (Db_updater.py):
#     4. Read new_references.json
#     5. Extract all 18 metadata fields from each tender detail page
#     6. Detect all downloadable files in #panelPieces
#     7. Skip tender if no downloadable files found
#     8. Download all files → tender_doc_final/{ref}/  +  tenders_metadata/{ref}.json
#
#   PHASE 3 (kg_builder.py):
#     9.  Read tenders_metadata/*.json (only download_available=True)
#    10.  Build RDF graph (8 SPARQL ASK consistency checks)
#    11.  SHACL validation
#    12.  Serialize to N-Triples
#    13.  Upload .nt file to S3 (knowledge_Base/Daybatch/)
#
# Gate logic:
#   Phase 2 only runs if new_references.json is non-empty.
#   Phase 3 only runs if tenders_metadata/ contains at least one JSON file.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VENV_DIR="${VENV_DIR:-./venv}"
PYTHON="${VENV_DIR}/bin/python3"

NEW_REFS_FILE="new_references.json"
PROCESSED_FILE="processed_tenders.json"
METADATA_DIR="tenders_metadata"
DOWNLOADS_DIR="downloads"
OUTPUT_DIR="output"
ONTOLOGY="tender_structure_final.owl"
SHACL="tender_shacl_shapes.ttl"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { log "ERROR: $*" >&2; exit 1; }

check_python() {
    [[ -x "${PYTHON}" ]] || die "Python not found at ${PYTHON}. Run: python3 -m venv ${VENV_DIR}"
}

count_new_refs() {
    # Returns 0 if file is missing, empty, or tenders list is empty
    if [[ ! -f "${NEW_REFS_FILE}" ]]; then
        echo 0; return
    fi
    "${PYTHON}" -c "
import json, sys
try:
    d = json.load(open('${NEW_REFS_FILE}'))
    print(len(d.get('new_references', d.get('tenders', []))))
except Exception:
    print(0)
"
}

count_metadata_files() {
    # Returns number of *.json files in tenders_metadata/
    if [[ ! -d "${METADATA_DIR}" ]]; then
        echo 0; return
    fi
    find "${METADATA_DIR}" -maxdepth 1 -name '*.json' | wc -l
}

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
if [[ -f ".env" ]]; then
    set -a
    # shellcheck source=.env
    source .env
    set +a
fi

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
check_python

# Resolve max-tenders from CLI
MAX_TENDERS=""
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    MAX_TENDERS="--max-tenders ${1}"
    log "Will process at most ${1} tenders"
fi

# ---------------------------------------------------------------------------
# PHASE 1: Reference comparison  (Steps 1-3)
# ---------------------------------------------------------------------------
log "========================================================"
log "PHASE 1: Reference comparison (steps 1-3)"
log "========================================================"

"${PYTHON}" ref_updater.py 2>&1 | tee -a run_updates.log

NEW_COUNT=$(count_new_refs)
log "New references found: ${NEW_COUNT}"

# Gate: stop here if nothing to process
if [[ "${NEW_COUNT}" -eq 0 ]]; then
    log "⏭  No new tenders — nothing to download or ingest. Exiting cleanly."
    exit 0
fi

# ---------------------------------------------------------------------------
# PHASE 2: Metadata extraction + download + S3 upload  (Steps 4-8)
# ---------------------------------------------------------------------------
log "========================================================"
log "PHASE 2: Download & metadata extraction (steps 4-8)"
log "========================================================"

mkdir -p "${METADATA_DIR}" "${DOWNLOADS_DIR}" "${OUTPUT_DIR}"

"${PYTHON}" Db_updater.py \
    --input-file  "${NEW_REFS_FILE}"   \
    --output-file "${PROCESSED_FILE}"  \
    --downloads-dir "${DOWNLOADS_DIR}" \
    --metadata-dir  "${METADATA_DIR}"  \
    ${MAX_TENDERS} \
    2>&1 | tee -a run_updates.log

META_COUNT=$(count_metadata_files)
log "Metadata files written: ${META_COUNT}"

# Gate: stop if Phase 2 produced no metadata (all skipped or failed)
if [[ "${META_COUNT}" -eq 0 ]]; then
    log "⏭  No metadata files produced — skipping KG build."
    exit 0
fi

# ---------------------------------------------------------------------------
# PHASE 3: KG build, validate, serialize, upload  (Steps 9-13)
# ---------------------------------------------------------------------------
log "========================================================"
log "PHASE 3: Knowledge Graph build (steps 9-13)"
log "========================================================"

"${PYTHON}" kg_builder.py \
    --input-dir   "${METADATA_DIR}" \
    --output-dir  "${OUTPUT_DIR}"   \
    --ontology    "${ONTOLOGY}"     \
    --shacl-shapes "${SHACL}"      \
    2>&1 | tee -a run_updates.log

EXIT_CODE=${PIPESTATUS[0]}

if [[ "${EXIT_CODE}" -ne 0 ]]; then
    log "❌ PHASE 3 failed with exit code ${EXIT_CODE}"
    exit "${EXIT_CODE}"
fi

log "========================================================"
log "✅ Pipeline completed successfully"
log "========================================================"
