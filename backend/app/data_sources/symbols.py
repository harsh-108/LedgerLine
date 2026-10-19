"""
Company name -> ticker resolver, shared by the /api/symbol-search route
and the analyst's find_symbol tool.

Why: the analyst used to be told to "resolve a bare name to the obvious
symbol", i.e. guess from memory. Small models guess wrong (LIC -> LICHFD,
which doesn't exist) and then rationalise the empty result. Tickers must
come from a lookup, never from the model.

Primary: Yahoo's public search API filtered to NSE/BSE listings.
Fallback/merge: Angel One's public scrip master (no login needed), which
catches new listings and fund-house ETFs Yahoo search misses.
"""

import threading
import time

import requests

from app.data_sources import smartapi_source

_cache = {}                 # (q, limit) -> (at, result); typing repeats itself
_CACHE_TTL = 600
_local_names = {"at": 0.0, "rows": []}
_local_lock = threading.Lock()


def _stored_symbols():
    """[(symbol, name)] for every symbol with stored prices, names from
    fundamentals where known. Refreshed every 5 minutes."""
    with _local_lock:
        if time.time() - _local_names["at"] < 300:
            return _local_names["rows"]
    import json as _json
    from app.core import database as db
    with db.get_conn() as conn:
        names = {}
        for sym, data in conn.execute("SELECT symbol, data FROM fundamentals"):
            try:
                d = _json.loads(data) or {}
                names[sym] = d.get("shortName") or d.get("longName") or ""
            except Exception:
                pass
        syms = [r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM watchlist WHERE symbol IS NOT NULL")]
        syms += list(names)
    rows = sorted({(s, names.get(s, "")) for s in syms
                   if s.endswith((".NS", ".BO"))})
    with _local_lock:
        _local_names.update(at=time.time(), rows=rows)
    return rows


def _local_matches(q, limit):
    """Stocks this server already knows, matched by ticker or name. Instant,
    and works when Yahoo is rate-limiting the server."""
    ql = q.lower()
    hits = []
    for sym, name in _stored_symbols():
        base = sym.split(".")[0].lower()
        if base.startswith(ql):
            rank = 0
        elif ql in base or ql in name.lower():
            rank = 1
        else:
            continue
        hits.append((rank, sym.endswith(".BO"), sym, name))
    hits.sort()
    return [{"symbol": sym, "name": name or sym.split(".")[0],
             "exch": "BSE" if sym.endswith(".BO") else "NSE", "type": "stock"}
            for _r, _bo, sym, name in hits[:limit]]


def search(q, limit=10):
    """Return {"items": [{symbol, name, exch, type}, ...], "error": str|None}."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"items": [], "error": None}
    key = (q.lower(), limit)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    res = _search(q, limit)
    if res["items"]:
        _cache[key] = (time.time(), res)
        if len(_cache) > 500:
            _cache.clear()
    return res


def _search(q, limit):
    items, seen, errors = [], set(), []
    try:
        for it in _local_matches(q, 4):
            seen.add(it["symbol"])
            items.append(it)
    except Exception as e:
        errors.append(f"local:{e.__class__.__name__}")
    r = {}
    for host in ("query1", "query2"):
        try:
            resp = requests.get(
                f"https://{host}.finance.yahoo.com/v1/finance/search",
                params={"q": q, "quotesCount": 12, "newsCount": 0},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=4,
            )
            if getattr(resp, "status_code", 200) == 429:
                errors.append("yahoo:rate-limited")
                r = {}
                continue
            r = resp.json()
            if r.get("quotes"):
                break
        except Exception as e:
            errors.append(f"yahoo:{e.__class__.__name__}")
            r = {}
    try:
        for it in r.get("quotes", []):
            sym = it.get("symbol", "")
            if not (sym.endswith(".NS") or sym.endswith(".BO")):
                continue
            if sym in seen:
                continue
            seen.add(sym)
            items.append({
                "symbol": sym,
                "name": it.get("shortname") or it.get("longname") or "",
                "exch": "NSE" if sym.endswith(".NS") else "BSE",
                "type": "etf" if it.get("quoteType") == "ETF" else "stock",
            })
    except Exception as e:
        errors.append(f"parse:{e.__class__.__name__}")
    try:
        for m in smartapi_source.search_names(q, limit=10):
            if m["symbol"] in seen:
                continue
            seen.add(m["symbol"])
            name_u = m["name"].upper()
            items.append({"symbol": m["symbol"], "name": m["name"],
                          "exch": m["exch"],
                          "type": "etf" if ("ETF" in name_u
                                           or "BEES" in name_u)
                          else "stock"})
    except Exception as e:
        errors.append(f"scrips:{e}")
    return {"items": items[:limit],
            "error": "; ".join(str(x) for x in errors)
            if (errors and not items) else None}
