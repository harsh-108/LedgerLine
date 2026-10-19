"""
NSE official-site adapter (via the nsepython library).

Adds two things Yahoo cannot provide:
  1. VALIDATION — compares your stored closes against NSE's own numbers,
     so silent Yahoo glitches get caught instead of trusted.
  2. DELIVERY % — the share of traded quantity actually taken as delivery.
     High delivery on an up-move suggests real accumulation, not intraday
     churn. Yahoo has no equivalent field.

Honesty notes:
  - nsepython scrapes nseindia.com; it works well but breaks for a few
    days whenever NSE redesigns. Every call here is wrapped so failures
    degrade to "no data", never crashes.
  - NSE rate-limits bursts. We sleep between symbols; a 50-stock sync
    takes a couple of minutes by design. Run it once daily, after close.
  - lastPrice is live during market hours, so validation is only
    apples-to-apples AFTER market close and AFTER your daily refresh.

Setup:  pip install nsepython
"""

import time

import requests

from app.core import database as db

SLEEP_BETWEEN = 1.6      # be polite; NSE blocks bursts
TOLERANCE_PCT = 0.75     # closes within this are "matching"

_BASE = "https://www.nseindia.com"
_HEADERS = {
    # NSE serves /api/ only to requests that look like its own web app:
    # a real browser UA, an Accept-Language, and cookies obtained from a
    # prior visit to the site. Brotli is deliberately left out of
    # Accept-Encoding so `requests` can decode the body without the
    # optional brotli package.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": _BASE + "/",
    "Connection": "keep-alive",
}
_SESSION_TTL = 600       # NSE cookies go stale; re-warm every 10 min

_sess = None
_sess_at = 0.0
_client_name = "requests"
last_error = None        # human-readable reason for the most recent failure


class _HTTPErr(RuntimeError):
    def __init__(self, code, body=""):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}")


def available():
    return True          # direct fetch needs only `requests`


def _new_client():
    """Prefer curl_cffi impersonating Chrome. NSE's Akamai edge blocks on
    TLS fingerprint since 2024, so plain `requests` gets an
    'Access Denied' page no matter what headers it sends. yfinance already
    depends on curl_cffi, so it is normally installed."""
    global _client_name
    try:
        from curl_cffi import requests as cffi
        s = cffi.Session(impersonate="chrome")
        _client_name = "curl_cffi"
    except ImportError:
        s = requests.Session()
        _client_name = "requests"
    s.headers.update(_HEADERS)
    return s


def _check(r):
    if r.status_code >= 400:
        body = ""
        try:
            body = r.text[:200]
        except Exception:
            pass
        raise _HTTPErr(r.status_code, body)
    return r


def _session(force=False):
    """Warm session: hit the homepage once to collect the cookies NSE's
    API checks for, then reuse the session for subsequent calls."""
    global _sess, _sess_at
    if _sess is not None and not force and time.time() - _sess_at < _SESSION_TTL:
        return _sess
    s = _new_client()
    _check(s.get(_BASE + "/", timeout=12))
    _sess, _sess_at = s, time.time()
    return s


def _api(path, params):
    """GET /api/<path>; re-warm cookies once on 401/403 and retry."""
    s = _session()
    url = f"{_BASE}/api/{path}"
    sym = (params or {}).get("symbol")
    if sym:
        try:   # visiting the quote page first sets extra cookies
            s.get(f"{_BASE}/get-quotes/equity", params={"symbol": sym},
                  timeout=12)
        except Exception:
            pass
    r = s.get(url, params=params, timeout=12,
              headers={"Referer": f"{_BASE}/get-quotes/equity?symbol={sym}"}
              if sym else None)
    if r.status_code in (401, 403):
        s = _session(force=True)
        r = s.get(url, params=params, timeout=12)
    _check(r)
    ctype = r.headers.get("content-type", "") or ""
    if "json" not in ctype:
        raise RuntimeError(f"non-JSON reply ({ctype.split(';')[0] or 'unknown'}) "
                           "— usually a block page or a corporate proxy")
    return r.json()


_ARCHIVE = ("https://nsearchives.nseindia.com/products/content/"
            "sec_bhavdata_full_{ddmmyyyy}.csv")
