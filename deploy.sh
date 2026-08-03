#!/bin/bash
set -uo pipefail
# Note: intentionally NOT using `set -e` at the top level. Instead, each
# critical step below checks its own exit code explicitly and exits with a
# clear error message. This avoids the failure mode where a single
# non-essential command (e.g. pkill finding no matching process, which is
# normal and expected) silently aborts the entire deploy with no
# indication of which step actually failed — GitHub Actions would only
# show "exit code 1" with no further detail.

# Run on the AlwaysData server by GitHub Actions over SSH after every push
# to main. Safe to run by hand too: `bash deploy.sh`

cd /home/zubayr/mediahub || { echo "FATAL: /home/zubayr/mediahub not found"; exit 1; }

echo "== Pulling latest code =="
if ! git fetch origin main; then
    echo "FATAL: git fetch failed"
    exit 1
fi
if ! git reset --hard origin/main; then
    echo "FATAL: git reset failed"
    exit 1
fi
echo "Now at commit: $(git rev-parse --short HEAD)"

echo "== Checking virtual environment =="
if [ ! -d ".venv" ]; then
    echo ".venv not found, creating a new virtual environment..."
    if ! python3 -m venv .venv; then
        echo "FATAL: venv creation failed"
        exit 1
    fi
fi

echo "== Installing dependencies =="
if ! .venv/bin/python -m pip install -q --upgrade pip; then
    echo "WARNING: pip self-upgrade failed, continuing with existing pip"
fi
if ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "FATAL: pip install -r requirements.txt failed"
    echo "Re-running verbosely for diagnostics:"
    .venv/bin/python -m pip install -r requirements.txt
    exit 1
fi
echo "Dependencies installed OK"

echo "== Restarting standalone service (if running) =="
# The recommended run mode: one Service running app.standalone (polling +
# worker together, no separate webhook Site needed). AlwaysData restarts
# Services automatically once the old process exits. pkill exits non-zero
# when it finds no matching process (e.g. you're not using this mode yet)
# — that's expected and not a failure, hence `|| true`.
pkill -f "python -m app.standalone" 2>/dev/null || true

echo "== Restarting webhook Site (if running) =="
# Only relevant if you're using webhook mode instead of standalone.
pkill -f "uvicorn app.webhook" 2>/dev/null || true

echo "== Restarting worker Service (if running) =="
# Only relevant if you're using webhook mode instead of standalone.
pkill -f "python -m app.worker" 2>/dev/null || true

echo "== Waiting for restart =="
sleep 5

echo "== Health check (webhook mode only) =="
if curl -fsS -m 5 "https://zubayr.alwaysdata.net/health" > /dev/null 2>&1; then
  echo "Webhook /health OK"
else
  echo "No webhook Site responding on /health -- this is expected if you're running standalone mode instead. Check the 'mediahub' Service logs in the AlwaysData dashboard to confirm it restarted cleanly."
fi

echo "== Deploy complete =="
exit 0
