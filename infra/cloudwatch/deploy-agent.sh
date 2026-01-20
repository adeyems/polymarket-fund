#!/bin/bash
# =============================================================================
# QuesQuant HFT - Deploy CloudWatch Agent
# =============================================================================
# Run this on the EC2 instance to configure the CloudWatch Agent.
# =============================================================================

set -euo pipefail

AGENT_CONFIG="/opt/quesquant/amazon-cloudwatch-agent.json"

echo "================================================"
echo "QuesQuant CloudWatch Agent Deployment"
echo "================================================"

# 1. Install CloudWatch Agent (if not already)
if ! command -v amazon-cloudwatch-agent-ctl &> /dev/null; then
    echo "[1/3] Installing CloudWatch Agent..."
    sudo dnf install -y amazon-cloudwatch-agent
else
    echo "[1/3] CloudWatch Agent already installed ✓"
fi

# 2. Copy configuration
echo "[2/3] Copying agent configuration..."
sudo mkdir -p /opt/quesquant
sudo cp ./amazon-cloudwatch-agent.json $AGENT_CONFIG
sudo chown root:root $AGENT_CONFIG
sudo chmod 644 $AGENT_CONFIG

# 3. Start/Restart the agent
echo "[3/3] Starting CloudWatch Agent..."
sudo amazon-cloudwatch-agent-ctl -a fetch-config \
    -m ec2 \
    -c file:$AGENT_CONFIG \
    -s

# Verify
echo ""
echo "================================================"
echo "Verifying Agent Status..."
echo "================================================"
sudo amazon-cloudwatch-agent-ctl -a status

echo ""
echo "✅ CloudWatch Agent deployed successfully!"
echo "Logs will appear in: /quesquant/hft-bot"
