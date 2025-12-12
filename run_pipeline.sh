#!/bin/bash
# Tender Scraper Pipeline
# Runs the complete workflow: scrape → push → check → heal

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Log file
LOG_FILE="pipeline_$(date +%Y%m%d_%H%M%S).log"

# Function to log messages
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] ✅ $1${NC}" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ❌ $1${NC}" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  $1${NC}" | tee -a "$LOG_FILE"
}

# Activate virtual environment
log "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "================================================================================"
echo "                    TENDER SCRAPER PIPELINE"
echo "================================================================================"
echo ""

# Step 1: Run Scraper
echo "================================================================================"
log "STEP 1/4: Running Tender Scraper (scraper.py)"
echo "================================================================================"
if python scraper.py 2>&1 | tee -a "$LOG_FILE"; then
    log_success "Scraper completed successfully"
else
    log_error "Scraper failed"
    exit 1
fi
echo ""

# Step 2: Run Data Pusher
echo "================================================================================"
log "STEP 2/4: Running Data Pusher (data_pusher.py)"
echo "================================================================================"
if python data_pusher.py 2>&1 | tee -a "$LOG_FILE"; then
    log_success "Data pusher completed successfully"
else
    log_error "Data pusher failed"
    exit 1
fi
echo ""

# Step 3: Run Database Health Checker
echo "================================================================================"
log "STEP 3/4: Running Database Health Checker (Db_health_checker.py)"
echo "================================================================================"
if python Db_health_checker.py 2>&1 | tee -a "$LOG_FILE"; then
    log_success "Health checker completed successfully"
    
    # Check if there are missing files
    MISSING_COUNT=$(python -c "import json; data=json.load(open('db_health_report.json')); print(data['missing_files_count'])")
    log "Found $MISSING_COUNT missing files"
else
    log_error "Health checker failed"
    exit 1
fi
echo ""

# Step 4: Run DB Healer (only if there are missing files)
echo "================================================================================"
log "STEP 4/4: Running DB Healer (Db_Healer.py)"
echo "================================================================================"

if [ "$MISSING_COUNT" -gt 0 ]; then
    log "Attempting to download $MISSING_COUNT missing files..."
    if python Db_Healer.py 2>&1 | tee -a "$LOG_FILE"; then
        log_success "DB Healer completed successfully"
    else
        log_warning "DB Healer completed with errors (some files may not be available)"
    fi
else
    log_success "No missing files - skipping DB Healer"
fi
echo ""

# Final Summary
echo "================================================================================"
echo "                         PIPELINE COMPLETE"
echo "================================================================================"
log_success "All pipeline steps completed!"
echo ""
log "Summary:"
log "  - Tenders scraped and saved to tenders.json"
log "  - Data pushed to database and S3"
log "  - Health check completed (report: db_health_report.json)"
log "  - Missing files recovery attempted"
echo ""
log "Full log saved to: $LOG_FILE"
echo "================================================================================"
