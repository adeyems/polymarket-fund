
import discord
import os
from dotenv import load_dotenv

# Load env
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
env_path = os.path.join(parent_dir, ".env")
load_dotenv(env_path)

token = os.getenv("DISCORD_BOT_TOKEN")
print(f"Token length: {len(token) if token else 0}")

intents = discord.Intents.default()
bot = discord.Bot(intents=intents)

@bot.event
async def on_ready():
    print(f"Login Success! Logged in as: {bot.user}")
    await bot.close()

if __name__ == "__main__":
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("No token found.")
