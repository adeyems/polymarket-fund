#!/bin/bash
# =============================================================================
# Sovereign Hive - EC2 Bootstrap (v2 — Secrets Manager, no .env on disk)
# =============================================================================

set -euxo pipefail
exec > >(tee /var/log/user-data.log) 2>&1

echo "=== Sovereign Hive Bootstrap ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

APP_DIR="/app/sovereign-hive"
APP_USER="ec2-user"
REPO_URL="git@github.com:adeyems/polymarket-fund.git"
SECRET_NAME="sovereign-hive/deploy-key"
AWS_REGION="ca-central-1"

# -----------------------------------------------------------------------------
# 1. System packages
# -----------------------------------------------------------------------------
echo "[1/7] Installing packages..."
dnf update -y
dnf install -y python3.11 python3.11-pip python3.11-devel git gcc jq

# -----------------------------------------------------------------------------
# 2. Application directory
# -----------------------------------------------------------------------------
echo "[2/7] Creating directories..."
mkdir -p $APP_DIR /var/log/sovereign-hive
chown -R $APP_USER:$APP_USER $APP_DIR /var/log/sovereign-hive

# -----------------------------------------------------------------------------
# 3. Deploy key from Secrets Manager
# -----------------------------------------------------------------------------
echo "[3/7] Fetching deploy key..."
SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'SecretString' \
    --output text 2>/dev/null || echo "{}")

if [ "$SECRET_JSON" != "{}" ]; then
    PRIVATE_KEY=$(echo "$SECRET_JSON" | jq -r '.private_key' | base64 -d)
    mkdir -p /home/$APP_USER/.ssh
    echo "$PRIVATE_KEY" > /home/$APP_USER/.ssh/deploy_key
    chmod 600 /home/$APP_USER/.ssh/deploy_key
    chown -R $APP_USER:$APP_USER /home/$APP_USER/.ssh

    cat > /home/$APP_USER/.ssh/config << 'SSHCONFIG'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/deploy_key
    StrictHostKeyChecking no
SSHCONFIG
    chmod 600 /home/$APP_USER/.ssh/config
    chown $APP_USER:$APP_USER /home/$APP_USER/.ssh/config
    echo "  Deploy key configured"
else
    echo "  WARNING: No deploy key found, using HTTPS clone"
fi

# -----------------------------------------------------------------------------
# 4. Clone repository
# -----------------------------------------------------------------------------
echo "[4/7] Cloning repository..."
sudo -u $APP_USER git clone $REPO_URL $APP_DIR 2>/dev/null || {
    echo "  Git clone failed, trying pull..."
    cd $APP_DIR && sudo -u $APP_USER git pull origin main
}

# -----------------------------------------------------------------------------
# 5. Python virtual environment
# -----------------------------------------------------------------------------
echo "[5/7] Setting up Python venv..."
python3.11 -m venv $APP_DIR/venv
chown -R $APP_USER:$APP_USER $APP_DIR/venv

if [ -f "$APP_DIR/requirements.txt" ]; then
    sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip -q
    sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt -q
    echo "  Dependencies installed"
fi

# -----------------------------------------------------------------------------
# 6. Secrets loader script (reads from Secrets Manager at startup)
# -----------------------------------------------------------------------------
echo "[6/7] Installing secrets loader..."
cat > $APP_DIR/load_secrets.sh << 'LOADER'
#!/bin/bash
# Load secrets from AWS Secrets Manager into environment variables
# Called by systemd ExecStartPre

REGION="ca-central-1"
SECRET_ID="sovereign-hive/env"
ENV_FILE="/run/sovereign-hive/env"

mkdir -p /run/sovereign-hive
chmod 700 /run/sovereign-hive

SECRET=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ID" \
    --region "$REGION" \
    --query 'SecretString' \
    --output text 2>/dev/null)

if [ -n "$SECRET" ]; then
    echo "$SECRET" | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    chown ec2-user:ec2-user "$ENV_FILE"
    echo "[SECRETS] Loaded to $ENV_FILE"
else
    echo "[SECRETS] ERROR: Could not load secrets"
    exit 1
fi
LOADER
chmod +x $APP_DIR/load_secrets.sh

# -----------------------------------------------------------------------------
# 7. Systemd service template
# -----------------------------------------------------------------------------
echo "[7/7] Installing systemd service..."
cat > /etc/systemd/system/sovereign-hive@.service << 'SYSTEMD'
[Unit]
Description=Sovereign Hive Strategy: %i
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/app/sovereign-hive
Environment="PATH=/app/sovereign-hive/venv/bin:/usr/local/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
Environment="STRATEGY_FILTER=%i"

# Load secrets from Secrets Manager (in-memory only, not on disk)
ExecStartPre=/app/sovereign-hive/load_secrets.sh
EnvironmentFile=/run/sovereign-hive/env

ExecStart=/app/sovereign-hive/venv/bin/python3 sovereign_hive/run_simulation.py --live
Restart=always
RestartSec=30

StandardOutput=append:/var/log/sovereign-hive/%i.log
StandardError=append:/var/log/sovereign-hive/%i_error.log

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/log/sovereign-hive /app/sovereign-hive /tmp /run/sovereign-hive

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload

echo "=== Bootstrap Complete ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Start with: systemctl start sovereign-hive@MARKET_MAKER"
