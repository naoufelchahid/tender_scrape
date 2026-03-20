#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the script directory
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found at $SCRIPT_DIR/venv"
    exit 1
fi

# Run Database Healer
echo "Starting Database Healer..."
python3 Db_Healer.py

echo "Healing process completed."
