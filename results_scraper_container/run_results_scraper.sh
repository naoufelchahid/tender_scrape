#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Run the results scraper
python3 results_scraper.py

# Deactivate
deactivate
