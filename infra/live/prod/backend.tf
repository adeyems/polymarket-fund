# =============================================================================
# QuesQuant HFT - Backend Configuration (S3 + DynamoDB)
# =============================================================================
# IMPORTANT: Run bootstrap.sh FIRST to create these resources.
# Then uncomment this block and run `terraform init`.
# =============================================================================

terraform {
  backend "s3" {
    bucket         = "quesquant-state-2026"
    key            = "live/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "quesquant-tfstate-lock"
    encrypt        = true
    profile        = "qudus-personal"
  }
}
