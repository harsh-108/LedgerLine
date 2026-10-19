#!/data/data/com.termux/files/usr/bin/bash
# Stop the server. The ngrok tunnel keeps running (update.sh relies on
# that, so the public URL never drops during an update).
#   bash stop.sh        server only
#   bash stop.sh all    server and the ngrok tunnel
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
PIDF="$APP_DIR/data/supervisor.pid"
if [ -f "$PIDF" ]; then kill "$(cat "$PIDF")" 2>/dev/null || true; rm -f "$PIDF"; fi
pkill -f "uvicorn app.main:app" 2>/dev/null || true
if [ "${1:-}" = "all" ]; then
  NPIDF="$APP_DIR/data/ngrok-supervisor.pid"
  if [ -f "$NPIDF" ]; then kill "$(cat "$NPIDF")" 2>/dev/null || true; rm -f "$NPIDF"; fi
  pkill -x ngrok 2>/dev/null || true
  termux-wake-unlock 2>/dev/null || true
  echo "stopped (server and ngrok)"
else
  echo "stopped (server; ngrok left running — 'stop.sh all' stops it too)"
fi
