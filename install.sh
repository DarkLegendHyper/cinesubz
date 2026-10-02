#!/bin/bash
# Quick install script for CineSubz scraper + Telegram bot
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Install complete."
echo ""
echo "CLI test:  python cli.py latest"
echo "Bot:       BOT_TOKEN=YOUR_TOKEN python bot.py"
echo ""
