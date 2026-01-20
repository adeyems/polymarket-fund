#!/bin/bash
# =============================================================================
# QuesQuant HFT - Day 2 Deployment Script
# =============================================================================
# Usage: ./tools/deploy_code.sh

set -e

REMOTE_IP="100.50.168.104"
SSH_KEY="infra/live/prod/quesquant-key.pem"
APP_DIR="/app/hft"

echo "🚀 Starting Deployment to $REMOTE_IP..."

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@"$REMOTE_IP" "
    echo '--- Pulling Latest Code ---'
    cd $APP_DIR && git pull origin main
    
    echo '--- Installing Dependencies ---'
    $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt
    
    echo '--- Restarting Service ---'
    sudo systemctl restart hft-bot
    
    echo '--- Verifying Status ---'
    sudo systemctl status hft-bot --no-pager | grep Active
"

echo "✅ Deployment Complete in < 10 seconds."
