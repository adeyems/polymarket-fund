# =============================================================================
# QuesQuant HFT - IAM Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# IAM Role for EC2 Instance
# -----------------------------------------------------------------------------
resource "aws_iam_role" "trading_node" {
  name = "${var.project_name}-trading-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-trading-node-role"
  }
}

# -----------------------------------------------------------------------------
# Policy: Read from Secrets Manager
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "secrets_access" {
  name = "${var.project_name}-secrets-access"
  role = aws_iam_role.trading_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.project_name}/*",
          "arn:aws:secretsmanager:${var.aws_region}:*:secret:prod/polymarket/*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Policy: Write to CloudWatch Logs
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "cloudwatch_logs" {
  name = "${var.project_name}-cloudwatch-logs"
  role = aws_iam_role.trading_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:*:log-group:${var.project_name}/*",
          "arn:aws:logs:${var.aws_region}:*:log-group:/${var.project_name}/*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Policy: Write to CloudWatch Metrics
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "cloudwatch_metrics" {
  name = "${var.project_name}-cloudwatch-metrics"
  role = aws_iam_role.trading_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Policy: SSM for Session Manager (Optional but recommended)
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.trading_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# -----------------------------------------------------------------------------
# Instance Profile
# -----------------------------------------------------------------------------
resource "aws_iam_instance_profile" "trading_node" {
  name = "${var.project_name}-trading-node-profile"
  role = aws_iam_role.trading_node.name
}
