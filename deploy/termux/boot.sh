#!/data/data/com.termux/files/usr/bin/bash
# Installed as ~/.termux/boot/ledgerline.sh — Termux:Boot runs it after every reboot.
# Supervises two things, each restarted 10 s after it dies:
#   1. the server (uvicorn)            log: data/server.log
#   2. the ngrok tunnel to port 8000   log: data/ngrok.log
# Safe to run again: a supervisor that is already alive is left alone, so
# update.sh / install-boot.sh never start a second copy of either.
# Env overrides: APP_DIR, NGROK_URL (your reserved ngrok domain, or put it in .env), NGROK_BIN, PORT.
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
PORT="${PORT:-8000}"
DATA="$APP_DIR/data"
LOG="$DATA/server.log"
NGROK_LOG="$DATA/ngrok.log"
mkdir -p "$DATA"

# The reserved ngrok domain is yours, so it is not written in this file (it
# is public on GitHub). Taken from, in order: the environment, a
# NGROK_URL=... line in .env, data/ngrok_url, or (once, for phones set up
# before this change) the domain the tunnel last used, read back from
# ngrok.log and saved to data/ngrok_url.
NGROK_URL="${NGROK_URL:-}"
if [ -z "$NGROK_URL" ] && [ -f "$APP_DIR/.env" ]; then
  NGROK_URL="$(sed -n 's/^NGROK_URL=//p' "$APP_DIR/.env" | tail -n 1 \
    | sed 's/[[:space:]]#.*//' | tr -d "\r\"' ")"
fi
if [ -z "$NGROK_URL" ] && [ -f "$DATA/ngrok_url" ]; then
  NGROK_URL="$(tr -d '\r\n ' < "$DATA/ngrok_url")"
fi
if [ -z "$NGROK_URL" ]; then
  NGROK_URL="$(cat "$NGROK_LOG.1" "$NGROK_LOG" 2>/dev/null \
    | sed -n 's|.*starting https://\([^ ]*\) ->.*|\1|p' | tail -n 1)"
  [ -n "$NGROK_URL" ] && echo "$NGROK_URL" > "$DATA/ngrok_url"
fi
NGROK_URL="${NGROK_URL#https://}"
termux-wake-lock

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

# ---------------------------------------------------------------- server
if alive "$DATA/supervisor.pid"; then
  echo "server supervisor already running"
else
  # keep at most ~2 old logs
  [ -f "$LOG.1" ] && mv -f "$LOG.1" "$LOG.2"
  [ -f "$LOG" ] && mv -f "$LOG" "$LOG.1"
  # Detached from the terminal: SIGHUP ignored (inherited by uvicorn) and
  # no stdio tied to the session, so closing the Termux tab that ran
  # update.sh / install-boot.sh no longer takes the server down with it.
  (
    trap '' HUP
    while true; do
      echo "[supervisor] $(date) starting" >> "$LOG"
      "$APP_DIR/deploy/termux/start.sh" >> "$LOG" 2>&1
      rc=$?                     # before $(date), which would reset $?
      echo "[supervisor] $(date) exited rc=$rc — restart in 10 s" >> "$LOG"
      sleep 10
    done
  ) </dev/null >/dev/null 2>&1 &
  echo $! > "$DATA/supervisor.pid"
  echo "server supervisor started"
fi

# ---------------------------------------------------------------- ngrok
# On PATH, or a binary downloaded into the home folder (NGROK_BIN overrides).
NGROK_BIN="${NGROK_BIN:-$(command -v ngrok 2>/dev/null)}"
for c in "$HOME/ngrok" "$HOME/bin/ngrok" "$HOME/.local/bin/ngrok"; do
  [ -z "$NGROK_BIN" ] && [ -x "$c" ] && NGROK_BIN="$c"
done
if [ -z "$NGROK_BIN" ]; then
  echo "ngrok not found (set NGROK_BIN=/path/to/ngrok) — tunnel not supervised"
elif [ -z "$NGROK_URL" ]; then
  echo "no ngrok domain: add NGROK_URL=your-name.ngrok-free.dev to $APP_DIR/.env — tunnel not supervised"
elif alive "$DATA/ngrok-supervisor.pid"; then
  echo "ngrok supervisor already running"
else
  [ -f "$NGROK_LOG" ] && mv -f "$NGROK_LOG" "$NGROK_LOG.1"
  # ngrok >= 3.16 takes --url; older agents only know --domain
  if "$NGROK_BIN" http --help 2>&1 | grep -q -- '--url'; then
    FLAG="--url=$NGROK_URL"
  else
    FLAG="--domain=$NGROK_URL"
  fi
  (
    trap '' HUP                 # same detaching as the server loop
    while true; do
      # An ngrok started by hand still holds the domain: wait for it to
      # go, rather than fail to claim the domain every 10 s.
      if pgrep -x ngrok >/dev/null 2>&1; then sleep 30; continue; fi
      echo "[ngrok-supervisor] $(date) starting https://$NGROK_URL -> :$PORT" >> "$NGROK_LOG"
      "$NGROK_BIN" http "$FLAG" "$PORT" --log=stdout --log-level=warn >> "$NGROK_LOG" 2>&1
      rc=$?
      echo "[ngrok-supervisor] $(date) exited rc=$rc — restart in 10 s" >> "$NGROK_LOG"
      sleep 10
    done
  ) </dev/null >/dev/null 2>&1 &
  echo $! > "$DATA/ngrok-supervisor.pid"
  echo "ngrok supervisor started (https://$NGROK_URL)"
fi
