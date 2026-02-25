#!/bin/bash
# =============================================================
# DAILY STRATEGIC ANALYSIS
# Runs once daily at 8 AM UTC via launchd
# Deep analysis of all trade history, strategy performance,
# code review, and actionable recommendations.
# Uses Opus for deeper reasoning.
# =============================================================

set -euo pipefail

PROJECT_DIR="/Users/qudus-mac/PycharmProjects/polymarket-fund"
LOG_DIR="$PROJECT_DIR/sovereign_hive/logs"
ANALYSIS_LOG="$LOG_DIR/daily_analysis.log"
PROMPT_FILE="$PROJECT_DIR/tools/daily_analysis_prompt.txt"

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
LOCK_FILE="$LOG_DIR/.daily_analysis.lock"
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Daily analysis already running (PID $LOCK_PID), skipping" >> "$ANALYSIS_LOG"
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

echo "" >> "$ANALYSIS_LOG"
echo "==========================================================" >> "$ANALYSIS_LOG"
echo "DAILY ANALYSIS RUN: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$ANALYSIS_LOG"
echo "==========================================================" >> "$ANALYSIS_LOG"

cd "$PROJECT_DIR"

PROMPT=$(cat "$PROMPT_FILE")

# Use Opus for deep strategic analysis (Max subscription, no budget cap)
claude -p "$PROMPT" \
  --model opus \
  --allowedTools "Bash,Read,Write,Edit,Grep,Glob,WebFetch,WebSearch" \
  >> "$ANALYSIS_LOG" 2>&1

echo "Daily analysis complete: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$ANALYSIS_LOG"
