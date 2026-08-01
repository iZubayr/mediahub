#!/bin/bash
set -euo pipefail

# Run on the AlwaysData server by GitHub Actions over SSH after every push
# to main. Safe to run by hand too: `bash deploy.sh`

cd /home/zubayr/mediahub

echo "== Pulling latest code =="
git fetch origin main
git reset --hard origin/main

echo "== Checking virtual environment =="
if [ ! -d ".venv" ]; then
    echo "== .venv not found. Creating a new virtual environment... =="
    python3 -m venv .venv
fi

echo "== Installing dependencies =="
.venv/bin/python -m pip install -q -r requirements.txt

echo "== Restarting standalone service (if running) =="
# The recommended run mode: one Service running app.standalone (polling +
# worker together, no separate webhook Site needed). AlwaysData restarts
# Services automatically once the old process exits.
pkill -f "python -m app.standalone" || true

echo "== Restarting webhook Site (if running) =="
# Only relevant if you're using webhook mode instead of standalone.
pkill -f "uvicorn app.webhook" || true

echo "== Restarting worker Service (if running) =="
# Only relevant if you're using webhook mode instead of standalone.
pkill -f "python -m app.worker" || true

echo "== Waiting for restart =="
sleep 5

echo "== Health check (webhook mode only) =="
if curl -fsS -m 5 "https://zubayr.alwaysdata.net/health" > /dev/null 2>&1; then
  echo "Webhook /health OK"
else
  echo "No webhook Site responding on /health -- this is expected if you're running standalone mode instead. Check the 'mediahub' Service logs in the AlwaysData dashboard to confirm it restarted cleanly."
fi

echo "== Deploy complete =="
