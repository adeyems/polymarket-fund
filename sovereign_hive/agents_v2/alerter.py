"""
Discord Alerter Agent — Portfolio notifications and reports.

Polls portfolio state every 60s and sends Discord webhook messages for:
1. New trades (buy/sell)
2. Closed positions (with P&L)
3. 6-hour portfolio summaries
4. System events from the watchdog
5. Daily performance report (8 AM UTC)
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
HEARTBEAT_FILE = DATA_DIR / ".heartbeat.json"
EVENTS_FILE = DATA_DIR / ".watchdog_events.jsonl"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
POLL_INTERVAL = int(os.getenv("ALERT_POLL_INTERVAL", "60"))
SUMMARY_INTERVAL = int(os.getenv("ALERT_SUMMARY_INTERVAL", "21600"))  # 6 hours
DAILY_REPORT_HOUR = int(os.getenv("ALERT_DAILY_REPORT_HOUR", "8"))

# State tracking
_last_portfolio_state: Optional[Dict] = None
_last_trade_count: int = 0
_last_positions: set = set()
_last_summary_time: Optional[datetime] = None
_last_daily_report_date: Optional[str] = None
_last_event_line: int = 0

# Discord embed colors
COLOR_GREEN = 3066993     # Trade buy, good news
COLOR_RED = 15158332      # Trade sell, bad news
COLOR_BLUE = 3447003      # Info, reports
COLOR_YELLOW = 16776960   # Warnings
COLOR_PURPLE = 10181046   # System events


async def send_discord_embed(title: str, description: str = "", color: int = COLOR_BLUE,
                              fields: List[Dict] = None):
    """Send a Discord webhook embed message."""
    if not DISCORD_WEBHOOK:
        print(f"[ALERTER] No webhook URL — would send: {title}")
        return

    embed = {
        "title": title,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields
    embed["footer"] = {"text": "Sovereign Hive"}

    payload = {"embeds": [embed]}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK, json=payload, timeout=10) as resp:
                if resp.status not in (200, 204):
                    print(f"[ALERTER] Discord returned {resp.status}")
                else:
                    print(f"[ALERTER] Sent: {title}")
    except Exception as e:
        print(f"[ALERTER] Discord error: {e}")


def _find_portfolio_file() -> Optional[Path]:
    """Find the active portfolio JSON file."""
    # Try strategy-specific files first, then default
    candidates = [
        DATA_DIR / "portfolio_sim.json",
        DATA_DIR / "portfolio_market_maker.json",
    ]
    # Also check for any portfolio_*.json
    for f in sorted(DATA_DIR.glob("portfolio_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f not in candidates:
            candidates.insert(0, f)

    for f in candidates:
        if f.exists():
            return f
    return None


def _load_portfolio() -> Optional[Dict]:
    """Load the current portfolio state."""
    portfolio_file = _find_portfolio_file()
    if not portfolio_file:
        return None
    try:
        with open(portfolio_file) as f:
            return json.load(f)
    except Exception:
        return None


async def check_new_trades(portfolio: Dict):
    """Detect and alert on new trades since last check."""
    global _last_trade_count, _last_positions

    trade_history = portfolio.get("trade_history", [])
    current_trade_count = len(trade_history)
    current_positions = set(portfolio.get("positions", {}).keys())

    # New closed trades (trade_history grew)
    if current_trade_count > _last_trade_count and _last_trade_count > 0:
        new_trades = trade_history[_last_trade_count:]
        for trade in new_trades[-3:]:  # Cap at 3 to avoid spam
            pnl = trade.get("pnl", 0)
            pnl_pct = trade.get("pnl_pct", 0)
            color = COLOR_GREEN if pnl >= 0 else COLOR_RED
            emoji = "+" if pnl >= 0 else ""

            await send_discord_embed(
                title=f"CLOSED | {emoji}${pnl:.2f} ({emoji}{pnl_pct:.1f}%)",
                color=color,
                fields=[
                    {"name": "Market", "value": trade.get("question", "?")[:60], "inline": False},
                    {"name": "Strategy", "value": trade.get("strategy", "?"), "inline": True},
                    {"name": "Side", "value": trade.get("side", "?"), "inline": True},
                    {"name": "Exit", "value": trade.get("exit_reason", "?"), "inline": True},
                    {"name": "Entry", "value": f"${trade.get('entry_price', 0):.3f}", "inline": True},
                    {"name": "Exit Price", "value": f"${trade.get('exit_price', 0):.3f}", "inline": True},
                ],
            )

    # New positions opened (positions set grew)
    new_positions = current_positions - _last_positions
    if new_positions and _last_positions:  # Skip initial load
        positions_data = portfolio.get("positions", {})
        for cid in list(new_positions)[:3]:  # Cap at 3
            pos = positions_data.get(cid, {})
            await send_discord_embed(
                title=f"TRADE BUY | {pos.get('strategy', '?')}",
                color=COLOR_GREEN,
                fields=[
                    {"name": "Market", "value": pos.get("question", "?")[:60], "inline": False},
                    {"name": "Side", "value": pos.get("side", "?"), "inline": True},
                    {"name": "Price", "value": f"${pos.get('entry_price', 0):.3f}", "inline": True},
                    {"name": "Amount", "value": f"${pos.get('cost_basis', 0):.2f}", "inline": True},
                ],
            )

    _last_trade_count = current_trade_count
    _last_positions = current_positions


async def send_summary(portfolio: Dict):
    """Send periodic portfolio summary."""
    global _last_summary_time

    now = datetime.now(timezone.utc)
    if _last_summary_time and (now - _last_summary_time).total_seconds() < SUMMARY_INTERVAL:
        return

    balance = portfolio.get("balance", 0)
    initial = portfolio.get("initial_balance", 1000)
    metrics = portfolio.get("metrics", {})
    positions = portfolio.get("positions", {})
    strategy_metrics = portfolio.get("strategy_metrics", {})

    total_pnl = metrics.get("total_pnl", 0)
    total_trades = metrics.get("total_trades", 0)
    wins = metrics.get("winning_trades", 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    roi = (balance + sum(p.get("cost_basis", 0) for p in positions.values()) - initial) / initial * 100

    # Strategy breakdown
    strat_lines = []
    for strat, data in sorted(strategy_metrics.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
        trades = data.get("trades", 0)
        if trades > 0:
            s_wins = data.get("wins", 0)
            s_wr = s_wins / trades * 100
            s_pnl = data.get("pnl", 0)
            strat_lines.append(f"**{strat}**: {trades} trades, {s_wr:.0f}% WR, ${s_pnl:+.2f}")

    strat_text = "\n".join(strat_lines) if strat_lines else "No completed trades yet"

    await send_discord_embed(
        title=f"PORTFOLIO REPORT | {now.strftime('%H:%M UTC')}",
        color=COLOR_BLUE,
        fields=[
            {"name": "Balance", "value": f"${balance:.2f}", "inline": True},
            {"name": "Open Positions", "value": str(len(positions)), "inline": True},
            {"name": "Total P&L", "value": f"${total_pnl:+.2f}", "inline": True},
            {"name": "ROI", "value": f"{roi:+.1f}%", "inline": True},
            {"name": "Win Rate", "value": f"{win_rate:.1f}% ({wins}/{total_trades})", "inline": True},
            {"name": "Strategies", "value": strat_text, "inline": False},
        ],
    )

    _last_summary_time = now


async def check_watchdog_events():
    """Read and forward watchdog events to Discord."""
    global _last_event_line

    if not EVENTS_FILE.exists():
        return

    try:
        with open(EVENTS_FILE) as f:
            lines = f.readlines()

        new_lines = lines[_last_event_line:]
        _last_event_line = len(lines)

        for line in new_lines[-5:]:  # Cap at 5 events
            try:
                event = json.loads(line.strip())
                severity = event.get("severity", "info")
                color = {
                    "info": COLOR_BLUE,
                    "warning": COLOR_YELLOW,
                    "critical": COLOR_RED,
                }.get(severity, COLOR_YELLOW)

                await send_discord_embed(
                    title=f"SYSTEM | {event.get('event_type', 'unknown').upper()}",
                    description=event.get("message", ""),
                    color=color,
                )
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"[ALERTER] Event read error: {e}")


async def check_daily_report(portfolio: Dict):
    """Send daily performance report at configured hour."""
    global _last_daily_report_date

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    if _last_daily_report_date == today:
        return
    if now.hour != DAILY_REPORT_HOUR:
        return

    _last_daily_report_date = today

    # Send a detailed summary (reuse summary logic)
    await send_summary(portfolio)


async def main():
    """Main alerter loop."""
    global _last_trade_count, _last_positions, _last_summary_time

    print(f"[ALERTER] Starting (poll={POLL_INTERVAL}s, summary={SUMMARY_INTERVAL}s)")

    # Initialize state from current portfolio
    portfolio = _load_portfolio()
    if portfolio:
        _last_trade_count = len(portfolio.get("trade_history", []))
        _last_positions = set(portfolio.get("positions", {}).keys())
        print(f"[ALERTER] Initialized: {_last_trade_count} trades, {len(_last_positions)} positions")

    # Send startup notification
    await send_discord_embed(
        title="SYSTEM | ALERTER STARTED",
        description="Discord alerter agent is online and monitoring.",
        color=COLOR_PURPLE,
    )

    while True:
        try:
            portfolio = _load_portfolio()
            if portfolio:
                await check_new_trades(portfolio)
                await send_summary(portfolio)
                await check_daily_report(portfolio)

            await check_watchdog_events()

        except Exception as e:
            print(f"[ALERTER] Loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
