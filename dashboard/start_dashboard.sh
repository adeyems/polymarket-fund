#!/bin/bash
# Secure Read-Only Dashboard Launcher
# Binds to 127.0.0.1 ONLY — never exposes ports externally
set -e

cd "$(dirname "$0")/.."
mkdir -p dashboard/cache

# Activate venv if it exists
if [ -f .venv_local/bin/activate ]; then
    source .venv_local/bin/activate
fi

echo "Starting Sovereign Hive Dashboard (localhost-only)..."
python3 -m dashboard.server
