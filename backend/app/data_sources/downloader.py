"""
Download daily data for everything in the watchlist (stored in SQLite,
editable via the UI or these helper functions).

- Stocks + ETFs : Yahoo Finance via yfinance (free, no key)
- Mutual funds  : mfapi.in (free, official AMFI NAV data, no key)

CLI usage:
    python downloader.py                     # refresh everything
    python downloader.py --search "hdfc"     # find MF scheme codes
"""

import argparse
import sys
import time

import requests
import yfinance as yf

from app.core import config
from app.core import database as db
from app.data_sources import smartapi_source

MFAPI_BASE = "https://api.mfapi.in/mf"

# If Yahoo returns fewer rows than this, the history is considered too
# shallow to trust and SmartAPI (when configured) is tried as well.
MIN_GOOD_ROWS = 250


# Desktop UA on purpose: Yahoo answers 429 to Android and to python-
# requests' default UA (checked 2026-10-06), 200 to desktop Chrome.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def yahoo_chart(symbol, range_="10y"):
    """Daily history straight from Yahoo's chart API, split- and dividend-
    adjusted like yfinance's auto_adjust=True. Needs no cookie/crumb, so it
    keeps working where yfinance fails — notably on the Termux phone,
    which has no curl_cffi and gets rate-limited on yfinance's login dance.
    Returns a DataFrame (Open/High/Low/Close/Volume, IST dates) or None."""
    import pandas as pd
    last_err = None
    for host in ("query1", "query2"):
        try:
            r = requests.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"range": range_, "interval": "1d",
                        "includeAdjustedClose": "true", "events": "div,split"},
                headers={"User-Agent": _UA}, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            res = (r.json().get("chart") or {}).get("result") or []
            if not res or not res[0].get("timestamp"):
                return None
            res = res[0]
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
            tz = (res.get("meta") or {}).get("exchangeTimezoneName") or "Asia/Kolkata"
            idx = (pd.to_datetime(res["timestamp"], unit="s", utc=True)
                   .tz_convert(tz).normalize())
            df = pd.DataFrame({"Open": q["open"], "High": q["high"],
                               "Low": q["low"], "Close": q["close"],
                               "Volume": q["volume"]}, index=idx, dtype=float)
            if adj:
                f = pd.Series(adj, index=idx, dtype=float) / df["Close"]
                for c in ("Open", "High", "Low", "Close"):
                    df[c] = df[c] * f
            df = df[~df.index.duplicated(keep="last")]
            return df.dropna(subset=["Open", "High", "Low", "Close"])
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return None


def validate_ticker(symbol):
    """Return (ok, message). Used by the UI before adding a ticker."""
    try:
        df = yf.Ticker(symbol).history(period="5d")
        if df.empty:
            df = yahoo_chart(symbol, "5d")
        if df is None or df.empty:
            return False, f"No data found for '{symbol}'. Check the suffix (.BO / .NS)."
        last = df["Close"].iloc[-1]
        return True, f"OK — last close {last:,.2f}"
    except Exception as e:
        try:
            df = yahoo_chart(symbol, "5d")
            if df is not None and not df.empty:
                return True, f"OK — last close {df['Close'].iloc[-1]:,.2f}"
        except Exception:
            pass
        return False, str(e)



def resolve_and_validate(symbol):
    """Return (ok, resolved_symbol, message).
    If no suffix given, tries .NS then .BO automatically."""
    candidates = [symbol] if "." in symbol else [f"{symbol}.NS", f"{symbol}.BO"]
    last_msg = ""
    for cand in candidates:
        ok, msg = validate_ticker(cand)
        if ok:
            return True, cand, msg
        last_msg = msg
    # Yahoo has nothing — accept the ticker anyway if Angel One's scrip
    # master knows it and SmartAPI credentials are present (history will
    # then come from SmartAPI in download_ticker).
    if smartapi_source.configured():
        for cand in candidates:
            if smartapi_source.has_symbol(cand):
                return True, cand, ("Not on Yahoo — will use Angel One "
                                    "SmartAPI for this stock's data.")
    tried = " / ".join(candidates)
    return False, symbol, f"No data found (tried {tried}). {last_msg}"

