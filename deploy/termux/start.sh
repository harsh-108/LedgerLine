#!/data/data/com.termux/files/usr/bin/bash
# Run the server in the foreground on all interfaces (Ctrl-C stops it).
# Env overrides: APP_DIR, PORT, TZ
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
PORT="${PORT:-8000}"
export TZ="${TZ:-Asia/Kolkata}"          # the refresh scheduler uses local time
export PYTHONUNBUFFERED=1
cd "$APP_DIR/backend" || { echo "missing $APP_DIR/backend"; exit 1; }
termux-wake-lock 2>/dev/null || true       # keep the CPU awake while serving
# No --reload: watchfiles + a second process doubles memory and gets killed on phones.
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 --log-level info
