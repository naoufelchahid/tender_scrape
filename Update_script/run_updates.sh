#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the script directory
cd "$SCRIPT_DIR"

# Activate virtual environment if it exists
# Activate virtual environment if it exists (check local and then root)
PYTHON_CMD="python3"
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
elif [ -d "$SCRIPT_DIR/../venv" ]; then
    source "$SCRIPT_DIR/../venv/bin/activate"
    PYTHON_CMD="$SCRIPT_DIR/../venv/bin/python3"
fi

# Set error handling
set -e

# Support for project imports
export PYTHONPATH="$SCRIPT_DIR/..:$PYTHONPATH"

# Define categories in specific order
categories=("services" "travaux" "fournitures")

echo "=================================================="
echo "PHASE 1: FETCHING REFERENCES (ref_updater.py)"
echo "=================================================="

# Run ref_updater for all categories first
for category in "${categories[@]}"; do
    echo "Running ref_updater.py for category: $category"
    output_file="new_references_${category}.json"
    
    if $PYTHON_CMD ref_updater.py --category "$category" --output "$output_file"; then
        echo "✓ Successfully fetched references for $category"
    else
        echo "✗ Error running ref_updater.py for $category"
        exit 1
    fi
    echo "--------------------------------------------------"
done

echo ""
echo "=================================================="
echo "PHASE 2: PROCESSING TENDERS (Db_updater.py)"
echo "=================================================="

# Then run Db_updater for all categories
for category in "${categories[@]}"; do
    input_file="new_references_${category}.json"
    
    if [ -f "$input_file" ]; then
        echo "Running Db_updater.py for category: $category"
        
        if $PYTHON_CMD Db_updater.py --input-file "$input_file"; then
            echo "✓ Successfully processed tenders for $category"
        else
            echo "✗ Error running Db_updater.py for $category"
            # Don't exit here, try to process other categories
        fi
    else
        echo "⚠ Input file $input_file not found (skipping)"
    fi
    echo "--------------------------------------------------"
done

echo "All updates completed."
