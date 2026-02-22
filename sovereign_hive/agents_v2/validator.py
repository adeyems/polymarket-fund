"""
AI Validator Agent — Pre-trade validation service.

FastAPI service that receives trade proposals from the trader and returns
approve/reject decisions with reasoning. Acts as a second opinion after
the existing Gemini AI screen.

Design: Fail-open — if this service is down, trades proceed anyway.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI
from .models import ValidationRequest, ValidationResponse

app = FastAPI(title="Sovereign Hive Validator", version="1.0")

# Validation log for the alerter to read
VALIDATOR_LOG = Path(__file__).parent.parent / "data" / ".validator_log.jsonl"


def _log_validation(request: ValidationRequest, response: ValidationResponse):
    """Append validation result to log file for alerter consumption."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "condition_id": request.condition_id,
            "question": request.question[:80],
            "strategy": request.strategy,
            "amount": request.amount,
            "approved": response.approved,
            "reason": response.reason,
            "risk_flags": response.risk_flags,
        }
        with open(VALIDATOR_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let logging break validation


@app.get("/health")
def health():
    return {"status": "ok", "agent": "validator"}


@app.post("/validate", response_model=ValidationResponse)
def validate_trade(req: ValidationRequest) -> ValidationResponse:
    """Validate a proposed trade before execution."""
    risk_flags = []
    summary = req.portfolio_summary or {}

    # 1. Concentration check: >40% of portfolio in one position
    balance = summary.get("balance", 1000)
    total_value = balance + sum(
        p.get("cost_basis", 0) for p in summary.get("positions", {}).values()
    ) if isinstance(summary.get("positions"), dict) else balance
    if total_value > 0 and req.amount / total_value > 0.40:
        risk_flags.append("CONCENTRATION: Single trade >40% of portfolio")

    # 2. Duplicate position check: already holding same market
    positions = summary.get("positions", {})
    if isinstance(positions, dict) and req.condition_id in positions:
        risk_flags.append("DUPLICATE: Already hold a position on this market")

    # 3. Size sanity: position > 30% of available balance
    if balance > 0 and req.amount / balance > 0.30:
        risk_flags.append("SIZE: Trade >30% of available balance")

    # 4. Price sanity: invalid price first, then extreme price warnings
    if req.price is not None:
        if req.price <= 0 or req.price > 1.0:
            risk_flags.append("PRICE: Invalid price")
        elif req.side == "YES" and req.price > 0.95:
            risk_flags.append("PRICE: Buying YES >$0.95 (minimal upside)")
        elif req.side == "NO" and req.price > 0.95:
            risk_flags.append("PRICE: Buying NO >$0.95 (minimal upside)")

    # 5. Low confidence with large size
    if req.confidence is not None and req.confidence < 0.55 and req.amount > 100:
        risk_flags.append("CONFIDENCE: Low confidence (<0.55) with large position (>$100)")

    # Decision: reject if critical flags, approve with warnings otherwise
    critical_flags = [f for f in risk_flags if f.startswith(("DUPLICATE:", "PRICE: Invalid"))]

    if critical_flags:
        response = ValidationResponse(
            approved=False,
            reason=critical_flags[0],
            risk_flags=risk_flags,
        )
    else:
        response = ValidationResponse(
            approved=True,
            reason="Approved" + (f" with {len(risk_flags)} warnings" if risk_flags else ""),
            risk_flags=risk_flags,
        )

    _log_validation(req, response)
    return response
