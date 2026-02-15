"""
Discord Bot for QuesQuant HFT - /audit command with real on-chain data.
"""
import discord
from discord.ext import commands
import os
import asyncio
from datetime import datetime

# Load Config
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
env_path = os.path.join(parent_dir, ".env")

if os.path.exists(env_path):
    load_dotenv(env_path)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")

if not DISCORD_BOT_TOKEN:
    print(f"[ERROR] .env not found at {env_path} or TOKEN missing.")

# Initialize Bot
print("[BOOT] Initializing Bot intents...")
intents = discord.Intents.default()
bot = discord.Bot(intents=intents)
print("[BOOT] Bot instance created.")


@bot.event
async def on_ready():
    print(f"[DISCORD] Logged in as {bot.user}")
    print("[DISCORD] Commands: /audit")


@bot.slash_command(name="audit", description="Get real-time portfolio from on-chain data")
async def audit(ctx):
    """Fetch and display real on-chain portfolio data."""
    print(f"[AUDIT] Command received from {ctx.author.name}")

    try:
        await ctx.defer()
    except Exception as e:
        print(f"[AUDIT] Defer failed: {e}")
        return

    try:
        # Import here to avoid circular imports
        from alerts.trade_alerts import get_portfolio_async

        print("[AUDIT] Fetching on-chain data...")
        data = await get_portfolio_async()

        if "error" in data:
            await ctx.respond(f"[AUDIT] Error: {data['error']}")
            return

        # Extract data
        usdc = data.get("usdc_balance", 0)
        pol = data.get("pol_balance", 0)
        positions = data.get("positions", [])
        total_equity = data.get("total_equity", 0)
        timestamp = data.get("timestamp", "N/A")

        # Color based on equity
        color = 3066993  # Green

        embed = discord.Embed(
            title="QUESQUANT CFO REPORT",
            color=color
        )

        # Wallet Section
        wallet_str = f"**USDC.e**: ${usdc:.2f}\n**POL**: {pol:.4f}"
        embed.add_field(name="WALLET", value=wallet_str, inline=False)

        # Positions Section
        if positions:
            pos_str = ""
            for p in positions:
                name = p.get("name", "Unknown")
                shares = p.get("shares", 0)
                value = p.get("value", 0)
                pos_str += f"**{name}**\n"
                pos_str += f"  {shares:.2f} shares @ ~${value:.2f}\n"
            embed.add_field(name="POSITIONS", value=pos_str, inline=False)
        else:
            embed.add_field(name="POSITIONS", value="No active positions", inline=False)

        # Summary
        embed.add_field(
            name="TOTAL EQUITY",
            value=f"**${total_equity:.2f}**",
            inline=False
        )

        embed.set_footer(text=f"On-chain data | {timestamp} | Req by {ctx.author.name}")

        await ctx.respond(embed=embed)
        print("[AUDIT] Response sent.")

    except Exception as e:
        print(f"[AUDIT] Critical error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await ctx.respond(f"[AUDIT] Bot error: {e}")
        except:
            pass


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("[ERROR] DISCORD_BOT_TOKEN not found.")
    else:
        print(f"[BOOT] Starting bot...")
        bot.run(DISCORD_BOT_TOKEN)
