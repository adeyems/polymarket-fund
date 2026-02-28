#!/usr/bin/env python3
"""
AI Position Review — Standalone script for monitor agent.

Gets Gemini's opinion on every open position. Run via SSH on EC2.
The monitor agent pipes its WebSearch findings as JSON on stdin,
which gets injected into Gemini's prompt as external intelligence.

Usage (EC2):
    sudo bash -c 'source /run/sovereign-hive/env && cd /app/sovereign-hive && \
        ./venv/bin/python tools/ai_position_review.py'

    With external context from monitor:
    echo '{"context":"Crockett leading 56-44 in latest UT/TPP poll"}' | \
        sudo bash -c 'source /run/sovereign-hive/env && cd /app/sovereign-hive && \
        ./venv/bin/python tools/ai_position_review.py'

Output: JSON to stdout (structured for monitor agent parsing)
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timezone

# ── Bootstrap ──────────────────────────────────────────────────────────
for envpath in ["/run/sovereign-hive/env", "/app/sovereign-hive/.env", ".env"]:
    if os.path.exists(envpath):
        try:
            from dotenv import load_dotenv
            load_dotenv(envpath)
        except ImportError:
            with open(envpath) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip("'\"")

# Add project root to path so we can import sovereign_hive modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    from sovereign_hive.core.gemini_analyzer import GeminiAnalyzer
except ImportError as e:
    print(json.dumps({"error": f"missing dependency: {e}",
                       "timestamp": datetime.now(timezone.utc).isoformat()}))
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────
WALLET_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
PORTFOLIO_DIR = os.path.join(project_root, "sovereign_hive", "data")


def get_clob_client():
    """Initialize CLOB client."""
    creds = ApiCreds(
        api_key=os.environ.get("CLOB_API_KEY", ""),
        api_secret=os.environ.get("CLOB_SECRET", ""),
        api_passphrase=os.environ.get("CLOB_PASSPHRASE", "")
    )
    return ClobClient(
        host="https://clob.polymarket.com", chain_id=137,
        key=WALLET_KEY, creds=creds, signature_type=0,
    )


def load_portfolio():
    """Load portfolio file (tries market_maker first, then live)."""
    for name in ["portfolio_market_maker.json", "portfolio_live.json", "portfolio.json"]:
        path = os.path.join(PORTFOLIO_DIR, name)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None


def read_stdin_context():
    """Read external context from stdin (non-blocking)."""
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                data = json.loads(raw)
                return data.get("context", "")
        except (json.JSONDecodeError, KeyError):
            return raw.strip()
    return ""


def get_order_book(client, token_id):
    """Fetch order book for a token. Returns (best_bid, best_ask)."""
    try:
        book = client.get_order_book(token_id)
        best_bid = float(book.bids[0].price) if book.bids else 0.0
        best_ask = float(book.asks[0].price) if book.asks else 1.0
        return best_bid, best_ask
    except Exception as e:
        print(f"[REVIEW] Order book error for {token_id[:20]}...: {e}", file=sys.stderr)
        return 0.0, 1.0


def get_open_orders(client):
    """Get all open orders from CLOB."""
    try:
        return client.get_orders()
    except Exception as e:
        print(f"[REVIEW] Get orders error: {e}", file=sys.stderr)
        return []


async def review_positions(portfolio, client, external_context):
    """Review all open positions using Gemini with external context."""
    gemini = GeminiAnalyzer()
    reviews = []
    errors = []

    positions = portfolio.get("positions", {})
    if not positions:
        return reviews, errors

    # Get open orders to find sell order IDs and prices
    open_orders = get_open_orders(client)
    # Build lookup: token_id -> order info
    order_lookup = {}
    for order in open_orders:
        asset_id = order.get("asset_id", "")
        if asset_id:
            order_lookup[asset_id] = {
                "order_id": order.get("id", ""),
                "side": order.get("side", ""),
                "price": float(order.get("price", 0)),
                "size": float(order.get("original_size", order.get("size", 0))),
                "size_matched": float(order.get("size_matched", 0)),
            }

    for condition_id, pos in positions.items():
        live_state = pos.get("live_state", "")
        # Only review positions that are active (filled, sell pending, etc.)
        if live_state not in ("FILLED", "SELL_PENDING", "SELL_POSTED", "BUY_PENDING"):
            continue

        token_id = pos.get("token_id", "")
        if not token_id:
            continue

        try:
            entry_price = float(pos.get("entry_price", 0))
            shares = float(pos.get("shares", 0))
            cost_basis = float(pos.get("cost_basis", 0))
            question = pos.get("question", "Unknown market")

            # Calculate hold time
            entry_time = pos.get("entry_time", pos.get("fill_time", ""))
            hold_hours = 0.0
            if entry_time:
                try:
                    et = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    hold_hours = (datetime.now(timezone.utc) - et).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass

            # Get current order book
            best_bid, best_ask = get_order_book(client, token_id)
            current_price = (best_bid + best_ask) / 2 if best_bid > 0 else best_ask

            # Find sell order info
            sell_info = order_lookup.get(token_id, {})
            sell_order_id = sell_info.get("order_id", pos.get("sell_order_id", ""))
            sell_order_price = sell_info.get("price", float(pos.get("mm_ask", 0)))

            # Call Gemini with external context
            result = await gemini.evaluate_exit_with_context(
                question=question,
                entry_price=entry_price,
                current_price=current_price,
                hold_hours=hold_hours,
                best_bid=best_bid,
                best_ask=best_ask,
                external_context=external_context,
                position_size_usd=cost_basis,
            )

            reviews.append({
                "condition_id": condition_id,
                "market": question,
                "token_id": token_id,
                "entry_price": entry_price,
                "current_price": round(current_price, 4),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "hold_hours": round(hold_hours, 1),
                "shares": shares,
                "cost_basis": round(cost_basis, 2),
                "live_state": live_state,
                "gemini_action": result.get("action", "HOLD"),
                "gemini_confidence": result.get("confidence", 0.5),
                "gemini_true_prob": result.get("true_probability", current_price),
                "gemini_sell_price": result.get("sell_price", entry_price),
                "gemini_reason": result.get("reason", ""),
                "sell_order_id": sell_order_id,
                "sell_order_price": sell_order_price,
            })

            # Rate limit between Gemini calls
            await asyncio.sleep(0.5)

        except Exception as e:
            errors.append(f"{condition_id[:20]}: {str(e)[:100]}")

    return reviews, errors


async def main():
    # Read external context from monitor agent
    external_context = read_stdin_context()

    # Load portfolio
    portfolio = load_portfolio()
    if not portfolio:
        print(json.dumps({
            "error": "No portfolio file found",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        sys.exit(1)

    # Init CLOB client
    if not WALLET_KEY:
        print(json.dumps({
            "error": "POLYMARKET_PRIVATE_KEY not set",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        sys.exit(1)

    client = get_clob_client()

    # Review positions
    reviews, errors = await review_positions(portfolio, client, external_context)

    # Output structured JSON
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "external_context_provided": bool(external_context),
        "positions_reviewed": len(reviews),
        "reviews": reviews,
        "errors": errors,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
