# =============================================================================
# Security Module - Variables
# =============================================================================

variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "admin_ip_cidr" {
  description = "CIDR block for SSH access (e.g., your IP/32)"
  type        = string
}

variable "dashboard_allowed_cidrs" {
  description = "CIDR blocks allowed to access the Dashboard API"
  type        = list(string)
  default     = ["0.0.0.0/0"] # Override in prod to restrict
}