_bhav_cache = {}         # "YYYY-MM-DD" -> {SYMBOL: row}


def _parse_bhavcopy(text):
    """The 'full bhavcopy' CSV: one row per symbol+series with close and
    delivery %. NSE pads every field with a leading space, hence strip."""
    import csv
    import io
    rows = {}
    rdr = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    for r in rdr:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if r.get("SERIES") not in ("EQ", "BE", "BZ"):
            continue
        sym = r.get("SYMBOL", "").upper()
        if not sym:
            continue

        def num(key):
            v = r.get(key, "")
            try:
                return float(v.replace(",", "")) if v not in ("", "-") else None
            except ValueError:
                return None
        rows[sym] = {"close": num("CLOSE_PRICE"),
                     "prev_close": num("PREV_CLOSE"),
                     "last": num("LAST_PRICE"),
                     "delivery_pct": num("DELIV_PER"),
                     "date": r.get("DATE1", "")}
    return rows


def _file_date(rows):
    """Most common DATE1 in the file ('25-Sep-2026') as ISO, else None."""
    import datetime as dt
    from collections import Counter
    c = Counter(r.get("date", "") for r in rows.values())
    raw, _ = c.most_common(1)[0] if c else ("", 0)
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def fetch_bhavcopy(date_iso=None, lookback=6):
    """Download NSE's daily full bhavcopy (close + delivery % for every
    stock). Walks back over weekends/holidays. Returns (date_iso, rows)
    or (None, None) with the reason in `last_error`."""
    import datetime as dt
    global last_error
    d = dt.date.fromisoformat(date_iso[:10]) if date_iso else dt.date.today()
    errors = []
    for _ in range(lookback):
        key = d.isoformat()
        if key in _bhav_cache:
            return key, _bhav_cache[key]
        url = _ARCHIVE.format(ddmmyyyy=d.strftime("%d%m%Y"))
        try:
            r = _new_client().get(url, timeout=25)
            if r.status_code == 200 and "SYMBOL" in r.text[:200]:
                rows = _parse_bhavcopy(r.text)
                if rows:
                    # Trust the date inside the file, not the URL: NSE's
                    # archive can answer a weekend/holiday URL with the
                    # last trading day's file.
                    actual = _file_date(rows) or key
                    _bhav_cache.clear()          # keep one day in memory
                    _bhav_cache[actual] = rows
                    last_error = None
                    return actual, rows
                errors.append(f"{key}: empty")
            else:
                errors.append(f"{key}: HTTP {r.status_code}")
        except Exception as e:
            errors.append(f"{key}: {e.__class__.__name__}")
        d -= dt.timedelta(days=1)
    last_error = "bhavcopy: " + "; ".join(errors)
    return None, None


def _fetch_direct(symbol_base):
    q = _api("quote-equity", {"symbol": symbol_base})
    info = (q or {}).get("priceInfo") or {}
    last = info.get("lastPrice")
    if last is None:
        raise RuntimeError("no priceInfo in reply (unknown symbol?)")
    dp = None
    try:
        # Delivery % lives on the trade_info section, not the main quote.
        t = _api("quote-equity", {"symbol": symbol_base,
                                  "section": "trade_info"})
        raw = ((t or {}).get("securityWiseDP") or {}).get(
            "deliveryToTradedQuantity")
        if raw not in (None, "", "-"):
            dp = float(str(raw).replace(",", ""))
    except Exception:
        pass                                  # delivery is optional
    prev = info.get("previousClose")
    return {"last": float(str(last).replace(",", "")),
            "prev_close": float(str(prev).replace(",", "")) if prev else None,
            "delivery_pct": dp}


def _fetch_nsepython(symbol_base):
    from nsepython import nse_eq              # optional fallback
    q = nse_eq(symbol_base)
    info = (q or {}).get("priceInfo") or {}
    last = info.get("lastPrice")
    if last is None:
        raise RuntimeError("nsepython returned no priceInfo")
    prev = info.get("previousClose")
    return {"last": float(last), "prev_close": float(prev) if prev else None,
            "delivery_pct": None}


