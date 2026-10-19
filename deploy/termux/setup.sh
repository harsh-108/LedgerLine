#!/data/data/com.termux/files/usr/bin/bash
# Ledgerline — one-time setup inside Termux (F-Droid build, Android 7+).
# Safe to re-run. Usage:
#     bash ~/ledgerline/deploy/termux/setup.sh
set -euo pipefail
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
TUR_PYPI="https://termux-user-repository.github.io/pypi/"

echo "== 1/6  Termux packages"
pkg update -y
pkg install -y python python-pip git openssl libxml2 libxslt libffi zlib \
               clang make pkg-config tzdata

echo "== 2/6  pip: use the Termux User Repository wheel index"
mkdir -p "$HOME/.config/pip"
cat > "$HOME/.config/pip/pip.conf" <<CONF
[global]
extra-index-url = $TUR_PYPI
CONF
pip install --upgrade pip wheel setuptools

echo "== 3/6  compiled libraries: prebuilt wheels only (never compile these on a phone)"
# pydantic-core is pulled in by FastAPI; numpy/pandas/scipy/sklearn/lxml by the app + yfinance.
pip install --only-binary=:all: "numpy<3" "pandas<3" scipy scikit-learn lxml pydantic-core pydantic

echo "== 4/6  pure-python deps"
# plain uvicorn on purpose: uvicorn[standard] wants uvloop/httptools which need compiling.
# The web stack is pinned to the versions tested together (backend/requirements.txt):
# a newer starlette under an older fastapi stops the server from starting.
# The compiled libraries above stay unpinned: only some versions have Android wheels.
pip install "fastapi==0.143.0" "starlette==1.7.0" "uvicorn==0.34.0" \
            "python-multipart==0.0.20" requests plotly pypdf openpyxl

echo "== 5/6  yfinance without curl_cffi (no Android build of curl-impersonate)"
# yfinance >= 0.2.6x falls back to plain requests when curl_cffi is missing.
pip install --no-deps yfinance
python - <<'PY' > "$HOME/.yf-reqs.txt"
import importlib.metadata as m
for r in (m.requires("yfinance") or []):
    r = r.split(";")[0].strip()
    if r.lower().replace("-", "_").startswith("curl_cffi"):
        continue
    print(r)
PY
pip install -r "$HOME/.yf-reqs.txt"

echo "== 6/6  app files"
if [ ! -d "$APP_DIR/backend" ]; then
  echo "!! $APP_DIR/backend not found. Copy the project to $APP_DIR first (see TERMUX.md)."; exit 1
fi
mkdir -p "$APP_DIR/data"
chmod +x "$APP_DIR"/deploy/termux/*.sh
[ -f "$APP_DIR/.env" ] || { cp "$APP_DIR/.env.example" "$APP_DIR/.env"; echo "   created $APP_DIR/.env — edit it (nano $APP_DIR/.env)"; }

echo
echo "== import check"
cd "$APP_DIR/backend" && python -c "import app.main; print('app imports OK')"
echo
echo "Done. Start it with:   bash $APP_DIR/deploy/termux/start.sh"
echo "Autostart at boot:     bash $APP_DIR/deploy/termux/install-boot.sh"
