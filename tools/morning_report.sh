#!/bin/bash
# Morning Report Script
# Usage: ./morning_report.sh

LOG_FILE="/var/log/quesquant/hft_bot.log"
echo "============================================"
echo "      ☀️  MORNING REPORT: HFT BOT  ☀️      "
echo "============================================"
echo "Checking logs since midnight (approx)..."

# 1. Check Service Uptime
echo ""
echo "[1] Service Status:"
sudo systemctl status hft-bot | grep "Active:"

# 2. Count Market Discovery Events (How much hopping?)
echo ""
echo "[2] Market Discovery Events:"
grep "MARKET-DISCOVERY" $LOG_FILE | tail -n 5
echo "Total Discovery Events (Last 1000 lines): $(tail -n 1000 $LOG_FILE | grep -c 'MARKET-DISCOVERY')"

# 3. Count Trades
echo ""
echo "[3] Trades Executed:"
grep "TRADE_FILLED" $LOG_FILE | tail -n 5
TOTAL_TRADES=$(grep -c "TRADE_FILLED" $LOG_FILE)
echo "Total Trades since log start: $TOTAL_TRADES"

# 4. Check for Crashes/Restarts
echo ""
echo "[4] Critical Errors / Restarts:"
grep -E "Critical|Traceback|Restarting" $LOG_FILE | tail -n 5
if [ $? -ne 0 ]; then
    echo "✅ No critical errors found in tail."
fi

echo ""
echo "============================================"
echo "Report Complete."
