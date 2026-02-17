#!/bin/bash
# =============================================================================
# Sovereign Hive - Bootstrap S3 + DynamoDB for Terraform State (ca-central-1)
# =============================================================================
# Run ONCE before first `terraform init`
# =============================================================================

set -euo pipefail

BUCKET="sovereign-hive-state-2026"
TABLE="sovereign-hive-tfstate-lock"
REGION="ca-central-1"
PROFILE="qudus-personal"

echo "=== Sovereign Hive - Terraform Bootstrap ==="
echo "Region: $REGION"

# S3 bucket
echo "[1/2] Creating S3 bucket: $BUCKET"
aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" \
    --profile "$PROFILE" 2>/dev/null || echo "  Bucket already exists"

aws s3api put-bucket-versioning \
    --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled \
    --profile "$PROFILE" \
    --region "$REGION"

aws s3api put-bucket-encryption \
    --bucket "$BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}' \
    --profile "$PROFILE" \
    --region "$REGION"

echo "  Bucket ready (versioned + encrypted)"

# DynamoDB table
echo "[2/2] Creating DynamoDB table: $TABLE"
aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" \
    --profile "$PROFILE" 2>/dev/null || echo "  Table already exists"

echo ""
echo "=== Bootstrap Complete ==="
echo "Now run: cd infra/live/prod && terraform init"
