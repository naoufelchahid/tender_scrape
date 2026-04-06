#!/bin/bash
set -euo pipefail

echo "=== Result Update ==="
echo "Querying Fuseki for tenders past deadline without results..."
cd "$(dirname "$0")"
python result_updater.py
echo "=== Done ==="
