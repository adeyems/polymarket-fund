#!/bin/bash
# =============================================================================
# QuesQuant HFT - EC2 User Data Bootstrap Script
# =============================================================================
# This script runs ONCE on first boot of the EC2 instance.
# It installs dependencies, fetches secrets, and starts the trading bot.
# =============================================================================

set -euxo pipefail
exec > >(tee /var/log/user-data.log) 2>&1

echo "=============================================="
echo "QuesQuant HFT - Bootstrap Starting"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
APP_DIR="/app/hft"
APP_USER="ec2-user"
REPO_URL="git@github.com:adeyems/polymarket-fund.git"
SECRET_NAME="prod/polymarket/deploy-key"
ENV_SECRET_NAME="quesquant/env"
AWS_REGION="us-east-1"

# -----------------------------------------------------------------------------
# 1. System Update & Core Dependencies
# -----------------------------------------------------------------------------
echo "[1/9] Updating system..."
dnf update -y

echo "[1/9] Installing core packages..."
dnf install -y \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    git \
    gcc \
    jq \
    aws-cli

# -----------------------------------------------------------------------------
# 2. Install CloudWatch Agent
# -----------------------------------------------------------------------------
echo "[2/9] Installing CloudWatch Agent..."
dnf install -y amazon-cloudwatch-agent

# -----------------------------------------------------------------------------
# 3. Create Application Directory
# -----------------------------------------------------------------------------
echo "[3/9] Creating application directory..."
mkdir -p $APP_DIR
mkdir -p /var/log/quesquant
chown -R $APP_USER:$APP_USER $APP_DIR /var/log/quesquant

# -----------------------------------------------------------------------------
# 4. Fetch Deploy Key from Secrets Manager
# -----------------------------------------------------------------------------
echo "[4/9] Fetching deploy key from Secrets Manager..."
SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'SecretString' \
    --output text)

PRIVATE_KEY=$(echo "$SECRET_JSON" | jq -r '.private_key' | base64 -d)

if [ -n "$PRIVATE_KEY" ]; then
    # Setup SSH for git
    mkdir -p /home/$APP_USER/.ssh
    echo "$PRIVATE_KEY" > /home/$APP_USER/.ssh/deploy_key
    chmod 600 /home/$APP_USER/.ssh/deploy_key
    chown -R $APP_USER:$APP_USER /home/$APP_USER/.ssh
    
    # Configure SSH to use deploy key
    cat > /home/$APP_USER/.ssh/config << 'SSHCONFIG'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/deploy_key
    StrictHostKeyChecking no
SSHCONFIG
    chmod 600 /home/$APP_USER/.ssh/config
    chown $APP_USER:$APP_USER /home/$APP_USER/.ssh/config
    
    echo "  ✓ Deploy key configured"
else
    echo "  ❌ Failed to retrieve deploy key"
    exit 1
fi

# -----------------------------------------------------------------------------
# 5. Clone Repository
# -----------------------------------------------------------------------------
echo "[5/9] Cloning repository..."
sudo -u $APP_USER git clone $REPO_URL $APP_DIR || {
    echo "  ⚠ Git clone failed, attempting pull..."
    cd $APP_DIR && sudo -u $APP_USER git pull origin main
}

# -----------------------------------------------------------------------------
# 6. Fetch Environment Variables from Secrets Manager
# -----------------------------------------------------------------------------
echo "[6/9] Fetching environment variables..."
ENV_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$ENV_SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'SecretString' \
    --output text 2>/dev/null || echo "{}")

if [ "$ENV_JSON" != "{}" ]; then
    # Convert JSON to .env format
    echo "$ENV_JSON" | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' > $APP_DIR/.env
    chmod 600 $APP_DIR/.env
    chown $APP_USER:$APP_USER $APP_DIR/.env
    echo "  ✓ Environment variables configured"
else
    echo "  ⚠ No environment secrets found"
fi

# -----------------------------------------------------------------------------
# 7. Install Python Dependencies (Virtual Env)
# -----------------------------------------------------------------------------
echo "[7/9] Setting up Python virtual environment..."
python3.11 -m venv $APP_DIR/venv
chown -R $APP_USER:$APP_USER $APP_DIR/venv

if [ -f "$APP_DIR/requirements.txt" ]; then
    sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip
    sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt
    echo "  ✓ Dependencies installed in venv"
else
    echo "  ⚠ No requirements.txt found"
fi

# -----------------------------------------------------------------------------
# 8. Configure CloudWatch Agent
# -----------------------------------------------------------------------------
echo "[8/9] Configuring CloudWatch Agent..."
if [ -f "$APP_DIR/infra/cloudwatch/amazon-cloudwatch-agent.json" ]; then
    cp $APP_DIR/infra/cloudwatch/amazon-cloudwatch-agent.json /opt/aws/amazon-cloudwatch-agent/etc/
    amazon-cloudwatch-agent-ctl -a fetch-config \
        -m ec2 \
        -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
        -s
    echo "  ✓ CloudWatch Agent configured"
fi

# -----------------------------------------------------------------------------
# 9. Install Systemd Service
# -----------------------------------------------------------------------------
echo "[9/9] Installing systemd service..."
cat > /etc/systemd/system/hft-bot.service << 'SYSTEMD'
[Unit]
Description=Polymarket HFT Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/app/hft
Environment="PATH=/app/hft/venv/bin:/usr/local/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/app/hft/.env
ExecStart=/app/hft/venv/bin/python3.11 -m hypercorn dashboard.api_bridge:app --bind 0.0.0.0:8002
Restart=always
RestartSec=10
StandardOutput=append:/var/log/quesquant/hft_bot.log
StandardError=append:/var/log/quesquant/hft_bot_error.log

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/log/quesquant /app/hft

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable hft-bot
systemctl start hft-bot

echo "=============================================="
echo "QuesQuant HFT - Bootstrap Complete!"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
