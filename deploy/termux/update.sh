#!/data/data/com.termux/files/usr/bin/bash
# Apply an update over ~/ledgerline and restart the server. The zip can be
# either a bundle of changed files (root-relative paths) or a plain zip of
# the whole project folder; only backend/, scripts/, deploy/termux/ and
# frontend-react/dist/ are taken from it. data/ (your database, logs) and
# .env (your keys) on the phone are never touched.
#
#   bash ~/ledgerline/deploy/termux/update.sh ~/storage/downloads/ledgerline-update.zip
#
# What it does: stop server -> back up current code -> unpack -> import
# check -> start. If the import check fails, the backup is restored and
# the old server comes back, so a bad bundle cannot leave the phone down.
# Run from a temporary, CR-stripped copy: this file gets replaced by the
# bundle while it is still executing, and bash reads scripts as it goes.
# (Single line with the brace closed before a comment so it parses even
# when the file itself has Windows line endings.)
[ -n "${LEDGERLINE_UPDATE_COPY:-}" ] || { T="$(mktemp)"; sed 's/\r$//' "$0" > "$T"; LEDGERLINE_UPDATE_COPY=1 exec bash "$T" "$@"; } # re-exec
set -uo pipefail
trap 'rm -f "$0"' EXIT
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
ZIP="${1:-$HOME/storage/downloads/ledgerline-update.zip}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$APP_DIR/data/code-backup-$STAMP.tar.gz"

[ -f "$ZIP" ] || { echo "!! bundle not found: $ZIP"; exit 1; }
[ -d "$APP_DIR/backend" ] || { echo "!! $APP_DIR/backend missing — is APP_DIR right?"; exit 1; }
command -v unzip >/dev/null 2>&1 || pkg install -y unzip

echo "== 1/5  checking the bundle"
LIST="$(unzip -Z1 "$ZIP")" || { echo "!! not a zip file: $ZIP"; exit 1; }
# A bundle may be either the changed files with root-relative paths, or a
# plain zip of the whole project folder (share_1/backend/..., possibly with
# data/, .env and node_modules inside). Everything but backend/, scripts/,
# deploy/termux/ and frontend-react/dist/ is ignored, so your database and
# keys on the phone are never overwritten.
TOP=""
if ! grep -qE '^(backend|frontend-react|deploy|scripts)/' <<< "$LIST"; then
  TOP="$(grep -oE '^[^/]+/' <<< "$LIST" | sort -u)"
  if [ "$(wc -l <<< "$TOP")" != 1 ] || ! grep -qE "^${TOP}(backend|frontend-react|deploy|scripts)/" <<< "$LIST"; then
    echo "!! this zip has no backend/ or frontend-react/dist/ in it (or more than one top folder)"; exit 1
  fi
  echo "   project zip with top folder '${TOP}' — will be stripped"
fi
grep -qE "^${TOP}(data/|\.env$)" <<< "$LIST" && echo "   note: bundle contains data/ or .env — ignored, the phone's own are kept"
grep -qE "^${TOP}frontend-react/node_modules/" <<< "$LIST" && echo "   note: bundle contains node_modules — ignored (leave it out next time, it is huge)"
HAS_BACKEND=0; HAS_DIST=0
grep -qE "^${TOP}backend/app/" <<< "$LIST" && HAS_BACKEND=1
grep -qE "^${TOP}frontend-react/dist/index.html$" <<< "$LIST" && HAS_DIST=1
echo "   backend: $([ $HAS_BACKEND = 1 ] && echo yes || echo no)   frontend build: $([ $HAS_DIST = 1 ] && echo yes || echo 'no (dist/ missing — run npm run build on the PC before zipping)')"
[ $HAS_BACKEND = 1 ] || [ $HAS_DIST = 1 ] || { echo "!! nothing to update in this zip"; exit 1; }

echo "== 2/5  stopping the server"
bash "$APP_DIR/deploy/termux/stop.sh" >/dev/null 2>&1 || true
pkill -f "uvicorn app.main:app" 2>/dev/null || true

echo "== 3/5  backing up current code to $BACKUP"
mkdir -p "$APP_DIR/data"
tar -czf "$BACKUP" -C "$APP_DIR" backend scripts deploy frontend-react/dist 2>/dev/null || true
ls -1t "$APP_DIR"/data/code-backup-*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f

echo "== 4/5  unpacking"
TMP="$APP_DIR/data/.update-tmp"; rm -rf "$TMP"; mkdir -p "$TMP"
unzip -o -q "$ZIP" "${TOP}backend/*" "${TOP}scripts/*" "${TOP}deploy/termux/*" "${TOP}frontend-react/dist/*" \
      -x "*/node_modules/*" "*__pycache__*" "*.pyc" -d "$TMP" 2>/dev/null || true
SRC="$TMP/$TOP"
for part in backend scripts deploy/termux; do
  if [ -d "$SRC/$part" ]; then mkdir -p "$APP_DIR/$part" && cp -r "$SRC/$part/." "$APP_DIR/$part/"; fi
done
if [ $HAS_DIST = 1 ] && [ -d "$SRC/frontend-react/dist" ]; then
  rm -rf "$APP_DIR/frontend-react/dist"                   # stale hashed assets go
  mkdir -p "$APP_DIR/frontend-react" && cp -r "$SRC/frontend-react/dist" "$APP_DIR/frontend-react/dist"
fi
rm -rf "$TMP"
find "$APP_DIR/backend" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
# bundles zipped on Windows can carry CRLF line endings, which break bash
sed -i 's/\r$//' "$APP_DIR"/deploy/termux/*.sh 2>/dev/null || true
chmod +x "$APP_DIR"/deploy/termux/*.sh 2>/dev/null || true
echo "   frontend now: $(ls "$APP_DIR"/frontend-react/dist/assets/*.js 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"

echo "== 5/5  import check"
if ! ( cd "$APP_DIR/backend" && ${PYTHON:-python} -c "import app.main; print('   app imports OK')" ); then
  echo "!! the updated app does not import — restoring the backup"
  BLIST="$(tar -tzf "$BACKUP" 2>/dev/null)"
  grep -q '^frontend-react/dist/' <<< "$BLIST" && rm -rf "$APP_DIR/frontend-react/dist"
  tar -xzf "$BACKUP" -C "$APP_DIR"
  if [ -f "$HOME/.termux/boot/ledgerline.sh" ]; then
    cp "$APP_DIR/deploy/termux/boot.sh" "$HOME/.termux/boot/ledgerline.sh"
    bash "$HOME/.termux/boot/ledgerline.sh"
  fi
  echo "!! old version is back. Send the error above to whoever made the bundle."
  exit 1
fi

if [ -f "$HOME/.termux/boot/ledgerline.sh" ]; then
  # the boot script is a copy made by install-boot.sh: keep it current
  cp "$APP_DIR/deploy/termux/boot.sh" "$HOME/.termux/boot/ledgerline.sh"
  chmod +x "$HOME/.termux/boot/ledgerline.sh"
  bash "$HOME/.termux/boot/ledgerline.sh"
  echo
  echo "Updated and restarted under the supervisor. Watch it come up with:"
  echo "   tail -f $APP_DIR/data/server.log"
else
  echo
  echo "Updated. Start it with:   bash $APP_DIR/deploy/termux/start.sh"
fi
echo "ngrok was left running (the boot script supervises it; 'stop.sh all' stops it)."
