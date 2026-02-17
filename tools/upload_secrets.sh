#!/bin/bash
# =============================================================================
# Sovereign Hive - Upload Secrets to AWS Secrets Manager (ca-central-1)
# =============================================================================
# Reads local .env → uploads to Secrets Manager.
# Run from project root: bash tools/upload_secrets.sh
# =============================================================================

set -euo pipefail

REGION="ca-central-1"
PROFILE="qudus-personal"
SECRET_ID="sovereign-hive/env"

echo "=== Sovereign Hive - Upload Secrets ==="
echo "Region: $REGION | Secret: $SECRET_ID"

ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found in current directory"
    exit 1
fi

# Convert .env to JSON using Python (handles = signs in values correctly)
echo "[1/2] Converting .env to JSON..."
ENV_JSON=$(python3 -c "
import json, sys
result = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or 'REGENERATE' in line:
            continue
        key, _, value = line.partition('=')
        if key and value:
            result[key] = value
print(json.dumps(result))
")

echo "  Keys: $(echo "$ENV_JSON" | jq -r 'keys[]' 2>/dev/null | tr '\n' ' ' || echo '(install jq to see)')"

# Create or update secret
echo "[2/2] Uploading to Secrets Manager..."
if aws secretsmanager describe-secret --secret-id "$SECRET_ID" \
    --profile "$PROFILE" --region "$REGION" 2>/dev/null; then
    aws secretsmanager put-secret-value \
        --secret-id "$SECRET_ID" \
        --secret-string "$ENV_JSON" \
        --profile "$PROFILE" \
        --region "$REGION"
    echo "  Secret updated"
else
    aws secretsmanager create-secret \
        --name "$SECRET_ID" \
        --description "Sovereign Hive environment variables" \
        --secret-string "$ENV_JSON" \
        --profile "$PROFILE" \
        --region "$REGION"
    echo "  Secret created"
fi

# Deploy key (optional)
DEPLOY_KEY_FILE="$HOME/.ssh/sovereign-hive-deploy"
DEPLOY_SECRET_ID="sovereign-hive/deploy-key"
if [ -f "$DEPLOY_KEY_FILE" ]; then
    echo ""
    echo "Uploading deploy key..."
    ENCODED_KEY=$(base64 < "$DEPLOY_KEY_FILE")
    DEPLOY_JSON="{\"private_key\":\"$ENCODED_KEY\"}"

    if aws secretsmanager describe-secret --secret-id "$DEPLOY_SECRET_ID" \
        --profile "$PROFILE" --region "$REGION" 2>/dev/null; then
        aws secretsmanager put-secret-value \
            --secret-id "$DEPLOY_SECRET_ID" \
            --secret-string "$DEPLOY_JSON" \
            --profile "$PROFILE" \
            --region "$REGION"
    else
        aws secretsmanager create-secret \
            --name "$DEPLOY_SECRET_ID" \
            --description "GitHub deploy key for sovereign-hive repo" \
            --secret-string "$DEPLOY_JSON" \
            --profile "$PROFILE" \
            --region "$REGION"
    fi
    echo "  Deploy key uploaded"
fi

echo ""
echo "=== Upload Complete ==="
echo "Verify: aws secretsmanager get-secret-value --secret-id $SECRET_ID --region $REGION --profile $PROFILE --query SecretString --output text | jq keys"
