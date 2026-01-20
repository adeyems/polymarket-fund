#!/bin/bash

# Polymarket Bot Watchdog 🐶
# This script runs market_maker.py in a loop.
# If the bot crashes, it restarts it automatically after 5 seconds.

echo "Starting Polymarket Bot Watchdog..."
echo "Press [CTRL+C] to stop everything."

while true; do
    echo "----------------------------------------"
    echo "[$(date)] Launching market_maker.py..."
    echo "----------------------------------------"
    
    # Run the Python script
    /Users/qudus-mac/.pyenv/versions/3.11.9/bin/python market_maker.py
    
    # Check exit status
    EXIT_CODE=$?
    
    echo "----------------------------------------"
    echo "[$(date)] Bot exited with code $EXIT_CODE."
    echo "Restarting in 5 seconds..."
    sleep 5
done
