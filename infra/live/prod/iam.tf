# =============================================================================
# Sovereign Hive - IAM (Secrets Manager + CloudWatch + SSM)
# =============================================================================

resource "aws_iam_role" "trading_node" {
  name = "${var.project_name}-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_instance_profile" "trading_node" {
  name = "${var.project_name}-node-profile"
  role = aws_iam_role.trading_node.name
}

# Read secrets at startup (no .env file on disk)
resource "aws_iam_role_policy" "secrets_read" {
  name = "${var.project_name}-secrets-read"
  role = aws_iam_role.trading_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.project_name}/*"
    }]
  })
}

# Push logs and metrics
resource "aws_iam_role_policy" "cloudwatch" {
  name = "${var.project_name}-cloudwatch"
  role = aws_iam_role.trading_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
        "cloudwatch:PutMetricData"
      ]
      Resource = "*"
    }]
  })
}

# SSM Session Manager (backup access without SSH)
resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.trading_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  # NOTE: Double colon is correct — AWS-managed policies use account-less ARN format
  # arn:aws:iam::aws:policy/... (no account ID, "aws" is the partition qualifier)
}
