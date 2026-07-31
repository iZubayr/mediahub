#!/bin/bash
set -euo pipefail

# Run on the AlwaysData server by GitHub Actions over SSH after every push
# to main. Safe to run by hand too: `bash deploy.sh`

cd mediahub

echo "== Pulling latest code =="
git fetch origin main
git reset --hard origin/main

echo "== Installing dependencies =="
.venv/bin/python -m pip install -q -r requirements.txt

echo "== Restarting webhook (Site) =="
# Site processes on AlwaysData are auto-restarted by the platform once the
# old process exits; killing it is the standard way to pick up new code
# without going through the dashboard.
pkill -f "uvicorn app.webhook" || true

echo "== Restarting worker (Service) =="
pkill -f "python -m app.worker" || true

echo "== Waiting for restart =="
sleep 5

echo "== Health check =="
curl -fsS "https://zubayr.alwaysdata.net/health" && echo || {
  echo "Health check failed!" >&2
  exit 1
}

echo "== Deploy complete =="
