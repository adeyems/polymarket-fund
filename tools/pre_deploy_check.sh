#!/bin/bash
# =============================================================================
# Sovereign Hive - Pre-Deploy Safety Checks
# =============================================================================
# Run before deploying to live: bash tools/pre_deploy_check.sh
# Verifies everything is secure and ready.
# =============================================================================

set -uo pipefail

REGION="ca-central-1"
PROFILE="qudus-personal"
INSTANCE_ID="i-08a9ff0a3fc646e5d"
SSH_KEY="infra/live/prod/sovereign-hive-key"
EC2_USER="ec2-user"
PASS=0
FAIL=0
WARN=0

green() { echo -e "\033[32m✓ $1\033[0m"; ((PASS++)); }
red()   { echo -e "\033[31m✗ $1\033[0m"; ((FAIL++)); }
yellow(){ echo -e "\033[33m⚠ $1\033[0m"; ((WARN++)); }

echo "============================================"
echo "  SOVEREIGN HIVE — PRE-DEPLOY SAFETY CHECK"
echo "============================================"
echo ""

# ---- 1. Local .env has required keys ----
echo "--- Local Environment ---"
REQUIRED_KEYS="POLYMARKET_PRIVATE_KEY CLOB_API_KEY CLOB_SECRET CLOB_PASSPHRASE GEMINI_API_KEY DISCORD_WEBHOOK_URL"
if [ -f .env ]; then
  for key in $REQUIRED_KEYS; do
    val=$(grep "^${key}=" .env | cut -d= -f2-)
    if [ -n "$val" ]; then
      # Mask the value for display
      masked="${val:0:4}...${val: -4}"
      green "$key present ($masked)"
    else
      red "$key MISSING or empty in .env"
    fi
  done
else
  red ".env file not found"
fi

echo ""

# ---- 2. SSH key exists and permissions ----
echo "--- SSH Key ---"
if [ -f "$SSH_KEY" ]; then
  perms=$(stat -f "%Lp" "$SSH_KEY" 2>/dev/null || stat -c "%a" "$SSH_KEY" 2>/dev/null)
  if [ "$perms" = "400" ] || [ "$perms" = "600" ]; then
    green "SSH key exists with permissions $perms"
  else
    red "SSH key permissions are $perms (should be 400 or 600)"
  fi
else
  red "SSH key not found at $SSH_KEY"
fi

echo ""

# ---- 3. No secrets in git staging ----
echo "--- Git Security ---"
STAGED_SECRETS=$(git diff --cached --name-only 2>/dev/null | grep -E "\.env$|\.pem$|\.key$|private_key|rescue_funds" || true)
if [ -z "$STAGED_SECRETS" ]; then
  green "No secret files in git staging area"
else
  red "SECRET FILES STAGED IN GIT: $STAGED_SECRETS"
fi

# Check for hardcoded keys in staged changes
HARDCODED=$(git diff --cached 2>/dev/null | grep -iE "0x[a-f0-9]{64}|sk-ant-|AKIA[A-Z0-9]{16}" || true)
if [ -z "$HARDCODED" ]; then
  green "No hardcoded secrets in staged changes"
else
  red "POSSIBLE HARDCODED SECRETS in staged changes"
fi

echo ""

# ---- 4. Systemd service file is secure ----
echo "--- Systemd Service ---"
if grep -q "load_secrets.sh" tools/sovereign-hive@.service; then
  green "Service uses Secrets Manager (load_secrets.sh)"
else
  red "Service does NOT use Secrets Manager"
fi

if grep -q "/app/hft" tools/sovereign-hive@.service; then
  red "Service references stale /app/hft path"
else
  green "Service paths are correct (/app/sovereign-hive)"
fi

if grep -q "EnvironmentFile=/app/hft/.env" tools/sovereign-hive@.service; then
  red "Service reads .env from disk (INSECURE)"
else
  green "No .env-on-disk in service file"
fi

echo ""

