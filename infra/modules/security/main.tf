# =============================================================================
# QuesQuant HFT - Security Module
# =============================================================================

# -----------------------------------------------------------------------------
# SSH Security Group (Restricted to Admin IP)
# -----------------------------------------------------------------------------
resource "aws_security_group" "ssh" {
  name        = "${var.project_name}-ssh-sg"
  description = "Allow SSH access from whitelisted IP"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH from Admin IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_ip_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-ssh-sg"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Dashboard Security Group — REMOVED (2026-02-25)
# Port 8002 was exposed to the internet and led to EIP-7702 wallet drain.
# Dashboard now runs locally via SSH pull. No ports needed on EC2.
# -----------------------------------------------------------------------------
