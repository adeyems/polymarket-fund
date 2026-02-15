#!/usr/bin/env python3
"""
SAFE SWAP UTILITY
=================
Universal token swap with mandatory safety checks.
NEVER executes if slippage > threshold.

Usage:
    python safe_swap.py pol_to_usdc 50      # Swap 50 POL to USDC.e
    python safe_swap.py usdc_to_pol 10      # Swap 10 USDC.e to POL
    python safe_swap.py native_to_bridged 5 # Swap 5 Native USDC to USDC.e
    python safe_swap.py bridged_to_native 5 # Swap 5 USDC.e to Native USDC
    python safe_swap.py quote pol_to_usdc 50 # Quote only (no execution)
"""
import os
import sys
import time
import json
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import dotenv_values

# Try multiple .env paths
ENV_PATHS = ["/app/hft/.env", ".env", "../.env"]
config = {}
for path in ENV_PATHS:
    if os.path.exists(path):
        config = dotenv_values(path)
        break

# --- CONFIGURATION ---
RPC_URL = "https://polygon-bor.publicnode.com"
MAX_SLIPPAGE_PERCENT = 3.0  # HARD LIMIT: Abort if slippage > 3%

# Token Addresses
TOKENS = {
    "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    "USDC_E": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # Bridged USDC
    "NATIVE_USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC
    "POL": "NATIVE",  # Special marker for native token
}

# Uniswap V3 Contracts
UNISWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
UNISWAP_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
POLYMARKET_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# ABIs
WMATIC_ABI = json.loads('[{"constant":false,"inputs":[],"name":"deposit","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},{"constant":false,"inputs":[{"name":"guy","type":"address"},{"name":"wad","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},{"constant":false,"inputs":[{"name":"wad","type":"uint256"}],"name":"withdraw","outputs":[],"type":"function"}]')

ERC20_ABI = json.loads('[{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]')

QUOTER_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]')

ROUTER_ABI = json.loads('[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct ISwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}]')


