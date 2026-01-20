# =============================================================================
# QuesQuant HFT - Outputs
# =============================================================================

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "trading_node_id" {
  description = "Instance ID of the trading node"
  value       = aws_instance.trading_node.id
}

output "trading_node_private_ip" {
  description = "Private IP of the trading node"
  value       = aws_instance.trading_node.private_ip
}

output "trading_node_public_ip" {
  description = "Elastic IP of the trading node"
  value       = aws_eip.trading_node.public_ip
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh -i ~/.ssh/${var.key_name}.pem ec2-user@${aws_eip.trading_node.public_ip}"
}

output "dashboard_url" {
  description = "Dashboard API URL"
  value       = "http://${aws_eip.trading_node.public_ip}:8002"
}

output "iam_role_arn" {
  description = "ARN of the IAM role"
  value       = aws_iam_role.trading_node.arn
}
