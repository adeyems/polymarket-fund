# =============================================================================
# Sovereign Hive - Variable Values (ca-central-1 Montreal)
# =============================================================================

project_name = "sovereign-hive"
environment  = "prod"
aws_region   = "ca-central-1"
aws_profile  = "qudus-personal"

# Network
vpc_cidr           = "10.0.0.0/16"
public_subnet_cidr = "10.0.1.0/24"
availability_zone  = "ca-central-1a"

# Security — SSH from admin IP only, NO public APIs
admin_ip_cidr = "81.156.74.152/32"

# Compute — Graviton3, network-enhanced, lean
instance_type    = "t4g.small"
key_name         = "sovereign-hive-key"
root_volume_size = 30
