#!/bin/bash

# Check if user wants filtered mode
if [ "$1" == "--filtered" ]; then
    echo "Showing filtered logs (Processing, Progress, Errors only)..."
    docker logs -f ocr-container 2>&1 | grep --line-buffered -E "Processing|Starting parallel|Completed|Successfully|ERROR"
else
    echo "Showing all logs... (Use --filtered for cleaner output)"
    docker logs -f ocr-container
fi
