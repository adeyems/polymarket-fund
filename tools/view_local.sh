#!/bin/bash

# Ensure we are in the project root
cd "$(dirname "$0")/.." || exit

# Create a local virtual environment if it doesn't exist
if [ ! -d ".venv_local" ]; then
    echo "📦 Creating local virtual environment (.venv_local)..."
    python3 -m venv .venv_local
fi

# Activate the virtual environment
source .venv_local/bin/activate

# Check if dependencies are installed, if not, install them
if ! pip show py-clob-client > /dev/null 2>&1; then
    echo "⬇️ Installing required libraries (py-clob-client, curl-cffi, web3, python-dotenv)..."
    pip install py-clob-client curl-cffi web3 python-dotenv
else
    echo "✅ Dependencies already installed."
fi

# Run the Python viewer script
echo "🚀 Running Position Viewer..."
python3 tools/view_position.py