class SafeSwap:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise Exception("Cannot connect to Polygon RPC")

        pk = config.get("POLYMARKET_PRIVATE_KEY") or os.getenv("POLYMARKET_PRIVATE_KEY")
        if not pk:
            raise Exception("POLYMARKET_PRIVATE_KEY not found")

        self.account = Account.from_key(pk)
        self.address = self.account.address
        self.quoter = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_QUOTER),
            abi=QUOTER_ABI
        )
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_ROUTER),
            abi=ROUTER_ABI
        )

    def get_balance(self, token: str) -> tuple:
        """Get balance of a token. Returns (raw_balance, decimals, readable_balance)"""
        if token == "POL":
            bal = self.w3.eth.get_balance(self.address)
            return bal, 18, bal / 1e18

        addr = TOKENS.get(token)
        if not addr:
            raise ValueError(f"Unknown token: {token}")

        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(addr),
            abi=ERC20_ABI
        )
        bal = contract.functions.balanceOf(self.address).call()
        try:
            decimals = contract.functions.decimals().call()
        except:
            decimals = 18 if token == "WMATIC" else 6

        return bal, decimals, bal / (10 ** decimals)

    def get_quote(self, token_in: str, token_out: str, amount_in: int) -> tuple:
        """
        Get best quote across multiple fee tiers.
        Returns (best_quote, best_fee, all_quotes)
        """
        # Resolve addresses
        addr_in = TOKENS.get(token_in)
        addr_out = TOKENS.get(token_out)

        if token_in == "POL":
            addr_in = TOKENS["WMATIC"]
        if token_out == "POL":
            addr_out = TOKENS["WMATIC"]

        quotes = {}
        best_quote = None
        best_fee = None

        for fee in [100, 500, 3000, 10000]:  # 0.01%, 0.05%, 0.3%, 1%
            try:
                quote = self.quoter.functions.quoteExactInputSingle(
                    Web3.to_checksum_address(addr_in),
                    Web3.to_checksum_address(addr_out),
                    fee,
                    amount_in,
                    0
                ).call()
                quotes[fee] = quote

                if best_quote is None or quote > best_quote:
                    best_quote = quote
                    best_fee = fee
            except Exception as e:
                quotes[fee] = f"Error: {e}"

        return best_quote, best_fee, quotes

    def calculate_slippage(self, amount_in: int, amount_out: int,
                           decimals_in: int, decimals_out: int,
                           expected_rate: float = None) -> float:
        """
        Calculate slippage percentage.
        For stablecoin swaps (USDC variants), expected rate is 1:1
        For POL/USDC, we estimate based on ~$0.15-0.20 per POL
        """
        value_in = amount_in / (10 ** decimals_in)
        value_out = amount_out / (10 ** decimals_out)

        if expected_rate:
            expected_out = value_in * expected_rate
        else:
            # Assume 1:1 for stablecoin swaps
            expected_out = value_in

        if expected_out == 0:
            return 100.0

        slippage = (expected_out - value_out) / expected_out * 100
        return slippage

    def execute_swap(self, token_in: str, token_out: str, amount: float,
                     quote_only: bool = False, force: bool = False) -> dict:
        """
        Execute a swap with safety checks.

        Args:
            token_in: Source token (POL, WMATIC, USDC_E, NATIVE_USDC)
            token_out: Destination token
            amount: Amount to swap (in human-readable units)
            quote_only: If True, only get quote without executing
            force: If True, skip slippage check (DANGEROUS)

        Returns:
            dict with results
        """
        result = {
            "status": "pending",
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount,
        }

        # Get decimals
        if token_in == "POL":
            decimals_in = 18
        elif token_in in ["USDC_E", "NATIVE_USDC"]:
            decimals_in = 6
        else:
            decimals_in = 18

        if token_out == "POL":
            decimals_out = 18
        elif token_out in ["USDC_E", "NATIVE_USDC"]:
            decimals_out = 6
        else:
            decimals_out = 18

        amount_in_raw = int(amount * (10 ** decimals_in))

        # Check balance
        bal_raw, _, bal_readable = self.get_balance(token_in)
        if bal_raw < amount_in_raw:
            result["status"] = "error"
            result["error"] = f"Insufficient balance. Have {bal_readable}, need {amount}"
            return result

        result["balance"] = bal_readable

        # Get quote
        print(f"[QUOTE] Getting quote for {amount} {token_in} -> {token_out}...")
        best_quote, best_fee, all_quotes = self.get_quote(token_in, token_out, amount_in_raw)

        if best_quote is None:
            result["status"] = "error"
            result["error"] = "No valid quote found"
            result["quotes"] = all_quotes
            return result

        amount_out = best_quote / (10 ** decimals_out)
        result["amount_out"] = amount_out
        result["best_fee"] = f"{best_fee/10000}%"
        result["all_quotes"] = {f"{k/10000}%": v/(10**decimals_out) if isinstance(v, int) else v
                                for k, v in all_quotes.items()}

        # Calculate slippage
        # For stablecoin swaps, expect 1:1
        # For POL swaps, we can't easily calculate expected rate
        if token_in in ["USDC_E", "NATIVE_USDC"] and token_out in ["USDC_E", "NATIVE_USDC"]:
            slippage = self.calculate_slippage(amount_in_raw, best_quote, decimals_in, decimals_out, 1.0)
            result["slippage"] = f"{slippage:.2f}%"

            if slippage > MAX_SLIPPAGE_PERCENT and not force:
                result["status"] = "aborted"
                result["error"] = f"SAFETY ABORT: Slippage {slippage:.2f}% exceeds limit {MAX_SLIPPAGE_PERCENT}%"
                print(f"[ABORT] {result['error']}")
                return result
        else:
            result["slippage"] = "N/A (non-stablecoin)"

        print(f"[QUOTE] Best: {amount_out:.4f} {token_out} (fee: {best_fee/10000}%)")

        if quote_only:
            result["status"] = "quote_only"
            return result

        # Execute swap
        print(f"[SWAP] Executing swap...")

        try:
            # Handle POL -> token (need to wrap first)
            if token_in == "POL":
                print("[WRAP] Wrapping POL to WMATIC...")
                wmatic = self.w3.eth.contract(
                    address=Web3.to_checksum_address(TOKENS["WMATIC"]),
                    abi=WMATIC_ABI
                )

                wrap_tx = wmatic.functions.deposit().build_transaction({
                    'from': self.address,
                    'nonce': self.w3.eth.get_transaction_count(self.address),
                    'gas': 100000,
                    'gasPrice': self.w3.eth.gas_price,
                    'value': amount_in_raw
                })
                signed = self.account.sign_transaction(wrap_tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt['status'] != 1:
                    result["status"] = "error"
                    result["error"] = "Wrap failed"
                    return result
                print(f"[WRAP] Done: {tx_hash.hex()}")
                token_in = "WMATIC"

            # Approve router
            token_addr = TOKENS.get(token_in)
            token_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=ERC20_ABI
            )

            allowance = token_contract.functions.allowance(
                self.address, UNISWAP_ROUTER
            ).call()

            if allowance < amount_in_raw:
                print("[APPROVE] Approving router...")
                approve_tx = token_contract.functions.approve(
                    Web3.to_checksum_address(UNISWAP_ROUTER),
                    amount_in_raw
                ).build_transaction({
                    'from': self.address,
                    'nonce': self.w3.eth.get_transaction_count(self.address),
                    'gas': 100000,
                    'gasPrice': self.w3.eth.gas_price
                })
                signed = self.account.sign_transaction(approve_tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt['status'] != 1:
                    result["status"] = "error"
                    result["error"] = "Approval failed"
                    return result
                print(f"[APPROVE] Done: {tx_hash.hex()}")

            # Execute swap
            min_out = int(best_quote * 0.97)  # 3% slippage tolerance
            token_out_addr = TOKENS.get(token_out if token_out != "POL" else "WMATIC")

            params = (
                Web3.to_checksum_address(token_addr),
                Web3.to_checksum_address(token_out_addr),
                best_fee,
                self.address,
                int(time.time()) + 600,
                amount_in_raw,
                min_out,
                0
            )

            swap_tx = self.router.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'nonce': self.w3.eth.get_transaction_count(self.address),
                'gas': 400000,
                'gasPrice': int(self.w3.eth.gas_price * 1.5),
                'value': 0
            })

            signed = self.account.sign_transaction(swap_tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            print(f"[SWAP] TX: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt['status'] == 1:
                result["status"] = "success"
                result["tx_hash"] = tx_hash.hex()

                # Handle token -> POL (need to unwrap)
                if token_out == "POL":
                    print("[UNWRAP] Unwrapping WMATIC to POL...")
                    wmatic = self.w3.eth.contract(
                        address=Web3.to_checksum_address(TOKENS["WMATIC"]),
                        abi=WMATIC_ABI
                    )
                    wmatic_bal = wmatic.functions.balanceOf(self.address).call()

                    unwrap_tx = wmatic.functions.withdraw(wmatic_bal).build_transaction({
                        'from': self.address,
                        'nonce': self.w3.eth.get_transaction_count(self.address),
                        'gas': 100000,
                        'gasPrice': self.w3.eth.gas_price
                    })
                    signed = self.account.sign_transaction(unwrap_tx)
                    unwrap_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                    self.w3.eth.wait_for_transaction_receipt(unwrap_hash, timeout=120)
                    print(f"[UNWRAP] Done: {unwrap_hash.hex()}")

                # Get final balance
                _, _, final_bal = self.get_balance(token_out)
                result["final_balance"] = final_bal

                print(f"[SUCCESS] Swap complete! New {token_out} balance: {final_bal}")
            else:
                result["status"] = "error"
                result["error"] = "Swap transaction reverted"
                result["tx_hash"] = tx_hash.hex()

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    swapper = SafeSwap()

    # Show balances
    print("=" * 50)
    print("CURRENT BALANCES")
    print("=" * 50)
    for token in ["POL", "WMATIC", "USDC_E", "NATIVE_USDC"]:
        try:
            _, _, bal = swapper.get_balance(token)
            symbol = "$" if "USDC" in token else ""
            print(f"{token}: {symbol}{bal:.4f}")
        except:
            pass
    print("=" * 50)

    cmd = sys.argv[1].lower()
    quote_only = cmd == "quote"
    if quote_only and len(sys.argv) > 2:
        cmd = sys.argv[2].lower()
        amount = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    else:
        amount = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

    swap_map = {
        "pol_to_usdc": ("POL", "USDC_E"),
        "usdc_to_pol": ("USDC_E", "POL"),
        "native_to_bridged": ("NATIVE_USDC", "USDC_E"),
        "bridged_to_native": ("USDC_E", "NATIVE_USDC"),
        "wmatic_to_usdc": ("WMATIC", "USDC_E"),
        "usdc_to_wmatic": ("USDC_E", "WMATIC"),
    }

    if cmd not in swap_map:
        print(f"Unknown command: {cmd}")
        print("Available commands:", list(swap_map.keys()))
        return

    token_in, token_out = swap_map[cmd]
    result = swapper.execute_swap(token_in, token_out, amount, quote_only=quote_only)

    print("\n" + "=" * 50)
    print("RESULT")
    print("=" * 50)
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
