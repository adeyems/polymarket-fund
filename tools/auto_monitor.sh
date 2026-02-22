#!/bin/bash
# =============================================================
# AUTONOMOUS CLAUDE MONITOR
# Runs every 30 minutes via launchd to:
#   1. Load memory from previous runs
#   2. Check all running simulations
#   3. Diagnose and fix issues
#   4. Pause/resume/restart strategies
#   5. Update state + journal
#   6. Send Discord status report
# =============================================================

set -euo pipefail

PROJECT_DIR="/Users/qudus-mac/PycharmProjects/polymarket-fund"
LOG_DIR="$PROJECT_DIR/sovereign_hive/logs"
MONITOR_LOG="$LOG_DIR/auto_monitor.log"
PROMPT_FILE="$PROJECT_DIR/tools/monitor_prompt.txt"

# Load environment variables (Discord webhook, API keys, etc.)
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Prevent overlapping runs
LOCK_FILE="$LOG_DIR/.auto_monitor.lock"
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Monitor already running (PID $LOCK_PID), skipping" >> "$MONITOR_LOG"
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Timestamp
echo "" >> "$MONITOR_LOG"
echo "========================================" >> "$MONITOR_LOG"
echo "AUTO MONITOR RUN: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$MONITOR_LOG"
echo "========================================" >> "$MONITOR_LOG"

cd "$PROJECT_DIR"

# Read the prompt from file
PROMPT=$(cat "$PROMPT_FILE")

# Run Claude Code in headless mode
# --model opus: full reasoning power for diagnosis + fixes
claude -p "$PROMPT" \
  --model opus \
  --allowedTools "Bash,Read,Write,Edit,Grep,Glob" \
  >> "$MONITOR_LOG" 2>&1

echo "Monitor run complete: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$MONITOR_LOG"
