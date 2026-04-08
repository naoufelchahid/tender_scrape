#!/usr/bin/env bash
# =============================================================================
# e2e_test.sh - End-to-End Single-Tender Pipeline Test Orchestrator
# =============================================================================
# Automates full pipeline startup for testing:
#   1. Create Docker network (if needed)
#   2. Build all Docker images
#   3. Start Fuseki + 5_Ingestion (with healthcheck)
#   4. Start 2_Ocr, 3_Classification, 4_Extraction
#   5. Run 1_Update scraper limited to N tenders
#   6. Optionally tail all logs and monitor queue depths
#
# Usage:
#   bash e2e_test.sh [OPTIONS]
#
# Options:
#   --build              Force rebuild all Docker images (default: use cached)
#   --limit N            Number of tenders to process (default: 1)
#   --skip-scraper       Skip 1_Update; assume new_references.json populated
#   --monitor            After startup, tail logs from all containers
#   --stop               Stop and remove all test containers + services
#   --help               Show this message
#
# Examples:
#   bash e2e_test.sh --build --limit 1 --monitor
#   bash e2e_test.sh --skip-scraper --monitor
#   bash e2e_test.sh --stop
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
NETWORK_NAME="tender_network"
FUSEKI_COMPOSE="${PROJECT_ROOT}/5_Ingestion/docker-compose.fuseki.yml"
OCR_COMPOSE="${PROJECT_ROOT}/2_Ocr/docker-compose.yml"
UPDATE_DIR="${PROJECT_ROOT}/1_Update"

# Container names for services without compose
CLASSIFICATION_CONTAINER="e2e_classification"
EXTRACTION_CONTAINER="e2e_extraction"

# Docker command (docker compose or docker-compose)
DOCKER_COMPOSE="docker compose"

# Defaults
BUILD_IMAGES=false
LIMIT_TENDERS=1
SKIP_SCRAPER=false
MONITOR_MODE=false
STOP_MODE=false
GPU_AVAILABLE=false
JENA_ALREADY_UP=false

# =============================================================================
# Colors & Logging
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()     { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*" >&2; }
die()     { error "$@"; exit 1; }

# =============================================================================
# Functions
# =============================================================================

show_help() {
    grep "^#" "$0" | grep -E "^\s*#\s+(bash|Usage|Options|Examples)" | sed 's/^[[:space:]]*# *//'
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build)       BUILD_IMAGES=true; shift ;;
            --limit)       LIMIT_TENDERS="$2"; shift 2 ;;
            --skip-scraper) SKIP_SCRAPER=true; shift ;;
            --monitor)     MONITOR_MODE=true; shift ;;
            --stop)        STOP_MODE=true; shift ;;
            --help)        show_help; exit 0 ;;
            *)             die "Unknown option: $1"; shift ;;
        esac
    done
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        die "Docker is not installed"
    fi
    if ! docker info &> /dev/null; then
        die "Docker daemon is not running or not accessible"
    fi
    success "Docker ready"
}

check_env_files() {
    local required_files=(
        "${PROJECT_ROOT}/.env"
        "${PROJECT_ROOT}/1_Update/.env"
        "${PROJECT_ROOT}/2_Ocr/.env"
        "${PROJECT_ROOT}/3_Classification/.env"
        "${PROJECT_ROOT}/4_Extraction/.env"
        "${PROJECT_ROOT}/5_Ingestion/.env"
    )

    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            die ".env file not found: $file"
        fi
    done
    success "All .env files present"
}

check_aws_credentials() {
    # Verify credentials are set in root .env
    if ! grep -q "AWS_ACCESS_KEY_ID" "${PROJECT_ROOT}/.env" 2>/dev/null; then
        warn "AWS_ACCESS_KEY_ID not found in root .env (will use AWS CLI config if available)"
    fi
    if ! grep -q "AWS_SECRET_ACCESS_KEY" "${PROJECT_ROOT}/.env" 2>/dev/null; then
        warn "AWS_SECRET_ACCESS_KEY not found in root .env (will use AWS CLI config if available)"
    fi
    success "AWS credentials check done"
}

