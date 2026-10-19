import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
"""
SmartAPI health check — run this BEFORE trusting the integration.

    python check_smartapi.py            # full check
    python check_smartapi.py RELIANCE.NS INFY.BO   # also test these symbols

Tests each layer in order and stops at the first failure with a
plain-language diagnosis:

  1. .env has all four SMARTAPI_* values
  2. required libraries import
  3. TOTP secret generates codes (catches "pasted the 6-digit code")
  4. login succeeds
  5. scrip master downloads and your symbols resolve to tokens
  6. live LTP fetch works
  7. historical daily candles come back, with depth report

Safe to run any time: it only READS data, never places orders.
"""

import sys
import datetime as dt

PASS, FAIL, WARN = "[ OK ]", "[FAIL]", "[WARN]"


def die(msg, fix):
    print(f"{FAIL} {msg}")
    print(f"       Fix: {fix}")
    sys.exit(1)


# ------------------------------------------------------------- 1. env
from app.core import envutil  # noqa: E402

keys = ("SMARTAPI_KEY", "SMARTAPI_CLIENT", "SMARTAPI_PIN",
        "SMARTAPI_TOTP_SECRET")
missing = [k for k in keys if not envutil.get(k)]
if missing:
    die(f".env missing: {', '.join(missing)}",
        "fill them in .env (no quotes, no spaces around =) and re-run")
print(f"{PASS} .env has all four SMARTAPI_* values")

# ------------------------------------------------------- 2. libraries
try:
    import pyotp
    from SmartApi import SmartConnect
except ImportError as e:
    die(f"library import failed: {e}",
        "pip install smartapi-python pyotp  (if SmartApi still fails, "
        "try: pip install smartapi)")
print(f"{PASS} smartapi-python and pyotp import")

# ------------------------------------------------------------ 3. TOTP
secret = envutil.get("SMARTAPI_TOTP_SECRET").strip()
if secret.isdigit() and len(secret) <= 8:
    die("SMARTAPI_TOTP_SECRET looks like a 6-digit code, not the secret",
        "you pasted a rotating code; go to "
        "smartapi.angelbroking.com/enable-totp and copy the LONG base32 "
        "string (letters A-Z, digits 2-7)")
try:
    code = pyotp.TOTP(secret).now()
except Exception as e:
    die(f"TOTP secret invalid: {e}",
        "the secret must be base32 (A-Z, 2-7). Re-run enable-totp and "
        "copy the text version of the QR")
print(f"{PASS} TOTP secret valid (current code: {code})")

# ----------------------------------------------------------- 4. login
api = SmartConnect(api_key=envutil.get("SMARTAPI_KEY"))
try:
    resp = api.generateSession(
        envutil.get("SMARTAPI_CLIENT"), envutil.get("SMARTAPI_PIN"),
        pyotp.TOTP(secret).now())
except Exception as e:
    die(f"login threw an exception: {e}",
        "check your internet connection; if the error mentions totp, "
        "sync your system clock (Settings > Time & Language > Sync now)")
if not resp.get("status"):
    msg = str(resp.get("message", "")).lower()
    if "totp" in msg:
        fix = ("clock drift breaks TOTP — sync your Windows clock; if it "
               "persists, re-run enable-totp for a fresh secret")
    elif "password" in msg or "credential" in msg or "invalid" in msg:
        fix = ("SMARTAPI_CLIENT must be your trading Client Code (like "
               "A123456) and SMARTAPI_PIN the 4-digit trading PIN — not "
               "the SmartAPI portal password")
    else:
        fix = "read the message above; post it on the SmartAPI forum if unclear"
    die(f"login rejected: {resp.get('message')}", fix)
print(f"{PASS} login succeeded (client {envutil.get('SMARTAPI_CLIENT')})")

# ---------------------------------------------- 5. scrip master + symbols
from app.data_sources import smartapi_source as ss  # noqa: E402

test_symbols = sys.argv[1:] or ["RELIANCE.NS", "TCS.BO"]
try:
    ss._load_scrips()
except Exception as e:
    die(f"scrip master download failed: {e}",
        "this is a ~35 MB download from margincalculator.angelone.in; "
        "check your connection/firewall and re-run")
print(f"{PASS} scrip master loaded "
      f"({len(ss._scrips['nse'])} NSE / {len(ss._scrips['bse'])} BSE scrips)")
for sym in test_symbols:
    found = ss.resolve_token(sym)
    if found:
        print(f"{PASS}   {sym} -> {found[0]} token {found[1]}")
    else:
        print(f"{WARN}   {sym} not in scrip master — SmartAPI cannot "
              f"serve this one; check the spelling on angelone.in")

# ------------------------------------------------------------- 6. LTP
sym = test_symbols[0]
found = ss.resolve_token(sym)
if found:
    exch, token = found
    trading_symbol = sym.split(".")[0] + ("-EQ" if exch == "NSE" else "")
    try:
        q = api.ltpData(exch, trading_symbol, token)
        ltp = (q.get("data") or {}).get("ltp")
        if ltp:
            print(f"{PASS} live quote: {sym} LTP = {ltp}")
        else:
            print(f"{WARN} LTP call returned no price: {q.get('message')}")
    except Exception as e:
        print(f"{WARN} LTP call failed: {e} (quotes may still work in-app "
              f"— its symbol mapping differs slightly)")

# ------------------------------------------------------- 7. historical
    start = dt.date.today() - dt.timedelta(days=3650)
    try:
        df = ss.fetch_history(sym, years=10, progress=lambda m: None)
    except Exception as e:
        die(f"historical fetch failed: {e}",
            "if the message mentions rate limits, wait a minute and re-run; "
            "otherwise paste this error when asking for help")
    if df is None or df.empty:
        die(f"historical fetch returned nothing for {sym}",
            "try after market close; if it persists for every symbol, "
            "check the app was created as Market Feeds or Trading type")
    print(f"{PASS} historical: {len(df)} daily candles for {sym}")
    print(f"       earliest: {df.index[0].date()}  "
          f"latest: {df.index[-1].date()}")
    if len(df) < 500:
        print(f"{WARN} that's under ~2 years — this scrip's data on Angel "
              f"One is shallow; test your other symbols too")

print()
print("All layers working. Fill the same .env on the app machine, restart")
print("uvicorn, and hit Refresh data — shallow stocks will now say")
print("'(SmartAPI)' in the refresh log.")
