#!/bin/bash
# =============================================================
# AUTONOMOUS CLAUDE MONITOR — REMOTE (EC2)
# Runs every 30 minutes via launchd to:
#   1. SSH into EC2 to check live trading process
#   2. Read remote logs, check health
#   3. Restart/pause strategy via systemctl
#   4. Update local state + journal
#   5. Send Discord status report
# =============================================================

set -euo pipefail

PROJECT_DIR="/Users/qudus-mac/PycharmProjects/polymarket-fund"
LOG_DIR="$PROJECT_DIR/sovereign_hive/logs"
MONITOR_LOG="$LOG_DIR/remote_monitor.log"
PROMPT_FILE="$PROJECT_DIR/tools/monitor_prompt_remote.txt"
SSH_KEY="$PROJECT_DIR/infra/live/prod/sovereign-hive-key"

# Load environment variables (Discord webhook, EC2 IP, etc.)
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

# EC2 connection details (can override via .env)
EC2_IP="${EC2_IP:-16.54.60.150}"
EC2_USER="${EC2_USER:-ec2-user}"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Prevent overlapping runs
LOCK_FILE="$LOG_DIR/.remote_monitor.lock"
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Remote monitor already running (PID $LOCK_PID), skipping" >> "$MONITOR_LOG"
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Verify SSH key exists and has correct permissions
if [ ! -f "$SSH_KEY" ]; then
  echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - ERROR: SSH key not found at $SSH_KEY" >> "$MONITOR_LOG"
  exit 1
fi

# Pre-flight: verify EC2 is reachable
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  "$EC2_USER@$EC2_IP" "echo OK" > /dev/null 2>&1; then
  echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - ERROR: Cannot reach EC2 at $EC2_IP" >> "$MONITOR_LOG"
  # Send Discord alert if webhook is set
  if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
    curl -s -H "Content-Type: application/json" \
      -d "{\"embeds\":[{\"title\":\"REMOTE MONITOR: EC2 UNREACHABLE\",\"description\":\"Cannot SSH to $EC2_IP. Instance may be stopped or network issue.\",\"color\":15158332}]}" \
      "$DISCORD_WEBHOOK_URL" > /dev/null 2>&1 || true
  fi
  exit 1
fi

# Timestamp
echo "" >> "$MONITOR_LOG"
echo "========================================" >> "$MONITOR_LOG"
echo "REMOTE MONITOR RUN: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$MONITOR_LOG"
echo "========================================" >> "$MONITOR_LOG"

cd "$PROJECT_DIR"

# Read the prompt from file
PROMPT=$(cat "$PROMPT_FILE")

# Run Claude Code in headless mode
# --model opus: full reasoning power for diagnosis
claude -p "$PROMPT" \
  --model opus \
  --allowedTools "Bash,Read,Write,Edit,Grep,Glob,WebFetch,WebSearch" \
  >> "$MONITOR_LOG" 2>&1

echo "Remote monitor run complete: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$MONITOR_LOG"
