# =============================================================================
# Security Module - Outputs
# =============================================================================

output "ssh_security_group_id" {
  description = "ID of the SSH security group"
  value       = aws_security_group.ssh.id
}

output "security_group_ids" {
  description = "List of all security group IDs for EC2 attachment"
  value       = [aws_security_group.ssh.id]
}
