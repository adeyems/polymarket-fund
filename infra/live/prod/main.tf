# =============================================================================
# QuesQuant HFT - Main Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

# Get latest Amazon Linux 2023 ARM64 AMI
data "aws_ami" "amazon_linux_arm" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

# -----------------------------------------------------------------------------
# Modules
# -----------------------------------------------------------------------------

module "vpc" {
  source = "../../modules/vpc"

  project_name       = var.project_name
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  public_subnet_cidr = var.public_subnet_cidr
  availability_zone  = var.availability_zone
}

module "security" {
  source = "../../modules/security"

  project_name            = var.project_name
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  admin_ip_cidr           = var.admin_ip_cidr
  dashboard_allowed_cidrs = var.dashboard_allowed_cidrs
}

# -----------------------------------------------------------------------------
# EC2 Instance (Graviton3 Trading Node)
# -----------------------------------------------------------------------------
resource "aws_instance" "trading_node" {
  ami                    = data.aws_ami.amazon_linux_arm.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = module.vpc.public_subnet_id
  vpc_security_group_ids = module.security.security_group_ids
  iam_instance_profile   = aws_iam_instance_profile.trading_node.name

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  # Enable detailed monitoring for HFT
  monitoring = true

  # User data script for initial setup (uses external script)
  user_data = filebase64("${path.module}/../../../tools/user_data.sh")

  tags = {
    Name        = "${var.project_name}-trading-node"
    Environment = var.environment
    Role        = "hft-trading"
  }

  lifecycle {
    # Prevent accidental termination
    prevent_destroy = false # Set to true for production
  }
}

# -----------------------------------------------------------------------------
# Elastic IP (Static Public IP)
# -----------------------------------------------------------------------------
resource "aws_eip" "trading_node" {
  instance = aws_instance.trading_node.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-trading-node-eip"
  }
}
