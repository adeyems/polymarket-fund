# =============================================================================
# QuesQuant HFT - Terraform Variable Values
# =============================================================================
# IMPORTANT: Update these values before running terraform apply!
# =============================================================================

project_name = "quesquant"
environment  = "prod"
aws_region   = "us-east-1"
aws_profile  = "qudus-personal"

# Network
vpc_cidr           = "10.0.0.0/16"
public_subnet_cidr = "10.0.1.0/24"
availability_zone  = "us-east-1a"

# Security - UPDATE THESE!
admin_ip_cidr           = "81.156.74.152/32"
dashboard_allowed_cidrs = ["0.0.0.0/0"] # Restrict in production

# Compute
instance_type    = "c7g.xlarge"
key_name         = "quesquant-key" # Create this key pair in AWS Console
root_volume_size = 30
