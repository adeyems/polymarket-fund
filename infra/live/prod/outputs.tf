# =============================================================================
# Sovereign Hive - Outputs
# =============================================================================

output "instance_id" {
  value = aws_instance.trading_node.id
}

output "public_ip" {
  value = aws_eip.trading_node.public_ip
}

output "ssh_command" {
  value = "ssh -i infra/live/prod/sovereign-hive-key ec2-user@${aws_eip.trading_node.public_ip}"
}