def _save_with_source(df, symbol, asset_type, source, progress):
    """Persist a history, keeping the symbol's series single-source.
    Yahoo rows are split-adjusted, SmartAPI rows are raw exchange prices;
    if the vendor changes, the old rows are wiped first so the two
    conventions never mix (mixing creates fake cliffs at splits)."""
    prev = db.symbol_source(symbol)
    if prev and prev != source:
        db.purge_prices(symbol)
        progress(f"[SRC] {symbol}: {prev} -> {source}, old rows purged")
    return db.save_prices(df, symbol, asset_type, source=source)


def download_ticker(symbol, asset_type, progress=print, retries=2):
    """Download full history: Yahoo's chart API first (one request, the
    same adjusted prices yfinance returns), then yfinance with retries (it
    throttles bursts), then Angel One SmartAPI as fallback when Yahoo has
    nothing or suspiciously little for this listing."""
    last_err = None
    yahoo_df = None
    try:
        yahoo_df = yahoo_chart(symbol, config.HISTORY_PERIOD)
        if yahoo_df is not None and yahoo_df.empty:
            yahoo_df = None
        if yahoo_df is None:
            retries = 0          # Yahoo answered: it has nothing for this
    except Exception as e:
        last_err = e

    # Chart API failed or came back short: yfinance, with retries.
    for attempt in range(1 + retries):
        if yahoo_df is not None and len(yahoo_df) >= MIN_GOOD_ROWS:
            break
        try:
            if attempt:
                time.sleep(2 * attempt)
                progress(f"[RETRY {attempt}] {symbol}")
            df = yf.Ticker(symbol).history(
                period=config.HISTORY_PERIOD, auto_adjust=True
            )
            if df.empty:
                last_err = "empty response"
                continue
            if yahoo_df is None or len(df) > len(yahoo_df):
                yahoo_df = df
            break
        except Exception as e:
            last_err = e

    if yahoo_df is not None and len(yahoo_df) >= MIN_GOOD_ROWS:
        n = _save_with_source(yahoo_df, symbol, asset_type, "yahoo", progress)
        progress(f"[OK] {symbol}: {n} rows")
        return n

    # Yahoo failed or came back shallow — try SmartAPI if configured.
    if smartapi_source.configured():
        try:
            years = int(config.HISTORY_PERIOD.rstrip("y")) \
                if config.HISTORY_PERIOD.endswith("y") else 10
            sdf = smartapi_source.fetch_history(symbol, years=years,
                                                progress=progress)
        except Exception as e:
            progress(f"[WARN] SmartAPI fallback {symbol}: {e}")
            sdf = None
        # keep whichever source produced more history
        if sdf is not None and (yahoo_df is None or len(sdf) > len(yahoo_df)):
            n = _save_with_source(sdf, symbol, asset_type, "smartapi",
                                  progress)
            progress(f"[OK] {symbol}: {n} rows (SmartAPI)")
            return n

    if yahoo_df is not None:
        n = _save_with_source(yahoo_df, symbol, asset_type, "yahoo", progress)
        progress(f"[OK] {symbol}: {n} rows (shallow — Yahoo only)")
        return n
    progress(f"[ERROR] {symbol}: {last_err}")
    return 0


