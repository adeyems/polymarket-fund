# =============================================================================
# Sovereign Hive - Backend Configuration (S3 + DynamoDB)
# =============================================================================
# Run bootstrap.sh FIRST to create these resources, then terraform init.
# =============================================================================

terraform {
  backend "s3" {
    bucket         = "sovereign-hive-state-2026"
    key            = "live/prod/terraform.tfstate"
    region         = "ca-central-1"
    dynamodb_table = "sovereign-hive-tfstate-lock"
    encrypt        = true
    profile        = "qudus-personal"
  }
}
