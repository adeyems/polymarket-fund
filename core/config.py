import os
from dotenv import load_dotenv

# Robust .env loading (Handles Local Nested vs Prod Flat)
basedir = os.path.abspath(os.path.dirname(__file__))
env_path_prod = os.path.join(basedir, ".env")
env_path_local = os.path.join(basedir, "..", ".env")

# print(f"DEBUG: Basedir: {basedir}")
# print(f"DEBUG: Trying Prod .env: {env_path_prod}")
load_dotenv(env_path_prod)      # Prod: config.py and .env in same dir
load_dotenv(env_path_local) # Local: config.py in core/, .env in root

# print(f"DEBUG: TOKEN in ENV: {os.getenv('DISCORD_BOT_TOKEN')}")

# QuesQuant Configuration
# PROXY: loaded from .env (PROXY_URL)
PROXY_URL = os.getenv("PROXY_URL", "")

# Alerts
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")
