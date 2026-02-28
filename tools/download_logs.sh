#!/bin/bash
# =============================================================================
# Download EC2 Logs Before Stopping Instance
# =============================================================================
# Usage:
#   bash tools/download_logs.sh              # Download all logs
#   bash tools/download_logs.sh --tail 500   # Download last 500 lines only
# =============================================================================
set -euo pipefail

REGION="ca-central-1"
SSH_KEY="infra/live/prod/sovereign-hive-key"
LOG_DIR="sovereign_hive/logs/ec2_archive"
TAIL_LINES="${2:-0}"  # 0 = full download

# Get IP from Terraform
cd infra/live/prod
PUBLIC_IP=$(terraform output -raw public_ip 2>/dev/null || echo "")
cd - > /dev/null

if [ -z "$PUBLIC_IP" ]; then
    echo "ERROR: Could not get instance IP. Is EC2 running?"
    exit 1
fi

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 ec2-user@$PUBLIC_IP"

# Create local archive directory with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_DIR="${LOG_DIR}/${TIMESTAMP}"
mkdir -p "$ARCHIVE_DIR"

echo "=== Downloading EC2 Logs ==="
echo "Target: $PUBLIC_IP"
echo "Archive: $ARCHIVE_DIR"
echo ""

# 1. Bot logs
echo "[1/4] Bot logs..."
if [ "$1" = "--tail" ] 2>/dev/null && [ "$TAIL_LINES" -gt 0 ] 2>/dev/null; then
    $SSH_CMD "tail -$TAIL_LINES /var/log/sovereign-hive/MARKET_MAKER.log 2>/dev/null || echo 'No log'" > "$ARCHIVE_DIR/MARKET_MAKER.log"
else
    scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "ec2-user@$PUBLIC_IP:/var/log/sovereign-hive/MARKET_MAKER.log" "$ARCHIVE_DIR/" 2>/dev/null || echo "  No bot log found"
fi

# 2. Portfolio state
echo "[2/4] Portfolio data..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "ec2-user@$PUBLIC_IP:/app/sovereign-hive/sovereign_hive/data/portfolio_market_maker.json" "$ARCHIVE_DIR/" 2>/dev/null || echo "  No portfolio file"

# 3. System journal (last 1000 lines of the service)
echo "[3/4] Systemd journal..."
$SSH_CMD "sudo journalctl -u sovereign-hive@MARKET_MAKER --no-pager -n 1000 2>/dev/null" > "$ARCHIVE_DIR/systemd_journal.log" 2>/dev/null || echo "  No journal"

# 4. Wallet audit snapshot
echo "[4/4] Wallet audit..."
$SSH_CMD "source /run/sovereign-hive/env 2>/dev/null && cd /app/sovereign-hive && python3 tools/wallet_audit.py 2>/dev/null" > "$ARCHIVE_DIR/wallet_audit.json" 2>/dev/null || echo "  Audit failed (secrets may not be loaded)"

# Summary
echo ""
echo "=== Download Complete ==="
echo "Files:"
ls -lh "$ARCHIVE_DIR/"
echo ""
echo "To read: cat $ARCHIVE_DIR/MARKET_MAKER.log | tail -100"

# Create a summary file for the agent
LINES=$(wc -l < "$ARCHIVE_DIR/MARKET_MAKER.log" 2>/dev/null || echo "0")
echo "{\"timestamp\": \"$TIMESTAMP\", \"log_lines\": $LINES, \"archive_dir\": \"$ARCHIVE_DIR\"}" > "$ARCHIVE_DIR/meta.json"
