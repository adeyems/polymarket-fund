#!/bin/bash
# =============================================================================
# QuesQuant HFT - Upload Secrets to AWS Secrets Manager
# =============================================================================
# This script uploads your local .env file to AWS Secrets Manager.
# The EC2 instance will fetch these secrets at boot time.
# =============================================================================

set -euo pipefail

AWS_PROFILE="qudus-personal"
AWS_REGION="us-east-1"
ENV_FILE=".env"
SECRET_NAME="quesquant/env"

echo "================================================"
echo "QuesQuant - Upload Secrets to AWS"
echo "================================================"

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: $ENV_FILE not found"
    echo "   Create a .env file with your secrets first."
    exit 1
fi

echo "Profile: $AWS_PROFILE"
echo "Region:  $AWS_REGION"
echo "Secret:  $SECRET_NAME"
echo "Source:  $ENV_FILE"
echo ""

# Convert .env to JSON
echo "[1/2] Converting .env to JSON..."
ENV_JSON=$(cat "$ENV_FILE" | grep -v '^#' | grep -v '^$' | \
    awk -F '=' '{
        key=$1;
        $1="";
        val=substr($0,2);
        gsub(/"/, "\\\"", val);
        printf "\"%s\": \"%s\",\n", key, val
    }' | sed '$ s/,$//' | awk 'BEGIN{print "{"} {print} END{print "}"}')

echo "  ✓ JSON created"

# Check if secret exists
echo "[2/2] Uploading to Secrets Manager..."
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" 2>/dev/null; then
    # Update existing secret
    aws secretsmanager put-secret-value \
        --secret-id "$SECRET_NAME" \
        --secret-string "$ENV_JSON" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION"
    echo "  ✓ Secret updated"
else
    # Create new secret
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "QuesQuant HFT environment variables" \
        --secret-string "$ENV_JSON" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION"
    echo "  ✓ Secret created"
fi

echo ""
echo "================================================"
echo "✅ Secrets uploaded successfully!"
echo "================================================"
echo ""
echo "To verify:"
echo "  aws secretsmanager get-secret-value --secret-id $SECRET_NAME --profile $AWS_PROFILE --region $AWS_REGION"
echo ""
echo "Keys uploaded:"
echo "$ENV_JSON" | jq -r 'keys[]' 2>/dev/null || echo "(install jq to see keys)"
