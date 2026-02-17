# =============================================================================
# Sovereign Hive - CloudWatch (Logs + Heartbeat Alarm)
# =============================================================================

resource "aws_cloudwatch_log_group" "trading" {
  name              = "/${var.project_name}/trading"
  retention_in_days = 30
}

resource "aws_cloudwatch_metric_alarm" "heartbeat_missing" {
  alarm_name          = "${var.project_name}-heartbeat-missing"
  alarm_description   = "No heartbeat from trading bot in 10 minutes"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Heartbeat"
  namespace           = var.project_name
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"
}
