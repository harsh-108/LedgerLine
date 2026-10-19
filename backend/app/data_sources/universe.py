"""
Screener universes beyond the watchlist.

The screener normally runs over your ~63 tracked stocks; a query like
"gold stocks in an uptrend" honestly returns nothing if you track no
gold stocks. This module lets the screener run over NSE index
constituent lists instead:

    watchlist  — your tracked stocks (default, always ready)
    nifty50    — NIFTY 50
    nifty100   — NIFTY 100
    nifty500   — NIFTY 500

Constituent lists come from NSE's public index CSVs and are cached in
universe_cache.json for 30 days (so one download per month, and the
feature works offline afterwards).

Preparing a universe = downloading history + fundamentals for whichever
constituents aren't in the DB yet, via the existing downloader (Yahoo
first, SmartAPI fallback). This is deliberately explicit and
user-triggered: NIFTY 500 means several hundred downloads (~15–30 min
first time) and that cost should be chosen, not sprung. Universe stocks
are stored in the same prices/fundamentals tables but are NOT added to
the watchlist — no tape, signals, or journal noise from stocks you
merely screened.
"""

import json
import os
import time

import requests

from app.core import database as db
from app.data_sources import downloader

CACHE_FILE = str(__import__("app.core.paths", fromlist=["paths"]).DATA_DIR / "universe_cache.json")
CACHE_DAYS = 30

# NSE publishes these; both hosts have served them over time.
_CSV = {
    "nifty50": "ind_nifty50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty500": "ind_nifty500list.csv",
}
_HOSTS = [
    "https://nsearchives.nseindia.com/content/indices/",
    "https://archives.nseindia.com/content/indices/",
]
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/csv,*/*"}

NAMES = ["watchlist"] + list(_CSV)


def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _listed(syms):
    """Drop NSE's placeholder rows. During a demerger or similar corporate
    action NSE puts a temporary 'DUMMY...' symbol (e.g. DUMMYHEG) in the
    index file; it has no prices or fundamentals anywhere, so it only ever
    showed up as a download error."""
    return [s for s in syms if not s.upper().startswith("DUMMY")]


def constituents(name):
    """Symbols ('RELIANCE.NS', ...) for an index universe.
    Cached ~30 days. Raises RuntimeError with a clear message if the
    list can't be fetched and isn't cached."""
    if name == "watchlist":
        return [w[2] for w in db.get_watchlist("stock") if w[2]]
    if name not in _CSV:
        raise RuntimeError(f"Unknown universe '{name}'.")
    cache = _load_cache()
    ent = cache.get(name)
    if ent and time.time() - ent["ts"] < CACHE_DAYS * 86400:
        return _listed(ent["symbols"])
    last_err = None
    for host in _HOSTS:
        try:
            r = requests.get(host + _CSV[name], headers=_HEADERS, timeout=20)
            r.raise_for_status()
            lines = r.text.strip().splitlines()
            header = [h.strip().lower() for h in lines[0].split(",")]
            si = header.index("symbol")
            syms = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) > si and parts[si].strip():
                    syms.append(parts[si].strip().upper() + ".NS")
            syms = _listed(syms)
            if len(syms) >= 10:
                cache[name] = {"ts": time.time(), "symbols": syms}
                _save_cache(cache)
                return syms
            last_err = f"unexpected CSV shape ({len(syms)} symbols)"
        except Exception as e:
            last_err = e
    if ent:   # stale cache beats no data
        return _listed(ent["symbols"])
    raise RuntimeError(
        f"Could not fetch the {name.upper()} constituent list from NSE "
        f"({last_err}). Check your connection and try again.")


def status(name):
    """How ready a universe is: total constituents, how many have price
    history, how many have fundamentals."""
    syms = constituents(name)
    counts = db.price_counts()
    funds = db.all_fundamentals()
    with_prices = sum(1 for s in syms if counts.get(s, 0) >= 60)
    with_funds = sum(1 for s in syms if s in funds)
    return {"name": name, "total": len(syms),
            "with_prices": with_prices, "with_fundamentals": with_funds,
            "missing": len(syms) - with_prices}


def prepare(name, progress=lambda m: None, sleep=0.6):
    """Download history + fundamentals for constituents that lack them.
    Idempotent — re-running only fills gaps. Polite sleeps because this
    can be hundreds of Yahoo/SmartAPI calls."""
    syms = constituents(name)
    counts = db.price_counts()
    funds = db.all_fundamentals()
    todo = [s for s in syms if counts.get(s, 0) < 60 or s not in funds]
    progress(f"{name}: {len(syms)} constituents, "
             f"{len(todo)} need data")
    done = 0
    for s in todo:
        if counts.get(s, 0) < 60:
            downloader.download_ticker(s, "stock", progress=progress)
        if s not in funds:
            downloader.fetch_fundamentals(s, progress=progress)
        done += 1
        if done % 10 == 0:
            progress(f"…{done}/{len(todo)} done")
        time.sleep(sleep)
    progress(f"{name} ready.")
    return status(name)


def symbols_for_query(name):
    """The symbol set a screener query runs over. Index universes also
    include your watchlist stocks, so tracked names never vanish from
    results when you widen the lens."""
    syms = constituents(name)
    if name != "watchlist":
        wl = [w[2] for w in db.get_watchlist("stock") if w[2]]
        syms = list(dict.fromkeys(syms + wl))
    return syms
