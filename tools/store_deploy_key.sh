#!/bin/bash
# =============================================================================
# QuesQuant HFT - Deploy Key Vaulting
# =============================================================================
# Usage: ./tools/store_deploy_key.sh

set -e

SECRET_ID="prod/polymarket/deploy-key"
KEY_FILE="tools/deploy_key"
REGION="us-east-1"
PROFILE="qudus-personal"

if [ ! -f "$KEY_FILE" ]; then
    echo "Error: $KEY_FILE not found. Run keygen first."
    exit 1
fi

echo "Storing Deploy Key in Secrets Manager: $SECRET_ID..."

# Check if secret already exists
if aws secretsmanager describe-secret --secret-id "$SECRET_ID" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1; then
    echo "Secret exists. Updating..."
    aws secretsmanager put-secret-value \
        --secret-id "$SECRET_ID" \
        --secret-string "{\"private_key\":\"$(cat $KEY_FILE | base64)\"}" \
        --profile "$PROFILE" \
        --region "$REGION"
else
    echo "Creating new secret..."
    aws secretsmanager create-secret \
        --name "$SECRET_ID" \
        --description "GitHub Deploy Key for HFT Bot" \
        --secret-string "{\"private_key\":\"$(cat $KEY_FILE | base64)\"}" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --tags Key=Project,Value=QuesQuant Key=Environment,Value=prod
fi

echo "✅ Deploy Key stored successfully."
