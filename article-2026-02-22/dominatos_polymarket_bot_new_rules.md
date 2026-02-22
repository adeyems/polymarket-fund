How to build a Polymarket bot (after new rules edition)

Polymarket silently satisfies nuked the 500ms delay 
Here's how to build a bot that actually works under the new rules

2 days ago Polymarket removed the 500ms taker price delay on crypto markets. No announcement. No warning. Half the bots on the platform broke overnight.
But it also opened up the biggest opportunity for new bots since Polymarket launched.
And today I'll explain how to build a bot that works under the new rules because everything you've seen before February 18 is now outdated.

If you try right now to ask an AI model to build a Polymarket bot, you'll get something based on the OLD rules. REST polling, no fee handling, no awareness that the 500ms buffer is gone.
That bot will lose money from the first trade.
Let me explain what actually changed and how to build around it.

What changed
Three things happened in the last 2 months:

1. The 500ms taker delay was removed (Feb 18, 2026)
Every taker order used to wait 500ms before executing. Market makers relied on this buffer to cancel stale quotes it was basically free insurance.
Now taker orders execute instantly. There's no time to cancel.

2. Dynamic taker fees on crypto markets (Jan 2026)
15-minute and 5-minute crypto markets now have taker fees. The formula:
fee = C × 0.25 × (p × (1-p))²
Max fee: ~1.56% at 50% probability. Drops to nearly zero at the extremes.

Remember the bot that made $515K in one month with a 99% win rate just exploiting price feed lag between Binance and Polymarket? 
That strategy is dead. The fee alone exceeds the arbitrage margin

The new meta
The new meta is simple: be a maker, not a taker.
Why:
Makers pay ZERO fees
Makers earn daily USDC rebates (funded by taker fees)
With 500ms delay gone, maker quotes get filled faster
Top bots now profit from rebates alone, not even from the spread
If you're still building a taker bot, you're fighting the fee curve
At 50% probability you need >1.56% edge just to break even
Good luck.

How to actually build this
Here's the architecture of a bot that works in 2026:
The key components:

1. WebSocket, not REST 
REST polling is dead. By the time your HTTP request round-trips, the opportunity is gone. You need real-time orderbook streams via WebSocket.

2. Fee-aware order signing.
This is the part that didn't exist before. You MUST include feeRateBps in your signed order payload now. If you miss this field, your orders get rejected on fee-enabled markets.

3. Fast cancel/replace loop
Without the 500ms buffer, if your cancel loop takes >200ms, you will get adversely selected. Someone will take your stale quote before you can update it.

Setting it up
1. Get your private key
Same key you use to log into Polymarket (EOA / MetaMask / hardware wallet).
export POLYMARKET_PRIVATE_KEY="0xyour_private_key_here"

2. Set approvals (one-time)
Before Polymarket can execute your trades, you need to approve the exchange contracts for USDC and conditional tokens. Do this once per wallet.

3. Connect to the CLOB
The official Python client works:
pip install py-clob-client
But there are now faster options in Rust:
polyfill-rs  (zero-alloc hot paths, SIMD JSON parsing, 21% faster)
polymarket-client-sdk (official Polymarket Rust SDK)
polymarket-hft (full HFT framework with CLOB + WS)
Pick what you can ship fastest

4. Query fee rates before every order
GET /fee-rate?tokenID={token_id}
Never hardcode fees. They vary per market and Polymarket can change them.

5. Sign orders with the fee field
{
  "salt": "...",
  "maker": "0x...",
  "signer": "0x...",
  "taker": "0x...",
  "tokenId": "...",
  "makerAmount": "50000000",
  "takerAmount": "100000000",
  "feeRateBps": "150"
}
The CLOB validates your signature against feeRateBps. If it doesn't match the current rate, the order is rejected.
If you use the official SDK (Python or Rust), this is handled automatically. But if you're building custom signing logic, you need this.

6. Post maker orders on both sides
Place limit orders that add liquidity  
BUY and SELL on both YES and NO tokens. This is what earns you rebates.

7. Run the cancel/replace loop
Monitor the external price feed (Binance WS) and your current quotes. When the price moves, cancel stale orders and replace with updated quotes. Target <100ms for the full cycle.

For 5-minute markets specifically
The 5-min BTC up/down markets are deterministic. You can calculate the exact market from the timestamp:
288 markets per day. Each one is a fresh opportunity.
The strategy that's been working:
At T-10 seconds before window close, BTC direction is ~85% determined
But Polymarket odds haven't fully priced it in
Post a maker order on the winning side at 90-95¢
If filled: $0.05-0.10/share profit on resolution, zero fees, plus rebates
The edge is pricing BTC direction faster than other makers and getting your order posted first.

The mistakes that will kill you
Using REST instead of WebSocket
Not including feeRateBps in order signing
Running from home wifi (150ms+ latency vs <5ms on a colocated VPS)
Market making near 50% without accounting for adverse selection
Hardcoding fee rates
Not merging YES/NO positions (capital gets locked)
Trying to taker-arb like it's 2025

The correct way to use AI here
That's the end of the technical part.
You now have the architecture, the fee math, and the new rules.
After that, you open Claude or any decent AI model and give it a specific task:
"Here's the Polymarket SDK. Write me a maker bot for 5-minute BTC markets. It should monitor Binance WS for price, post maker orders on both sides, include feeRateBps in signing, and run a cancel/replace loop under 100ms. Use WebSocket for orderbook data."
The correct approach: you define the stack, the infrastructure, and the constraints. AI generates the strategy logic on top.

And even if you describe the bot logic perfectly 
you still have to test it first. Especially now with fees eating into margins, backtesting against the fee curve is mandatory before you go live.

The bots that win in 2026 aren't the fastest takers.
They're the best liquidity providers.
Build accordingly.