# ---- 5. Tests pass ----
echo "--- Tests ---"
TEST_OUTPUT=$(python -m pytest tests/ -q 2>&1)
TEST_EXIT=$?
if [ $TEST_EXIT -eq 0 ]; then
  PASSED=$(echo "$TEST_OUTPUT" | tail -1)
  green "All tests pass: $PASSED"
else
  red "Tests FAILED (exit code $TEST_EXIT)"
  echo "$TEST_OUTPUT" | tail -5
fi

echo ""

# ---- 6. EC2 instance status ----
echo "--- EC2 Instance ---"
INSTANCE_STATE=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" --profile "$PROFILE" \
  --query "Reservations[0].Instances[0].State.Name" \
  --output text 2>/dev/null || echo "ERROR")

if [ "$INSTANCE_STATE" = "running" ]; then
  green "EC2 instance is running"

  # Get public IP
  PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" --profile "$PROFILE" \
    --query "Reservations[0].Instances[0].PublicIpAddress" \
    --output text 2>/dev/null || echo "UNKNOWN")
  green "Public IP: $PUBLIC_IP"

  # Test SSH connectivity
  if ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
    "$EC2_USER@$PUBLIC_IP" "echo OK" > /dev/null 2>&1; then
    green "SSH connection successful"

    # Check if load_secrets.sh exists on EC2
    if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o BatchMode=yes \
      "$EC2_USER@$PUBLIC_IP" "test -x /app/sovereign-hive/load_secrets.sh && echo YES" 2>/dev/null | grep -q YES; then
      green "load_secrets.sh exists on EC2"
    else
      yellow "load_secrets.sh not found on EC2 (will be created by bootstrap)"
    fi

    # Check systemd service on EC2
    SVC_STATUS=$(ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o BatchMode=yes \
      "$EC2_USER@$PUBLIC_IP" "sudo systemctl is-enabled sovereign-hive@MARKET_MAKER 2>/dev/null || echo disabled" 2>/dev/null)
    if [ "$SVC_STATUS" = "enabled" ]; then
      green "MARKET_MAKER service is enabled on EC2"
    else
      yellow "MARKET_MAKER service is $SVC_STATUS (will be enabled on deploy)"
    fi
  else
    red "SSH connection FAILED to $PUBLIC_IP"
  fi
elif [ "$INSTANCE_STATE" = "stopped" ]; then
  yellow "EC2 instance is STOPPED — start it before deploying"
else
  red "EC2 instance state: $INSTANCE_STATE"
fi

echo ""

# ---- 7. AWS Secrets Manager ----
echo "--- Secrets Manager ---"
SM_KEYS=$(aws secretsmanager get-secret-value \
  --secret-id "sovereign-hive/env" \
  --region "$REGION" --profile "$PROFILE" \
  --query "SecretString" --output text 2>/dev/null | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin).keys()))" 2>/dev/null || echo "ERROR")

if [ "$SM_KEYS" != "ERROR" ]; then
  green "Secrets Manager accessible"
  for key in $REQUIRED_KEYS; do
    if echo "$SM_KEYS" | grep -q "$key"; then
      green "  SM has $key"
    else
      red "  SM MISSING $key"
    fi
  done
else
  red "Cannot access Secrets Manager (check AWS profile)"
fi

echo ""

# ---- Summary ----
echo "============================================"
echo "  RESULTS: $PASS passed, $FAIL failed, $WARN warnings"
echo "============================================"

if [ $FAIL -gt 0 ]; then
  echo ""
  echo -e "\033[31mDO NOT DEPLOY — fix the $FAIL failure(s) above first.\033[0m"
  exit 1
elif [ $WARN -gt 0 ]; then
  echo ""
  echo -e "\033[33mDeploy with caution — $WARN warning(s) above.\033[0m"
  exit 0
else
  echo ""
  echo -e "\033[32mAll checks passed. Safe to deploy.\033[0m"
  exit 0
fi
