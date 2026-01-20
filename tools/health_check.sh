#!/bin/bash
# =============================================================================
# QuesQuant HFT - Remote Health Check
# =============================================================================
# Run this locally to verify deployment success.
# =============================================================================

set -euo pipefail

# Configuration - Update with your server IP
SERVER_IP="${1:-}"
PORT="${2:-8002}"
TIMEOUT=10
MAX_RETRIES=6
RETRY_DELAY=10

usage() {
    echo "Usage: $0 <SERVER_IP> [PORT]"
    echo ""
    echo "Examples:"
    echo "  $0 54.123.45.67"
    echo "  $0 54.123.45.67 8002"
    exit 1
}

if [ -z "$SERVER_IP" ]; then
    usage
fi

HEALTH_URL="http://${SERVER_IP}:${PORT}/health"
WS_TEST_URL="ws://${SERVER_IP}:${PORT}/api/v1/ws/stream"

echo "================================================"
echo "QuesQuant HFT - Health Check"
echo "================================================"
echo "Server:  $SERVER_IP:$PORT"
echo "URL:     $HEALTH_URL"
echo "Timeout: ${TIMEOUT}s"
echo ""

# -----------------------------------------------------------------------------
# 1. HTTP Health Check
# -----------------------------------------------------------------------------
echo "[1/4] HTTP Health Check..."
for i in $(seq 1 $MAX_RETRIES); do
    HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" --connect-timeout $TIMEOUT "$HEALTH_URL" 2>/dev/null || echo -e "\n000")
    HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
    HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n 1)
    
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  ✅ HTTP OK (200)"
        echo "  Response: $HTTP_BODY"
        break
    else
        echo "  ⏳ Attempt $i/$MAX_RETRIES - HTTP $HTTP_CODE"
        if [ $i -lt $MAX_RETRIES ]; then
            sleep $RETRY_DELAY
        fi
    fi
done

if [ "$HTTP_CODE" != "200" ]; then
    echo "  ❌ Health check FAILED after $MAX_RETRIES attempts"
    exit 1
fi

# -----------------------------------------------------------------------------
# 2. Parse Health Response
# -----------------------------------------------------------------------------
echo ""
echo "[2/4] Parsing Health Response..."
if command -v jq &> /dev/null; then
    STATUS=$(echo "$HTTP_BODY" | jq -r '.status // "unknown"')
    CONNECTIONS=$(echo "$HTTP_BODY" | jq -r '.connections // 0')
    echo "  Status:      $STATUS"
    echo "  Connections: $CONNECTIONS"
    
    if [ "$STATUS" = "ok" ]; then
        echo "  ✅ Status OK"
    else
        echo "  ⚠️  Status: $STATUS"
    fi
else
    echo "  (Install jq for detailed parsing)"
    echo "  Raw: $HTTP_BODY"
fi

# -----------------------------------------------------------------------------
# 3. Port Connectivity
# -----------------------------------------------------------------------------
echo ""
echo "[3/4] Port Connectivity..."
if nc -z -w $TIMEOUT "$SERVER_IP" "$PORT" 2>/dev/null; then
    echo "  ✅ Port $PORT is open"
else
    echo "  ⚠️  Port $PORT connectivity check failed (nc not available or port filtered)"
fi

# SSH Port (optional)
if nc -z -w $TIMEOUT "$SERVER_IP" 22 2>/dev/null; then
    echo "  ✅ SSH (22) is open"
else
    echo "  ⚠️  SSH (22) not reachable from this IP"
fi

# -----------------------------------------------------------------------------
# 4. Summary
# -----------------------------------------------------------------------------
echo ""
echo "================================================"
echo "Health Check Summary"
echo "================================================"

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ DEPLOYMENT SUCCESSFUL"
    echo ""
    echo "Dashboard: http://${SERVER_IP}:${PORT}"
    echo "API Docs:  http://${SERVER_IP}:${PORT}/docs"
    echo "WebSocket: ws://${SERVER_IP}:${PORT}/api/v1/ws/stream"
    exit 0
else
    echo "❌ DEPLOYMENT FAILED"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check instance is running: aws ec2 describe-instances"
    echo "  2. Check security group allows port $PORT"
    echo "  3. SSH and check logs: journalctl -u quesquant-hft"
    exit 1
fi