check_sqs_queues() {
    # Warn if SQS queue URLs are not set (optional, as they might be AWS defaults)
    local queues=(
        "OCR_QUEUE_URL"
        "EXTRACTION_QUEUE_URL"
        "KB_INGESTION_QUEUE_URL"
    )
    for queue in "${queues[@]}"; do
        if ! grep -q "$queue" "${PROJECT_ROOT}/.env" 2>/dev/null; then
            warn "$queue not found in root .env (queue polling may fail)"
        fi
    done
    success "SQS queue check done"
}

get_container_status() {
    docker inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo ""
}

ensure_container_running() {
    local name="$1"
    shift
    local status
    status=$(get_container_status "$name")

    case "$status" in
        running)
            log "  → $name already running, skipping"
            return 0
            ;;
        exited|paused|created)
            log "  → $name exists but is $status — restarting"
            docker start "$name" > /dev/null
            success "$name restarted"
            return 0
            ;;
        "")
            log "  → $name not found — creating"
            docker run -d --name "$name" "$@" > /dev/null
            success "$name started"
            ;;
        *)
            warn "$name is in unexpected state '$status' — attempting start"
            docker start "$name" > /dev/null || true
            ;;
    esac
}

check_gpu() {
    log "Checking GPU availability..."
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        local gpu_count
        gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
        success "GPU available ($gpu_count device(s) detected)"
        GPU_AVAILABLE=true
    elif docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        success "GPU available via Docker"
        GPU_AVAILABLE=true
    else
        warn "No GPU detected — OCR container will start WITHOUT --gpus flag (CPU fallback)"
        warn "OCR performance will be significantly slower"
        GPU_AVAILABLE=false
    fi
}

check_jena_connectivity() {
    local max_attempts="${1:-5}"
    local wait_seconds="${2:-1}"
    set -a; source "${PROJECT_ROOT}/.env" 2>/dev/null; set +a
    local jena_endpoint="${JENA_ENDPOINT:-http://localhost:3030}"
    # Strip any dataset/path suffix — ping lives at the Fuseki root
    local fuseki_base
    fuseki_base=$(echo "$jena_endpoint" | grep -oP '^https?://[^/]+')
    fuseki_base="${fuseki_base:-http://localhost:3030}"
    local url="${fuseki_base}/\$/ping"
    local attempt=0

    log "Checking Jena connectivity at $url ..."
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -sf "$url" &>/dev/null; then
            success "Jena is reachable at $fuseki_base"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep "$wait_seconds"
    done
    return 1
}

create_network() {
    if docker network inspect "$NETWORK_NAME" &> /dev/null; then
        log "Docker network $NETWORK_NAME already exists"
    else
        log "Creating Docker network: $NETWORK_NAME"
        docker network create "$NETWORK_NAME"
        success "Network created"
    fi
}

build_images() {
    if [[ "$BUILD_IMAGES" != true ]]; then
        log "Skipping image builds (use --build to force rebuild)"
        return
    fi

    log "Preparing shared dependencies..."
    # Replace symlinks with actual files for Docker context
    for stage in 1_Update 2_Ocr 3_Classification 4_Extraction 5_Ingestion; do
        if [ -L "${PROJECT_ROOT}/${stage}/monitor.py" ]; then
            rm "${PROJECT_ROOT}/${stage}/monitor.py"
            cp "${PROJECT_ROOT}/monitor.py" "${PROJECT_ROOT}/${stage}/monitor.py"
        fi
    done

    log "Building Docker images..."

    log "  → Building 2_Ocr..."
    docker build -t tender-ocr:latest "${PROJECT_ROOT}/2_Ocr/" > /dev/null
    success "2_Ocr built"

    log "  → Building 3_Classification..."
    docker build -t tender-classification:latest "${PROJECT_ROOT}/3_Classification/" > /dev/null
    success "3_Classification built"

    log "  → Building 4_Extraction..."
    docker build -t tender-extraction:latest -f "${PROJECT_ROOT}/4_Extraction/Dockerfile" "${PROJECT_ROOT}" > /dev/null
    success "4_Extraction built"

    log "  → Building 5_Ingestion (kb_ingestion)..."
    docker build -t tender-ingestion:latest -f "${PROJECT_ROOT}/5_Ingestion/Dockerfile" "${PROJECT_ROOT}" > /dev/null
    success "5_Ingestion built"

    success "All images built"
}

