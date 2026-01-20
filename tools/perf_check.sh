#!/bin/bash
# QuesQuant HFT - Remote Performance Audit
# Usage: ./tools/perf_check.sh

REMOTE_IP="100.50.168.104"
SSH_KEY="infra/live/prod/quesquant-key-v2"

echo "🔍 Running Remote Performance Audit on $REMOTE_IP..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@"$REMOTE_IP" "python3 /app/hft/tools/analyze_performance.py"
