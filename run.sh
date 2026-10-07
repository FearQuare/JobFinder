#!/usr/bin/env bash
# Start JobFinder on http://127.0.0.1:8765 (first run sets everything up).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ (or: brew install python)." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is required (found $("$PY" --version 2>&1))." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "→ Creating virtual environment (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

REQ_HASH="$(cat requirements.txt | shasum | cut -d' ' -f1)"
if [ ! -f .venv/.req-hash ] || [ "$(cat .venv/.req-hash)" != "$REQ_HASH" ]; then
  echo "→ Installing dependencies (first time takes 1–3 minutes)…"
  # The pip bundled with the venv can be older than the one that filled your pip download cache,
  # which makes it print "Cache entry deserialization failed" for every cached file. Upgrading pip
  # without the cache avoids that; the new pip then reads the cache normally.
  python -m pip install --quiet --disable-pip-version-check --no-cache-dir --upgrade pip
  python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  echo "$REQ_HASH" > .venv/.req-hash
fi

# Browser used for the optional LinkedIn sign-in. If Google Chrome is installed the app uses it,
# otherwise it needs Playwright's own Chromium (downloaded once, ~150 MB).
if [ ! -d "/Applications/Google Chrome.app" ] && [ ! -f .venv/.chromium-installed ]; then
  echo "→ Installing the browser used for LinkedIn sign-in (one time)…"
  if python -m playwright install chromium; then touch .venv/.chromium-installed; else
    echo "  (Skipped — LinkedIn sign-in won't work until this succeeds. Everything else does.)"; fi
fi

URL="http://127.0.0.1:${PORT}"
echo "→ JobFinder running at ${URL}  (Ctrl+C to stop)"
( sleep 2; command -v open >/dev/null && open "$URL" || true ) &
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