wait_for_fuseki() {
    local max_attempts=60
    local attempt=0
    local fuseki_url="http://localhost:3030/$/ping"

    log "Waiting for Fuseki to be healthy..."
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -sf "$fuseki_url" &> /dev/null; then
            success "Fuseki is healthy"
            return 0
        fi
        attempt=$((attempt + 1))
        echo -n "."
        sleep 1
    done

    die "Fuseki healthcheck failed after ${max_attempts}s"
}

start_services() {
    log "Starting all services..."

    log "  → Fuseki + 5_Ingestion..."
    if [[ "$JENA_ALREADY_UP" == true ]]; then
        log "  → Fuseki already up, skipping startup"
    else
        $DOCKER_COMPOSE -f "$FUSEKI_COMPOSE" up -d
        success "Fuseki + 5_Ingestion started"
        wait_for_fuseki
    fi
    check_jena_connectivity 60 1 || die "Jena unreachable after startup — aborting"

    log "  → Starting 2_Ocr..."
    local ocr_flags=(
        --env-file "${PROJECT_ROOT}/2_Ocr/.env"
        --restart unless-stopped
        --network "$NETWORK_NAME"
        --volume "${PROJECT_ROOT}/2_Ocr/logs:/app/logs"
        --volume "${PROJECT_ROOT}/2_Ocr/temp:/app/temp"
        --memory 8g
    )
    [[ "$GPU_AVAILABLE" == true ]] && ocr_flags+=(--gpus all)
    ensure_container_running ocr-container "${ocr_flags[@]}" tender-ocr:latest

    log "  → Starting 3_Classification..."
    ensure_container_running "$CLASSIFICATION_CONTAINER" \
        --env-file "${PROJECT_ROOT}/3_Classification/.env" \
        --restart unless-stopped \
        --network "$NETWORK_NAME" \
        tender-classification:latest

    log "  → Starting 4_Extraction..."
    ensure_container_running "$EXTRACTION_CONTAINER" \
        --env-file "${PROJECT_ROOT}/4_Extraction/.env" \
        --restart unless-stopped \
        --network "$NETWORK_NAME" \
        tender-extraction:latest

    log ""
    success "All services started"
}

run_scraper() {
    if [[ "$SKIP_SCRAPER" == true ]]; then
        if [[ ! -f "${UPDATE_DIR}/new_references.json" ]]; then
            die "--skip-scraper requires new_references.json to exist in 1_Update/"
        fi
        log "Skipping ref_updater.py; using existing new_references.json"
        log "Running Db_updater.py directly..."
        cd "$UPDATE_DIR"
        python3 Db_updater.py --max-tenders "$LIMIT_TENDERS" 2>&1 | tee -a run_updates.log
        cd "$PROJECT_ROOT"
    else
        log "Running 1_Update scraper (limit: $LIMIT_TENDERS tender(s))..."
        cd "$UPDATE_DIR"
        bash run_updates.sh "$LIMIT_TENDERS" 2>&1 | tee -a run_updates.log
        cd "$PROJECT_ROOT"
    fi

    success "Scraper completed"
}

monitor_logs() {
    log ""
    log "Monitoring logs from all services..."
    log "Press Ctrl+C to stop monitoring"
    log ""

    # Start log tailing in background
    $DOCKER_COMPOSE -f "$FUSEKI_COMPOSE" logs -f 2>/dev/null &
    local fuseki_pid=$!

    $DOCKER_COMPOSE -f "$OCR_COMPOSE" logs -f 2>/dev/null &
    local ocr_pid=$!

    docker logs -f "$CLASSIFICATION_CONTAINER" 2>/dev/null &
    local class_pid=$!

    docker logs -f "$EXTRACTION_CONTAINER" 2>/dev/null &
    local extract_pid=$!

    # Wait for Ctrl+C
    trap "kill $fuseki_pid $ocr_pid $class_pid $extract_pid 2>/dev/null; log 'Monitoring stopped'" EXIT INT TERM

    wait
}

