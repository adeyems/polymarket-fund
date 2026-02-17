# =============================================================================
# Sovereign Hive - Variables
# =============================================================================

variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
  default     = "sovereign-hive"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "ca-central-1"
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
  default     = "ca-central-1a"
}

# -----------------------------------------------------------------------------
# Security
# -----------------------------------------------------------------------------
variable "admin_ip_cidr" {
  description = "Your IP address in CIDR format for SSH access"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Compute
# -----------------------------------------------------------------------------
variable "instance_type" {
  description = "EC2 instance type (Graviton3)"
  type        = string
  default     = "c7g.medium"
}

variable "key_name" {
  description = "Name of the SSH key pair"
  type        = string
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
  default     = 20
}
