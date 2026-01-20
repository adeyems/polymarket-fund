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
APP_DIR="/opt/quesquant"
APP_USER="ec2-user"
REPO_URL="git@github.com:YOUR_ORG/polymarket-fund.git"  # UPDATE THIS
SECRET_NAME="quesquant/deploy-key"
ENV_SECRET_NAME="quesquant/env"
AWS_REGION="us-east-1"

# -----------------------------------------------------------------------------
# 1. System Update & Core Dependencies
# -----------------------------------------------------------------------------
echo "[1/7] Updating system..."
dnf update -y

echo "[1/7] Installing core packages..."
dnf install -y \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    git \
    gcc \
    jq \
    aws-cli

# Set Python 3.11 as default
alternatives --set python3 /usr/bin/python3.11

# -----------------------------------------------------------------------------
# 2. Install CloudWatch Agent
# -----------------------------------------------------------------------------
echo "[2/7] Installing CloudWatch Agent..."
dnf install -y amazon-cloudwatch-agent

# -----------------------------------------------------------------------------
# 3. Create Application Directory
# -----------------------------------------------------------------------------
echo "[3/7] Creating application directory..."
mkdir -p $APP_DIR
mkdir -p /var/log/quesquant
chown -R $APP_USER:$APP_USER $APP_DIR /var/log/quesquant

# -----------------------------------------------------------------------------
# 4. Fetch Deploy Key from Secrets Manager
# -----------------------------------------------------------------------------
echo "[4/7] Fetching deploy key from Secrets Manager..."
DEPLOY_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'SecretString' \
    --output text 2>/dev/null || echo "")

if [ -n "$DEPLOY_KEY" ]; then
    # Setup SSH for git
    mkdir -p /home/$APP_USER/.ssh
    echo "$DEPLOY_KEY" > /home/$APP_USER/.ssh/deploy_key
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
    
    echo "  ✓ Deploy key configured"
else
    echo "  ⚠ No deploy key found, skipping git clone"
fi

# -----------------------------------------------------------------------------
# 5. Clone Repository
# -----------------------------------------------------------------------------
echo "[5/7] Cloning repository..."
if [ -n "$DEPLOY_KEY" ]; then
    sudo -u $APP_USER git clone $REPO_URL $APP_DIR/app || {
        echo "  ⚠ Git clone failed, may already exist"
        cd $APP_DIR/app && sudo -u $APP_USER git pull origin main || true
    }
else
    echo "  ⚠ Skipping clone (no deploy key)"
fi

# -----------------------------------------------------------------------------
# 6. Fetch Environment Variables from Secrets Manager
# -----------------------------------------------------------------------------
echo "[6/7] Fetching environment variables..."
ENV_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$ENV_SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'SecretString' \
    --output text 2>/dev/null || echo "{}")

if [ "$ENV_JSON" != "{}" ]; then
    # Convert JSON to .env format
    echo "$ENV_JSON" | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' > $APP_DIR/app/.env
    chmod 600 $APP_DIR/app/.env
    chown $APP_USER:$APP_USER $APP_DIR/app/.env
    echo "  ✓ Environment variables configured"
else
    echo "  ⚠ No environment secrets found"
fi

# -----------------------------------------------------------------------------
# 7. Install Python Dependencies
# -----------------------------------------------------------------------------
echo "[7/7] Installing Python dependencies..."
if [ -f "$APP_DIR/app/requirements.txt" ]; then
    sudo -u $APP_USER pip3.11 install --user -r $APP_DIR/app/requirements.txt
    echo "  ✓ Dependencies installed"
else
    echo "  ⚠ No requirements.txt found"
fi

# -----------------------------------------------------------------------------
# 8. Configure CloudWatch Agent
# -----------------------------------------------------------------------------
echo "[8/8] Configuring CloudWatch Agent..."
if [ -f "$APP_DIR/app/infra/cloudwatch/amazon-cloudwatch-agent.json" ]; then
    cp $APP_DIR/app/infra/cloudwatch/amazon-cloudwatch-agent.json /opt/aws/amazon-cloudwatch-agent/etc/
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
cat > /etc/systemd/system/quesquant-hft.service << 'SYSTEMD'
[Unit]
Description=QuesQuant HFT Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/opt/quesquant/app
Environment="PATH=/home/ec2-user/.local/bin:/usr/local/bin:/usr/bin"
ExecStart=/usr/bin/python3.11 -m hypercorn dashboard.api_bridge:app --bind 0.0.0.0:8002
Restart=always
RestartSec=10
StandardOutput=append:/var/log/quesquant/hft_bot.log
StandardError=append:/var/log/quesquant/hft_bot_error.log

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/log/quesquant /opt/quesquant

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable quesquant-hft
systemctl start quesquant-hft

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo ""
echo "=============================================="
echo "QuesQuant HFT - Bootstrap Complete!"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
echo ""
echo "Service Status:"
systemctl status quesquant-hft --no-pager || true
echo ""
echo "Health Check: curl http://localhost:8002/health"
