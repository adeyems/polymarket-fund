"""
Non-blocking Discord trade alerts and portfolio fetching.
All webhook calls are fire-and-forget to ensure zero latency impact on HFT.
"""
import os
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# Thread pool for non-blocking execution
_executor = ThreadPoolExecutor(max_workers=2)

# Load config
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
WALLET = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CT_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Known position token IDs (add more as needed)
KNOWN_POSITIONS = {
    "51338236787729560681434534660841415073585974762690814047670810862722808070955": "Kevin Warsh YES (Fed Chair)"
}


def get_portfolio_sync() -> Dict[str, Any]:
    """
    Synchronously fetch real on-chain portfolio data.
    Returns dict with balances and positions.
    """
    try:
        from web3 import Web3

        # Try multiple RPCs
        rpcs = ['https://polygon-rpc.com', 'https://1rpc.io/matic']
        w3 = None
        for rpc in rpcs:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
                if w3.is_connected():
                    break
            except:
                continue

        if not w3 or not w3.is_connected():
            return {"error": "RPC connection failed"}

        # ERC-20 balance ABI
        erc20_abi = [{
            'inputs': [{'name': 'account', 'type': 'address'}],
            'name': 'balanceOf',
            'outputs': [{'name': '', 'type': 'uint256'}],
            'stateMutability': 'view',
            'type': 'function'
        }]

        # ERC-1155 balance ABI
        erc1155_abi = [{
            'inputs': [{'name': 'account', 'type': 'address'}, {'name': 'id', 'type': 'uint256'}],
            'name': 'balanceOf',
            'outputs': [{'name': '', 'type': 'uint256'}],
            'stateMutability': 'view',
            'type': 'function'
        }]

        # Get USDC.e balance
        usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=erc20_abi)
        usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call() / 1e6

        # Get POL balance
        pol_balance = w3.eth.get_balance(Web3.to_checksum_address(WALLET)) / 1e18

        # Get conditional token positions
        ct = w3.eth.contract(address=Web3.to_checksum_address(CT_ADDRESS), abi=erc1155_abi)
        positions = []
        total_position_value = 0

        for token_id, name in KNOWN_POSITIONS.items():
            try:
                balance = ct.functions.balanceOf(
                    Web3.to_checksum_address(WALLET),
                    int(token_id)
                ).call() / 1e6

                if balance > 0.01:  # Only show positions > 0.01 shares
                    # Estimate value at ~$0.98 for high-probability markets
                    value = balance * 0.98
                    total_position_value += value
                    positions.append({
                        "name": name,
                        "token_id": token_id[:20] + "...",
                        "shares": balance,
                        "value": value
                    })
            except Exception as e:
                pass  # Skip failed position lookups

        total_equity = usdc_balance + total_position_value

        return {
            "usdc_balance": usdc_balance,
            "pol_balance": pol_balance,
            "positions": positions,
            "total_equity": total_equity,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    except Exception as e:
        return {"error": str(e)}


async def get_portfolio_async() -> Dict[str, Any]:
    """Non-blocking portfolio fetch using thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, get_portfolio_sync)


async def send_trade_alert_async(
    action: str,  # "BUY" or "SELL"
    market_name: str,
    price: float,
    size: float,
    order_id: Optional[str] = None,
    status: str = "SUBMITTED"
):
    """
    Fire-and-forget trade alert via Discord webhook.
    Completely non-blocking - errors are silently logged.
    """
    if not DISCORD_WEBHOOK_URL:
        return

    try:
        # Color: Green for BUY, Red for SELL
        color = 3066993 if action == "BUY" else 15158332
        emoji = "🟢" if action == "BUY" else "🔴"

        notional = price * size

        embed = {
            "title": f"{emoji} TRADE {action}",
            "color": color,
            "fields": [
                {"name": "Market", "value": market_name[:50], "inline": False},
                {"name": "Price", "value": f"${price:.4f}", "inline": True},
                {"name": "Size", "value": f"{size:.2f} shares", "inline": True},
                {"name": "Notional", "value": f"${notional:.2f}", "inline": True},
                {"name": "Status", "value": status, "inline": True},
            ],
            "footer": {"text": f"Order: {order_id[:16]}..." if order_id else "QuesQuant HFT"}
        }

        payload = {"embeds": [embed]}

        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5) as resp:
                if resp.status not in (200, 204):
                    print(f"[ALERT] Discord returned {resp.status}")

    except Exception as e:
        # Never let alert failures affect trading
        print(f"[ALERT-ERROR] {e}")


def send_trade_alert_fire_and_forget(
    action: str,
    market_name: str,
    price: float,
    size: float,
    order_id: Optional[str] = None,
    status: str = "SUBMITTED"
):
    """
    Synchronous wrapper that fires alert in background thread.
    Use this from sync code - it returns immediately.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, create task
            asyncio.create_task(send_trade_alert_async(
                action, market_name, price, size, order_id, status
            ))
        else:
            # We're in sync context, use thread pool
            _executor.submit(
                asyncio.run,
                send_trade_alert_async(action, market_name, price, size, order_id, status)
            )
    except Exception as e:
        print(f"[ALERT-FIRE] {e}")


# Export for easy import
__all__ = [
    'get_portfolio_sync',
    'get_portfolio_async',
    'send_trade_alert_async',
    'send_trade_alert_fire_and_forget'
]
