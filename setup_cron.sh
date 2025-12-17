#!/bin/bash

# Configuration
PROJECT_DIR="/home/naoufel/projects/AO"
UPDATES_SCRIPT="$PROJECT_DIR/run_updates.sh"
HEALER_SCRIPT="$PROJECT_DIR/run_healer.sh"

LOG_DIR="$PROJECT_DIR/logs_archive/cron"
mkdir -p "$LOG_DIR"

UPDATES_LOG="$LOG_DIR/run_updates.log"
HEALER_LOG="$LOG_DIR/run_healer.log"

# Check if scripts exist
if [ ! -f "$UPDATES_SCRIPT" ]; then
    echo "Error: $UPDATES_SCRIPT not found!"
    exit 1
fi

if [ ! -f "$HEALER_SCRIPT" ]; then
    echo "Error: $HEALER_SCRIPT not found!"
    exit 1
fi

# Make scripts executable
chmod +x "$UPDATES_SCRIPT"
chmod +x "$HEALER_SCRIPT"

# Define Cron Jobs
# 1. run_updates.sh every hour (at minute 0)
# 0 * * * * /path/to/script >> /path/to/log 2>&1
CRON_UPDATES="0 * * * * $UPDATES_SCRIPT >> $UPDATES_LOG 2>&1"

# 2. run_healer.sh every 3 hours
# 0 */3 * * * /path/to/script >> /path/to/log 2>&1
CRON_HEALER="0 */3 * * * $HEALER_SCRIPT >> $HEALER_LOG 2>&1"

# Backup current crontab
crontab -l > mycron_backup 2>/dev/null || true

# Check if jobs already exist to avoid duplicates
CURRENT_CRON=$(crontab -l 2>/dev/null)

if echo "$CURRENT_CRON" | grep -q "run_updates.sh"; then
    echo "run_updates.sh is already in crontab. Skipping addition."
else
    echo "Adding run_updates.sh to crontab..."
    (crontab -l 2>/dev/null; echo "$CRON_UPDATES") | crontab -
fi

if echo "$CURRENT_CRON" | grep -q "run_healer.sh"; then
    echo "run_healer.sh is already in crontab. Skipping addition."
else
    echo "Adding run_healer.sh to crontab..."
    (crontab -l 2>/dev/null; echo "$CRON_HEALER") | crontab -
fi

echo "Cron setup complete. Current crontab:"
echo "---------------------------------------------------"
crontab -l
echo "---------------------------------------------------"
