# =============================================================================
# Sovereign Hive - Main Configuration (ca-central-1, lean)
# =============================================================================
# Public subnet, no NAT Gateway, locked-down security group.
# Cost: ~$12/month (t4g.small) + ~$4 (EIP + CloudWatch) = ~$16/month
# =============================================================================

# -----------------------------------------------------------------------------
# AMI
# -----------------------------------------------------------------------------
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
# VPC (minimal — 1 public subnet, no NAT)
# -----------------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project_name}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# -----------------------------------------------------------------------------
# Security Group — ZERO inbound except SSH from admin IP
# -----------------------------------------------------------------------------
resource "aws_security_group" "trading_node" {
  name_prefix = "${var.project_name}-node-"
  description = "Trading node: SSH from admin only, all outbound"
  vpc_id      = aws_vpc.main.id

  # SSH from admin IP only
  ingress {
    description = "SSH from admin"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_ip_cidr]
  }

  # All outbound (CLOB API, Polygon RPC, package repos)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-sg" }

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# EC2 Instance
# -----------------------------------------------------------------------------
resource "aws_instance" "trading_node" {
  ami                    = data.aws_ami.amazon_linux_arm.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.trading_node.id]
  iam_instance_profile   = aws_iam_instance_profile.trading_node.name

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  monitoring = true

  user_data = filebase64("${path.module}/../../../tools/user_data_v2.sh")

  tags = {
    Name = "${var.project_name}-trading-node"
  }
}

# Elastic IP
resource "aws_eip" "trading_node" {
  instance = aws_instance.trading_node.id
  domain   = "vpc"

  tags = { Name = "${var.project_name}-eip" }
}
