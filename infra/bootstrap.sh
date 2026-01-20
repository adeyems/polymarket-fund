#!/bin/bash
# =============================================================================
# QuesQuant HFT - Terraform State Bootstrap
# =============================================================================
# This script creates the S3 bucket and DynamoDB table required for
# Terraform state management. Run ONCE before `terraform init`.
# =============================================================================

set -euo pipefail

AWS_PROFILE="qudus-personal"
AWS_REGION="us-east-1"

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)

# Resource Names
BUCKET_NAME="quesquant-state-2026"
DYNAMODB_TABLE="quesquant-tfstate-lock"

echo "================================================"
echo "QuesQuant Terraform State Bootstrap"
echo "================================================"
echo "Profile: $AWS_PROFILE"
echo "Region:  $AWS_REGION"
echo "Account: $ACCOUNT_ID"
echo "Bucket:  $BUCKET_NAME"
echo "Table:   $DYNAMODB_TABLE"
echo "================================================"

# -----------------------------------------------------------------------------
# 1. Create S3 Bucket (Encrypted, Versioned)
# -----------------------------------------------------------------------------
echo "[1/4] Creating S3 Bucket..."

if aws s3api head-bucket --bucket "$BUCKET_NAME" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  ✓ Bucket already exists"
else
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" \
        --create-bucket-configuration LocationConstraint="$AWS_REGION" 2>/dev/null || \
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION"
    echo "  ✓ Bucket created"
fi

# -----------------------------------------------------------------------------
# 2. Enable Versioning
# -----------------------------------------------------------------------------
echo "[2/4] Enabling Versioning..."
aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --profile "$AWS_PROFILE" \
    --versioning-configuration Status=Enabled
echo "  ✓ Versioning enabled"

# -----------------------------------------------------------------------------
# 3. Enable Server-Side Encryption (AES-256)
# -----------------------------------------------------------------------------
echo "[3/4] Enabling Encryption..."
aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --profile "$AWS_PROFILE" \
    --server-side-encryption-configuration '{
        "Rules": [{
            "ApplyServerSideEncryptionByDefault": {
                "SSEAlgorithm": "AES256"
            },
            "BucketKeyEnabled": true
        }]
    }'
echo "  ✓ Encryption enabled (AES-256)"

# -----------------------------------------------------------------------------
# 4. Create DynamoDB Table for State Locking
# -----------------------------------------------------------------------------
echo "[4/4] Creating DynamoDB Lock Table..."

if aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" --profile "$AWS_PROFILE" --region "$AWS_REGION" 2>/dev/null; then
    echo "  ✓ Table already exists"
else
    aws dynamodb create-table \
        --table-name "$DYNAMODB_TABLE" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION"
    echo "  ✓ Table created"
    
    # Wait for table to be active
    echo "  Waiting for table to be active..."
    aws dynamodb wait table-exists \
        --table-name "$DYNAMODB_TABLE" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION"
    echo "  ✓ Table ready"
fi

# -----------------------------------------------------------------------------
# Output Backend Config
# -----------------------------------------------------------------------------
echo ""
echo "================================================"
echo "✅ Bootstrap Complete!"
echo "================================================"
echo ""
echo "Add this to your backend.tf:"
echo ""
echo "terraform {"
echo "  backend \"s3\" {"
echo "    bucket         = \"$BUCKET_NAME\""
echo "    key            = \"live/prod/terraform.tfstate\""
echo "    region         = \"$AWS_REGION\""
echo "    dynamodb_table = \"$DYNAMODB_TABLE\""
echo "    encrypt        = true"
echo "    profile        = \"$AWS_PROFILE\""
echo "  }"
echo "}"
echo ""
