#!/bin/bash
# Start the CineSubz WhatsApp bot
set -e
cd "$(dirname "$0")"

if [ ! -d node_modules ]; then
    echo "[setup] installing npm deps…"
    npm install
fi

# pick python: venv next to repo, else system python3
if [ -x "../.venv/bin/python" ]; then
    export PYTHON="../.venv/bin/python"
else
    export PYTHON="${PYTHON:-python3}"
fi

echo "[run] starting WhatsApp bot (QR will appear below on first run)…"
exec node index.js