def download_mf(scheme_code, label, progress=print):
    try:
        resp = requests.get(f"{MFAPI_BASE}/{scheme_code}", timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        official = payload.get("meta", {}).get("scheme_name", "UNKNOWN")
        data = payload.get("data", [])
        if not data:
            progress(f"[WARN] scheme {scheme_code}: no NAV data")
            return 0
        rows = []
        for item in data:
            d, m, y = item["date"].split("-")
            rows.append((f"{y}-{m}-{d}", float(item["nav"])))
        db.save_navs(scheme_code, rows)
        db.update_mf_label(scheme_code, official)
        progress(f"[OK] MF {scheme_code}: {len(rows)} NAVs — {official}")
        return len(rows)
    except Exception as e:
        progress(f"[ERROR] MF {scheme_code}: {e}")
        return 0


def search_schemes(query):
    """Return [(scheme_code, scheme_name), ...] from mfapi search."""
    resp = requests.get(f"{MFAPI_BASE}/search", params={"q": query}, timeout=30)
    resp.raise_for_status()
    return [(r["schemeCode"], r["schemeName"]) for r in resp.json()]



# Keys pulled from yfinance .info — Yahoo's coverage for .BO/.NS varies,
# so every value is optional and the UI shows "—" when missing.
FUNDAMENTAL_KEYS = {
    "sector": "Sector",
    "industry": "Industry",
    "marketCap": "Market cap",
    "trailingPE": "P/E (TTM)",
    "priceToBook": "P/B",
    "trailingEps": "EPS (TTM)",
    "returnOnEquity": "ROE",
    "profitMargins": "Net margin",
    "debtToEquity": "Debt/Equity",
    "dividendYield": "Dividend yield",
    "fiftyTwoWeekHigh": "52w high",
    "fiftyTwoWeekLow": "52w low",
    "bookValue": "Book value",
    "beta": "Beta",
}


def fetch_fundamentals(symbol, progress=print):
    """Store a snapshot of key fundamentals from Yahoo. Best-effort."""
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        data = {k: info.get(k) for k in FUNDAMENTAL_KEYS if info.get(k) is not None}
        # next earnings date, for the "results this week" home card
        try:
            cal = t.calendar
            dates = (cal or {}).get("Earnings Date") \
                if isinstance(cal, dict) else None
            if dates:
                data["nextEarnings"] = str(dates[0])
        except Exception:
            pass
        if data:
            db.save_fundamentals(symbol, data)
            progress(f"[OK] fundamentals for {symbol}: {len(data)} fields")
        else:
            progress(f"[WARN] no fundamentals returned for {symbol}")
        return data
    except Exception as e:
        progress(f"[WARN] fundamentals {symbol}: {e}")
        return {}


def download_one(symbol=None, asset_type=None, scheme_code=None, label="",
                 progress=print):
    """Download everything for a single newly-added item (history +
    fundamentals for tickers, NAVs for MFs). Used for instant-add in the UI."""
    if asset_type == "mf":
        return download_mf(scheme_code, label, progress)
    n = download_ticker(symbol, asset_type, progress)
    if n and asset_type == "stock":
        fetch_fundamentals(symbol, progress)
    return n


def refresh_all_fundamentals(progress=print, sleep=0.4):
    """Refresh fundamentals for every stock in the watchlist."""
    for (_id, asset_type, symbol, _sc, _label, _a) in db.get_watchlist("stock"):
        fetch_fundamentals(symbol, progress)
        time.sleep(sleep)
    progress("Fundamentals refresh done.")


def run_all(progress=print, sleep=0.5):
    db.init_db()
    items = db.get_watchlist()
    for (_id, asset_type, symbol, scheme_code, label, _added) in items:
        if asset_type in ("stock", "etf"):
            download_ticker(symbol, asset_type, progress)
            if asset_type == "stock":
                fetch_fundamentals(symbol, progress)
        elif asset_type == "mf":
            download_mf(scheme_code, label, progress)
        time.sleep(sleep)
    progress("Done.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--search", help="search mutual fund scheme codes by name")
    args = p.parse_args()
    if args.search:
        for code, name in search_schemes(args.search)[:25]:
            print(f"  {code:>8}  {name}")
        sys.exit(0)
    run_all()
