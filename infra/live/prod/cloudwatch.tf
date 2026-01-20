# =============================================================================
# QuesQuant HFT - CloudWatch Dashboard
# =============================================================================

resource "aws_cloudwatch_dashboard" "hft" {
  dashboard_name = "${var.project_name}-hft-dashboard"

  dashboard_body = file("${path.module}/../../cloudwatch/dashboard.json")
}

# -----------------------------------------------------------------------------
# CloudWatch Log Groups
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "hft_bot" {
  name              = "/quesquant/hft-bot"
  retention_in_days = 30

  tags = {
    Name        = "${var.project_name}-hft-bot-logs"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "trades" {
  name              = "/quesquant/trades"
  retention_in_days = 365

  tags = {
    Name        = "${var.project_name}-trades-logs"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "heartbeat_missing" {
  alarm_name          = "${var.project_name}-heartbeat-missing"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Heartbeat"
  namespace           = "QuesQuant/HFT"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "HFT Bot heartbeat missing - possible crash"
  treat_missing_data  = "breaching"

  dimensions = {
    Environment = var.environment
  }

  # TODO: Add SNS topic for alerts
  # alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project_name}-heartbeat-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "high_latency" {
  alarm_name          = "${var.project_name}-high-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TickToTradeLatency"
  namespace           = "QuesQuant/HFT"
  period              = 60
  statistic           = "Average"
  threshold           = 300
  alarm_description   = "Tick-to-trade latency exceeds 300ms"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Environment = var.environment
  }

  tags = {
    Name = "${var.project_name}-latency-alarm"
  }
}
