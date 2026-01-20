# =============================================================================
# QuesQuant HFT - Variables
# =============================================================================

variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
  default     = "quesquant"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name"
  type        = string
  default     = "qudus-personal"
}

# -----------------------------------------------------------------------------
# Network
# -----------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "availability_zone" {
  description = "Availability Zone"
  type        = string
  default     = "us-east-1a"
}

# -----------------------------------------------------------------------------
# Security
# -----------------------------------------------------------------------------
variable "admin_ip_cidr" {
  description = "Your IP address in CIDR format for SSH access (e.g., 1.2.3.4/32)"
  type        = string
  sensitive   = true
}

variable "dashboard_allowed_cidrs" {
  description = "CIDR blocks allowed to access Dashboard API"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# -----------------------------------------------------------------------------
# Compute
# -----------------------------------------------------------------------------
variable "instance_type" {
  description = "EC2 instance type (Graviton3 recommended)"
  type        = string
  default     = "c7g.xlarge"
}

variable "key_name" {
  description = "Name of the SSH key pair"
  type        = string
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
  default     = 30
}
