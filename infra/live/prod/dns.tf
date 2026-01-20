# =============================================================================
# QuesQuant HFT - DNS Configuration (Route 53)
# =============================================================================

# -----------------------------------------------------------------------------
# Route 53 Hosted Zone
# -----------------------------------------------------------------------------
# We check if we should create the zone or use an existing one
resource "aws_route53_zone" "main" {
  count = var.create_route53_zone ? 1 : 0
  name  = "quesquant.com"

  tags = {
    Name        = "${var.project_name}-hosted-zone"
    Environment = var.environment
  }
}

data "aws_route53_zone" "selected" {
  name         = "quesquant.com"
  private_zone = false
  # Depends on the creation if we are creating it
  depends_on = [aws_route53_zone.main]
}

locals {
  zone_id = var.create_route53_zone ? aws_route53_zone.main[0].zone_id : data.aws_route53_zone.selected.zone_id
}

# -----------------------------------------------------------------------------
# DNS Records
# -----------------------------------------------------------------------------

# Root A Record
resource "aws_route53_record" "root" {
  zone_id = local.zone_id
  name    = "quesquant.com"
  type    = "A"
  ttl     = "300"
  records = [aws_eip.trading_node.public_ip]
}

# WWW A Record
resource "aws_route53_record" "www" {
  zone_id = local.zone_id
  name    = "www.quesquant.com"
  type    = "A"
  ttl     = "300"
  records = [aws_eip.trading_node.public_ip]
}

# Polymarket Subdomain (Live/Prod)
resource "aws_route53_record" "polymarket" {
  zone_id = local.zone_id
  name    = "polymarket.quesquant.com"
  type    = "A"
  ttl     = "300"
  records = [aws_eip.trading_node.public_ip]
}

# API/Dashboard (Keeping for legacy)
resource "aws_route53_record" "api" {
  zone_id = local.zone_id
  name    = "api.quesquant.com"
  type    = "A"
  ttl     = "300"
  records = [aws_eip.trading_node.public_ip]
}
