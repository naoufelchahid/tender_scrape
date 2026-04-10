#!/bin/bash
# Quick helper script to monitor container logs

echo "Results OCR Container - Log Monitor"
echo "===================================="
echo ""
echo "Press Ctrl+C to stop monitoring"
echo ""

cd /home/naoufel/projects/AO_scrape/results_ocr_container
docker compose logs -f --tail 50