monitor_queue_depths() {
    log ""
    log "Checking SQS queue depths..."

    # Source the root .env to get queue URLs
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a

    check_queue() {
        local queue_name="$1"
        local queue_url="$2"
        if [[ -z "$queue_url" ]]; then
            warn "$queue_name not configured"
            return
        fi
        local depth=$(aws sqs get-queue-attributes \
            --queue-url "$queue_url" \
            --attribute-names ApproximateNumberOfMessages \
            --query 'Attributes.ApproximateNumberOfMessages' \
            --output text 2>/dev/null || echo "N/A")
        log "  $queue_name: $depth messages"
    }

    check_queue "OCR_QUEUE" "${OCR_QUEUE_URL:-}"
    check_queue "CLASSIFICATION_QUEUE" "${CLASSIFICATION_QUEUE_URL:-}"
    check_queue "EXTRACTION_QUEUE" "${EXTRACTION_QUEUE_URL:-}"
    check_queue "KB_INGESTION_QUEUE" "${KB_INGESTION_QUEUE_URL:-}"
}

verify_jena_data() {
    log ""
    log "Verifying data in Jena..."

    # Source root .env
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a

    local jena_endpoint="${JENA_ENDPOINT:-http://localhost:3030}"
    # JENA_ENDPOINT may already be the full SPARQL query URL; derive base and build cleanly
    local fuseki_base
    fuseki_base=$(echo "$jena_endpoint" | grep -oP '^https?://[^/]+')
    fuseki_base="${fuseki_base:-http://localhost:3030}"
    local jena_dataset="${JENA_DATASET:-tenders}"
    local query_url="${fuseki_base}/${jena_dataset}/query"

    log "Jena endpoint: $query_url"

    # Simple COUNT query — grep failure handled explicitly to avoid pipefail exit
    local raw_response
    raw_response=$(curl -s -X POST "$query_url" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "query=SELECT%20(COUNT(%3Fs)%20as%20%3Fcount)%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20%7D" \
        2>/dev/null || true)
    local count
    count=$(echo "$raw_response" | grep -oP '(?<=>)\d+(?=<)' | head -1 || true)

    if [[ "$count" != "N/A" && "$count" -gt 0 ]]; then
        success "Jena contains $count triples"
    else
        warn "No triples found in Jena (or unable to query)"
    fi
}

stop_all() {
    log "Stopping all services..."

    log "  → Stopping Fuseki + 5_Ingestion..."
    $DOCKER_COMPOSE -f "$FUSEKI_COMPOSE" down 2>/dev/null || true
    success "Fuseki + 5_Ingestion stopped"

    log "  → Stopping 2_Ocr..."
    docker rm -f ocr-container 2>/dev/null || true
    success "2_Ocr stopped"

    log "  → Removing 3_Classification..."
    docker rm -f "$CLASSIFICATION_CONTAINER" 2>/dev/null || true
    success "3_Classification removed"

    log "  → Removing 4_Extraction..."
    docker rm -f "$EXTRACTION_CONTAINER" 2>/dev/null || true
    success "4_Extraction removed"

    log "  → Network teardown..."
    # Note: Don't remove the network automatically; user can do it manually if needed
    # docker network rm "$NETWORK_NAME" 2>/dev/null || true

    success "All services stopped"
    log ""
    log "To remove the Docker network, run:"
    log "  docker network rm $NETWORK_NAME"
}

# =============================================================================
# Main
# =============================================================================
main() {
    parse_args "$@"

    log "=========================================="
    log "E2E Single-Tender Pipeline Test"
    log "=========================================="
    log ""

    if [[ "$STOP_MODE" == true ]]; then
        stop_all
        exit 0
    fi

    # Preflight checks
    log "Running preflight checks..."
    check_docker
    check_env_files
    check_aws_credentials
    check_sqs_queues
    check_gpu
    if check_jena_connectivity 3 1; then
        JENA_ALREADY_UP=true
    else
        log "Jena not yet reachable — will start Fuseki"
        JENA_ALREADY_UP=false
    fi
    success "All preflight checks passed"
    log ""

    # Create network
    create_network
    log ""

    # Build images (if requested)
    build_images
    log ""

    # Start services
    start_services
    log ""

    # Run scraper
    run_scraper
    log ""

    # Post-run checks
    monitor_queue_depths
    verify_jena_data
    log ""

    # Monitor mode (optional)
    if [[ "$MONITOR_MODE" == true ]]; then
        monitor_logs
    else
        log "To monitor logs, run:"
        log "  bash e2e_test.sh --monitor"
        log ""
        log "To stop all services, run:"
        log "  bash e2e_test.sh --stop"
        log ""
        log "Jena UI: http://localhost:3030"
    fi
}

# =============================================================================
# Run
# =============================================================================
main "$@"
