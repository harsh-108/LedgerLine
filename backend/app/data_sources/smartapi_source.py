"""
Angel One SmartAPI as a HISTORICAL data source (daily candles).

Why this exists: Yahoo's coverage of Indian listings is patchy — many
.BO tickers and small/mid-caps return empty or shallow history. Angel
One's getCandleData endpoint serves exchange data for both NSE and BSE,
free, with the same credentials live.py already uses.

How it plugs in: downloader.download_ticker() falls back to
fetch_history() whenever Yahoo returns nothing (or too little) and the
four SMARTAPI_* keys are present in .env. The DataFrame returned here
is shaped exactly like yfinance's output, so db.save_prices() and
everything downstream (scanner, charts, ML, backtests) work unchanged.

Honesty notes:
  - ONE_DAY candles are limited to ~2000 days per request, so long
    histories are fetched in windows (handled below).
  - Angel One's own forum advises against the historical endpoint
    DURING market hours; run refreshes after close (which is already
    this app's cron pattern).
  - Depth varies by segment: NSE equities go back furthest; BSE-only
    scrips may have less history. Whatever the API returns is stored.
  - The session/token logic is shared with live.py's approach but kept
    self-contained here so either module works alone.

UNTESTED TEMPLATE against live credentials — same caveat as live.py.
Expect to debug once with your own keys.
"""

import datetime as dt
import json
import os
import threading
import time

import pandas as pd
import requests

from app.core import envutil

_SCRIPS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "scrips_cache.json")
_SCRIPS_TTL = 7 * 86400   # re-download the master weekly

SCRIP_MASTER_URL = ("https://margincalculator.angelone.in/"
                    "OpenAPI_File/files/OpenAPIScripMaster.json")

# Angel One publishes per-interval maximums; ONE_DAY = 2000 days/request.
DAY_WINDOW = 1900          # stay under the 2000-day cap with margin
SLEEP_BETWEEN_CALLS = 0.5  # historical API is rate-limited; be polite
MAX_YEARS = 25             # sanity cap when walking back through windows

_lock = threading.Lock()
_session = {"api": None, "created": 0.0}   # cached login (~valid for hours)
_scrips = {"nse": None, "bse": None}       # symbol -> token maps
_names = None                              # [(base, exch, name), ...] for search


def configured():
    return all(envutil.get(k) for k in
               ("SMARTAPI_KEY", "SMARTAPI_CLIENT", "SMARTAPI_PIN",
                "SMARTAPI_TOTP_SECRET"))


# ------------------------------------------------------------------ login
def _connect():
    """Return a logged-in SmartConnect, reusing a recent session."""
    with _lock:
        if _session["api"] and time.time() - _session["created"] < 4 * 3600:
            return _session["api"]
        try:
            import pyotp
            from SmartApi import SmartConnect
        except ImportError:
            raise RuntimeError("Run: pip install smartapi-python pyotp")
        api = SmartConnect(api_key=envutil.get("SMARTAPI_KEY"))
        totp = pyotp.TOTP(envutil.get("SMARTAPI_TOTP_SECRET")).now()
        resp = api.generateSession(
            envutil.get("SMARTAPI_CLIENT"), envutil.get("SMARTAPI_PIN"), totp
        )
        if not resp.get("status"):
            raise RuntimeError(f"SmartAPI login failed: {resp.get('message')}")
        _session.update(api=api, created=time.time())
        return api