def fetch_quote(symbol_base):
    """Return {'last','prev_close','delivery_pct'} or None. Never raises;
    the reason for a None is left in `last_error`."""
    global last_error
    errors = []
    for fn in (_fetch_direct, _fetch_nsepython):
        try:
            out = fn(symbol_base)
            last_error = None
            return out
        except ImportError:
            continue
        except _HTTPErr as e:
            hint = ""
            if e.code == 403 and "Access Denied" in e.body:
                hint = (" (Akamai block: TLS fingerprint or proxy; "
                        f"client={_client_name})")
            errors.append(f"{fn.__name__[7:]}: HTTP {e.code}{hint}")
        except Exception as e:
            errors.append(f"{fn.__name__[7:]}: {e.__class__.__name__}: "
                          f"{str(e)[:120]}")
    last_error = "; ".join(errors) or "unknown"
    return None


def sync(progress=lambda m: None, max_symbols=None):
    """For each stock in the watchlist: fetch NSE quote, store delivery %,
    and compare NSE's price with our stored last close.

    Returns dict: checked, matched, mismatches[], no_data[], delivery_saved.
    """
    if not available():
        return {"error": "NSE adapter unavailable"}

    stocks = [r for r in db.get_watchlist("stock")]
    if max_symbols:
        stocks = stocks[:max_symbols]

    result = {"checked": 0, "matched": 0, "mismatches": [],
              "no_data": [], "delivery_saved": 0, "source": None}
    last_date = db.last_price_date() or ""

    # Primary: one bhavcopy download for the latest date we hold prices
    # for. Fallback: NSE's per-symbol /api (needs the browser sensor
    # cookie, so it fails on most non-browser clients).
    bhav_date, bhav = fetch_bhavcopy(last_date or None)
    if bhav:
        result["source"] = f"bhavcopy {bhav_date}"
        progress(f"Using NSE bhavcopy for {bhav_date} ({len(bhav)} symbols)")
        if last_date and bhav_date != last_date[:10]:
            progress(f"note: our latest prices are {last_date[:10]}; "
                     f"comparing against NSE {bhav_date}")
    else:
        result["source"] = "per-symbol api"
        progress(f"bhavcopy unavailable ({last_error}); trying per-symbol API")

    for (_id, _t, symbol, _sc, label, _a) in stocks:
        base = symbol.split(".")[0]
        if bhav:
            row = bhav.get(base)
            q = ({"last": row["close"], "prev_close": row["prev_close"],
                  "delivery_pct": row["delivery_pct"]}
                 if row and row["close"] else None)
            if q is None:
                last_error_local = "not in bhavcopy (wrong ticker or not EQ series)"
        else:
            q = fetch_quote(base)
            last_error_local = last_error
            time.sleep(SLEEP_BETWEEN)
        if q is None:
            result["no_data"].append(base)
            progress(f"[--] {base}: no NSE data ({last_error_local})")
            continue
        result["checked"] += 1

        cmp_date = bhav_date if bhav else last_date
        if q["delivery_pct"] is not None and cmp_date:
            db.save_delivery(base, cmp_date, q["delivery_pct"])
            result["delivery_saved"] += 1

        ours = None
        if bhav:
            for d_, c_ in db.load_closes(symbol):
                if str(d_)[:10] == bhav_date:
                    ours = c_
                    break
        if ours is None:
            ours = db.last_close(symbol)
        if ours:
            diff_pct = abs(q["last"] / ours - 1) * 100
            if diff_pct <= TOLERANCE_PCT:
                result["matched"] += 1
                progress(f"[OK] {base}: ours {ours:,.2f} vs NSE "
                         f"{q['last']:,.2f} ({diff_pct:.2f}%)")
            else:
                result["mismatches"].append(
                    {"symbol": base, "ours": ours, "nse": q["last"],
                     "diff_pct": round(diff_pct, 2)})
                progress(f"[!!] {base}: ours {ours:,.2f} vs NSE "
                         f"{q['last']:,.2f} — {diff_pct:.1f}% apart")

    progress(f"Done: {result['matched']}/{result['checked']} matched, "
             f"{len(result['mismatches'])} mismatches, "
             f"{result['delivery_saved']} delivery figures saved.")
    return result