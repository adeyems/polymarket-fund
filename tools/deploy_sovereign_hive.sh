#!/bin/bash
# =============================================================================
# Sovereign Hive - Deploy to EC2 (ca-central-1)
# =============================================================================
# Two modes:
#   SSH:  bash tools/deploy_sovereign_hive.sh MARKET_MAKER
#   SSM:  bash tools/deploy_sovereign_hive.sh MARKET_MAKER --ssm
#   Stop: bash tools/deploy_sovereign_hive.sh MARKET_MAKER stop
# =============================================================================

set -euo pipefail

REGION="ca-central-1"
PROFILE="qudus-personal"
SSH_KEY="infra/live/prod/sovereign-hive-key"
APP_DIR="/app/sovereign-hive"
STRATEGY="${1:-MARKET_MAKER}"
ACTION="${2:-start}"

echo "=== Sovereign Hive Deploy ==="
echo "Strategy: $STRATEGY | Action: $ACTION"

# Get instance details from Terraform
cd infra/live/prod
INSTANCE_ID=$(terraform output -raw instance_id 2>/dev/null || echo "")
PUBLIC_IP=$(terraform output -raw public_ip 2>/dev/null || echo "")
cd - > /dev/null

if [ -z "$PUBLIC_IP" ]; then
    echo "ERROR: Could not get instance IP from Terraform outputs"
    exit 1
fi

echo "Target: $PUBLIC_IP ($INSTANCE_ID)"

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 ec2-user@$PUBLIC_IP"

if [ "$ACTION" = "--ssm" ]; then
    # -------------------------------------------------------------------------
    # SSM deploy (no SSH key needed)
    # -------------------------------------------------------------------------
    echo ""
    echo "[1/3] Pulling code via SSM..."
    CMD_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters commands="[\"cd $APP_DIR && sudo -u ec2-user git pull origin main 2>&1\"]" \
        --region "$REGION" --profile "$PROFILE" \
        --output text --query "Command.CommandId")
    sleep 5
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
        --region "$REGION" --profile "$PROFILE" --query "StandardOutputContent" --output text

    echo "[2/3] Installing dependencies..."
    CMD_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters commands="[\"cd $APP_DIR && sudo -u ec2-user $APP_DIR/venv/bin/pip install -r requirements.txt -q 2>&1\"]" \
        --region "$REGION" --profile "$PROFILE" \
        --output text --query "Command.CommandId")
    sleep 10
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
        --region "$REGION" --profile "$PROFILE" --query "StandardOutputContent" --output text

    echo "[3/3] Restarting service..."
    CMD_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters commands="[\"sudo systemctl restart sovereign-hive@${STRATEGY} && sleep 2 && sudo systemctl status sovereign-hive@${STRATEGY} --no-pager\"]" \
        --region "$REGION" --profile "$PROFILE" \
        --output text --query "Command.CommandId")
    sleep 5
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
        --region "$REGION" --profile "$PROFILE" --query "StandardOutputContent" --output text

elif [ "$ACTION" = "stop" ]; then
    # -------------------------------------------------------------------------
    # Stop strategy
    # -------------------------------------------------------------------------
    echo ""
    echo "Stopping sovereign-hive@${STRATEGY}..."
    $SSH_CMD "sudo systemctl stop sovereign-hive@${STRATEGY} && echo 'Stopped'"

else
    # -------------------------------------------------------------------------
    # SSH deploy (default)
    # -------------------------------------------------------------------------
    echo ""
    echo "[1/3] Pulling code..."
    $SSH_CMD "cd $APP_DIR && git pull origin main 2>&1"

    echo "[2/3] Installing dependencies..."
    $SSH_CMD "cd $APP_DIR && $APP_DIR/venv/bin/pip install -q -r requirements.txt 2>&1"

    echo "[3/4] Restarting service..."
    $SSH_CMD "
        sudo cp $APP_DIR/tools/sovereign-hive@.service /etc/systemd/system/ 2>/dev/null || true
        sudo systemctl daemon-reload
        sudo systemctl enable sovereign-hive@${STRATEGY}
        sudo systemctl restart sovereign-hive@${STRATEGY}
        sleep 2
        sudo systemctl status sovereign-hive@${STRATEGY} --no-pager | head -5
    "

    # -------------------------------------------------------------------------
    # Post-deploy health check: wait for first scan, check for errors
    # -------------------------------------------------------------------------
    echo ""
    echo "[4/4] Verifying deployment (waiting 45s for first scan)..."
    sleep 45

    HEALTH_OK=true

    # Check service is still running (didn't crash on startup)
    SERVICE_STATUS=$($SSH_CMD "sudo systemctl is-active sovereign-hive@${STRATEGY} 2>/dev/null" || echo "failed")
    if [ "$SERVICE_STATUS" != "active" ]; then
        echo "HEALTH CHECK FAILED: Service is $SERVICE_STATUS (not active)"
        echo "Recent logs:"
        $SSH_CMD "sudo journalctl -u sovereign-hive@${STRATEGY} --no-pager -n 20" || true
        HEALTH_OK=false
    fi

    # Check for import errors, tracebacks, or Gemini failures in recent logs
    ERRORS=$($SSH_CMD "tail -100 /var/log/sovereign-hive/${STRATEGY}.log 2>/dev/null | grep -ciE 'ImportError|ModuleNotFoundError|NameError|SyntaxError|FALLBACK MODE|Traceback'" || echo "0")
    if [ "$ERRORS" -gt 0 ]; then
        echo "HEALTH CHECK WARNING: Found $ERRORS error indicators in recent logs"
        $SSH_CMD "tail -100 /var/log/sovereign-hive/${STRATEGY}.log 2>/dev/null | grep -iE 'ImportError|ModuleNotFoundError|NameError|SyntaxError|FALLBACK MODE|Traceback'" || true
        HEALTH_OK=false
    fi

    # Check that a scan cycle completed
    SCAN_OK=$($SSH_CMD "tail -50 /var/log/sovereign-hive/${STRATEGY}.log 2>/dev/null | grep -c 'CYCLE'" || echo "0")
    if [ "$SCAN_OK" -eq 0 ]; then
        echo "HEALTH CHECK WARNING: No scan cycle completed in first 45s"
        HEALTH_OK=false
    fi

    if [ "$HEALTH_OK" = true ]; then
        echo "HEALTH CHECK PASSED: Service active, no errors, scan cycle running"
    else
        echo ""
        echo "*** DEPLOY SUCCEEDED BUT HEALTH CHECK FLAGGED ISSUES ***"
        echo "*** Review the warnings above before walking away ***"
    fi
fi

echo ""
echo "=== Deploy Complete ==="
echo "Monitor: $SSH_CMD 'tail -f /var/log/sovereign-hive/${STRATEGY}.log'"
echo "Status:  $SSH_CMD 'sudo systemctl status sovereign-hive@${STRATEGY}'"