# ----------------------------------------------------------- scrip master
def _load_scrips():
    """Download + cache the instrument master once per process.
    Builds two maps: NSE 'SYMBOL-EQ' and BSE 'SYMBOL' -> token."""
    with _lock:
        if _scrips["nse"] is not None:
            return
        master = None
        # disk cache first: one successful ~35 MB download serves a week
        try:
            if (os.path.exists(_SCRIPS_CACHE)
                    and time.time() - os.path.getmtime(_SCRIPS_CACHE)
                    < _SCRIPS_TTL):
                with open(_SCRIPS_CACHE) as f:
                    master = json.load(f)
        except Exception:
            master = None
        if master is None:
            # don't hammer Angel One on every keystroke after a failure
            if time.time() - _scrips.get("failed_at", 0) < 300:
                raise RuntimeError(_scrips.get("failed_msg", "scrip master "
                                   "download failed recently; retry later"))
            try:
                resp = requests.get(SCRIP_MASTER_URL, timeout=90,
                                    headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                text = resp.text.lstrip("\ufeff \n\r\t")
                master = json.loads(text)
                if not isinstance(master, list) or not master:
                    raise ValueError("unexpected scrip master format")
                try:
                    with open(_SCRIPS_CACHE, "w") as f:
                        json.dump(master, f)
                except Exception:
                    pass
            except Exception as e:
                # stale disk cache beats no cache at all
                try:
                    with open(_SCRIPS_CACHE) as f:
                        master = json.load(f)
                    if not isinstance(master, list) or not master:
                        raise ValueError("cache empty")
                except Exception:
                    try:
                        os.remove(_SCRIPS_CACHE)      # corrupt partial file
                    except Exception:
                        pass
                    _scrips["failed_at"] = time.time()
                    _scrips["failed_msg"] = (f"scrip master unavailable "
                                             f"({e.__class__.__name__}: "
                                             f"{str(e)[:80]})")
                    raise RuntimeError(_scrips["failed_msg"])
        nse, bse, names = {}, {}, []
        for row in master:
            seg, sym, tok = (row.get("exch_seg"), row.get("symbol"),
                             row.get("token"))
            if not (sym and tok):
                continue
            nm = (row.get("name") or "").upper()
            if seg == "NSE" and sym.endswith("-EQ"):
                nse[sym[:-3]] = tok
                names.append((sym[:-3], "NSE", nm))
            elif seg == "BSE":
                bse[sym] = tok
                names.append((sym, "BSE", nm))
        _scrips["nse"], _scrips["bse"] = nse, bse
        global _names
        _names = names


def resolve_token(symbol):
    """'RELIANCE.NS' / 'RELIANCE.BO' / bare -> (exchange, token) or None.
    Bare symbols try NSE first (deeper history), then BSE."""
    _load_scrips()
    base, _, suffix = symbol.upper().partition(".")
    order = {"NS": [("NSE", _scrips["nse"])],
             "BO": [("BSE", _scrips["bse"])]}.get(
        suffix, [("NSE", _scrips["nse"]), ("BSE", _scrips["bse"])])
    for exch, table in order:
        tok = table.get(base)
        if tok:
            return exch, tok
    return None


def has_symbol(symbol):
    """Cheap existence check for validation (no login needed)."""
    try:
        return resolve_token(symbol) is not None
    except Exception:
        return False


# ------------------------------------------------------------- historical
def _candles(api, exch, token, start: dt.date, end: dt.date):
    resp = api.getCandleData({
        "exchange": exch,
        "symboltoken": token,
        "interval": "ONE_DAY",
        "fromdate": start.strftime("%Y-%m-%d 09:00"),
        "todate": end.strftime("%Y-%m-%d 15:30"),
    })
    if not resp or not resp.get("status"):
        return []
    return resp.get("data") or []


def fetch_history(symbol, years=10, progress=lambda m: None):
    """Daily OHLCV as a yfinance-shaped DataFrame
    (Datetime index; Open/High/Low/Close/Volume columns), or None.

    Walks back in ≤DAY_WINDOW-day requests until `years` are covered or
    the API stops returning data (i.e. before listing / data start).
    """
    if not configured():
        return None
    found = resolve_token(symbol)
    if not found:
        progress(f"[--] {symbol}: not in Angel One scrip master")
        return None
    exch, token = found
    api = _connect()

    years = min(years, MAX_YEARS)
    target_start = dt.date.today() - dt.timedelta(days=int(years * 365.25))
    end = dt.date.today()
    rows = []
    empty_windows = 0
    while end > target_start and empty_windows < 2:
        start = max(target_start, end - dt.timedelta(days=DAY_WINDOW))
        try:
            chunk = _candles(api, exch, token, start, end)
        except Exception as e:
            progress(f"[WARN] SmartAPI {symbol} window {start}: {e}")
            chunk = []
        if chunk:
            rows = chunk + rows
            empty_windows = 0
        else:
            # nothing in this window — likely before the scrip existed;
            # allow one gap (data holes happen), then stop walking back
            empty_windows += 1
        end = start - dt.timedelta(days=1)
        time.sleep(SLEEP_BETWEEN_CALLS)

    if not rows:
        progress(f"[--] {symbol}: SmartAPI returned no candles ({exch})")
        return None

    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low",
                                     "Close", "Volume"])
    df["ts"] = pd.to_datetime(df["ts"].str[:10])
    df = (df.drop_duplicates("ts").set_index("ts").sort_index())
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    progress(f"[OK] {symbol}: {len(df)} rows via SmartAPI ({exch})")
    return df


def search_names(query, limit=10):
    """Search the scrip master by symbol prefix OR company/scheme name —
    every word of the query must appear in the name (so "groww defence"
    finds GROWW NIFTY INDIA DEFENCE ETF). Returns
    [{"symbol","name","exch"}], NSE listings first."""
    _load_scrips()
    q = query.strip().upper()
    if len(q) < 2:
        return []
    tokens = [t for t in q.split() if t]
    out, seen = [], set()

    def add(base, exch, name):
        sym = base + (".NS" if exch == "NSE" else ".BO")
        if sym in seen:
            return
        seen.add(sym)
        out.append({"symbol": sym, "name": name.title(), "exch": exch})

    # pass 1: symbol prefix; pass 2: all query words in the name
    for base, exch, name in _names:
        if base.startswith(tokens[0]):
            add(base, exch, name)
    for base, exch, name in _names:
        if len(out) >= limit * 2:
            break
        if all(t in name for t in tokens):
            add(base, exch, name)
    out.sort(key=lambda x: (x["exch"] != "NSE", len(x["symbol"])))
    return out[:limit]


def quote_depth(symbol):
    """Best-5 bid/ask depth via SmartAPI FULL quote mode. Live during
    market hours; needs credentials. UNTESTED TEMPLATE like the rest."""
    if not configured():
        return None
    found = resolve_token(symbol)
    if not found:
        return None
    exch, token = found
    api = _connect()
    resp = api.getMarketData("FULL", {exch: [token]})
    fetched = (resp or {}).get("data", {}).get("fetched") or []
    if not fetched:
        return None
    q = fetched[0]
    depth = q.get("depth") or {}
    return {
        "ltp": q.get("ltp"),
        "bids": [{"price": b.get("price"), "qty": b.get("quantity")}
                 for b in (depth.get("buy") or [])[:5]],
        "asks": [{"price": a.get("price"), "qty": a.get("quantity")}
                 for a in (depth.get("sell") or [])[:5]],
        "total_buy_qty": q.get("totBuyQuan"),
        "total_sell_qty": q.get("totSellQuan"),
    }
