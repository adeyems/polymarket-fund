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
# Dashboard API Security Group (Port 8002)
# -----------------------------------------------------------------------------
resource "aws_security_group" "dashboard" {
  name        = "${var.project_name}-dashboard-sg"
  description = "Allow Dashboard API access"
  vpc_id      = var.vpc_id

  ingress {
    description = "Dashboard API"
    from_port   = 8002
    to_port     = 8002
    protocol    = "tcp"
    cidr_blocks = var.dashboard_allowed_cidrs
  }

  # WebSocket upgrade uses same port
  ingress {
    description = "HTTPS for Dashboard"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.dashboard_allowed_cidrs
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-dashboard-sg"
    Environment = var.environment
  }
}
