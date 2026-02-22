I reverse-engineered a $619K Polymarket sports bot and recreated the full logic in Claude Opus 4.6. 

It makes ~$2,000/day. This wallet ran 7,877 trades in a year using a math-based strategy that most people completely overlook.

I went through the positions, found the real edge, and mapped everything out.

Here’s exactly how it works. 🧵 

The strategy is Arbitrage.

If you understand the math, you’ll understand why this bot makes money. Instead of predicting an outcome, the bot exploits temporary mispricings where the sum of probabilities is less than 1.

There are exactly two ways this bot finds arbitrage on Polymarket:
1. YES-YES Arb: Buying “YES” for two opposing sides when combined prices < $1.
2. NO-NO Arb: Buying “NO” for two opposing sides when combined prices < $1.

Real Trade Example 1:
Market: Will Finland beat Switzerland?
• It bought YES (Finland) at 44.20¢
• It bought YES (Switzerland) at 52.50¢
Total cost: 96.70¢
Guaranteed payout: $1.00
Net profit: 3.30¢ per share.

Real Trade Example 2:
Market: Alabama vs Arkansas
• It bought YES (Bama) at 84.40¢
• It bought YES (Arkansas) at 12.00¢
Total cost: 96.40¢
Guaranteed payout: $1.00
Net profit: +$149.33 on this single trade

Let’s look at the core logic built into this script:

Step 1: The Scan
Every 30-60 secs, it pills the Polymarket CLOB via API. It specifically filters for active sports markets (NCAA, NFL, EuroLeague) with exactly two outcomes. 

Step 2: The Math
It takes the best available Bid/Ask prices for Team A and Team B and runs the check. It’s strictly looking for cases where:
Ask(Team A) + Ask(Team B) < $0.98. 
(Polymarket charges a 2% fee on winning shares, so 98c is the true break-even line).

Step 3: Position Sizing & Risk
The bot doesn’t just blindly buy max size. It checks the depth of the order book.
If it finds a 3.3c arb, it calculates exactly how many shares it can buy before the price slips past 98c. 
Risk is hard-capped (usually ~$7K-$9K max per side).

Step 4: Simultaneous Execution
This is crucial. The bot uses “Fill-or-Kill” limit orders via the API simultaneously. 
If you manually try to buy Side A, and then Side B, the price of Side B might move—leaving you exposed to directional risk (known as “spread closing”). 
The script executes both in milliseconds. If one fails, the other cancels.

Step 5: Settle and Reinvest
Wait for the game to end. Claim the $1 payout on the winning side. The capital cycles back into the pool to run again. 

Here is the thing: None of this logic is particularly insane. It’s standard quantitative arbitrage. 
The magic is the automation and the discipline. Where a human might make +$149 and stop, this bot ran the exact same logic 7,877 times.

Prediction markets are incredibly inefficient right now compared to trad-fi because there simply aren’t enough MMs or arbers taking advantage of the gaps yet. 

Once more retail volume floods in, these spreads will tighten. But for now, the edge is massive.
