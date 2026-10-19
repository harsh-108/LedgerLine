"""
Mutual funds — the Funds page's backend.

Data: NAVs from mfapi.in (free, official AMFI data, no key) already flow
into the `nav` table via downloader.download_mf on every refresh. This
module adds:

  * search / add by scheme code (so funds can be added from the UI, not
    only from config.py)
  * an overview row per fund: latest NAV, point returns, CAGR, drawdown,
    ROLLING 1Y / 3Y returns (median / worst / best / % positive) — the
    honest way to judge a fund, since a single 1Y number depends on
    which day you looked
  * lump-sum holdings in units (per user, like stock holdings), valued
    at the latest NAV. SIPs stay in sip.py.
"""

import datetime as _dt

import numpy as np
import pandas as pd

from app.core import database as db
from app.core import memo
from app.analysis import charts as ch

BENCHMARK = "NIFTYBEES.NS"


# ----------------------------------------------------------------- schema
def ensure_tables():
    with db.get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS mf_holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_code INTEGER NOT NULL,
            units       REAL NOT NULL,
            buy_nav     REAL NOT NULL,
            buy_date    TEXT,
            username    TEXT,
            added_at    TEXT DEFAULT (datetime('now','localtime'))
        )""")


# ------------------------------------------------------------- analytics
def _point_returns(nav):
    out = {}
    for label, days in [("1m", 21), ("3m", 63), ("6m", 126),
                        ("1y", 252), ("3y", 756), ("5y", 1260)]:
        if len(nav) > days:
            out[label] = round(
                float(nav.iloc[-1] / nav.iloc[-days - 1] - 1) * 100, 2)
    return out


def _rolling(nav, years):
    """Distribution of every `years`-long holding period in the history.
    Uses calendar offsets on the date index, so gaps/holidays don't skew."""
    if (nav.index[-1] - nav.index[0]).days < 365 * years + 30:
        return None
    start = nav.index + pd.DateOffset(years=years)
    end_vals = nav.reindex(start, method="ffill")
    mask = start <= nav.index[-1]
    if mask.sum() < 20:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (end_vals.values[mask] / nav.values[mask]) ** (1 / years) - 1
    r = pd.Series(r * 100)
    r = r[np.isfinite(r)]          # a zero NAV upstream would give inf
    if r.empty:
        return None
    return {"median": round(float(r.median()), 2),
            "worst": round(float(r.min()), 2),
            "best": round(float(r.max()), 2),
            "positive_pct": round(float((r > 0).mean() * 100), 1),
            "windows": int(len(r))}


def _cagr(nav):
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    if years < 1:
        return None
    return round(float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1)
                 * 100, 2)


def _benchmark_returns():
    rows = db.load_closes(BENCHMARK)
    if len(rows) < 30:
        return {}
    s = pd.Series([r[1] for r in rows],
                  index=pd.to_datetime([r[0] for r in rows])).sort_index()
    return _point_returns(s)


@memo.memoize("fund_stats")
def fund_stats(scheme_code):
    nav = ch.load_mf_series(scheme_code)
    if nav is None or len(nav) < 5:
        return None
    dd = float((nav / nav.cummax() - 1).min() * 100)
    return {
        "latest_nav": round(float(nav.iloc[-1]), 4),
        "nav_date": nav.index[-1].date().isoformat(),
        "prev_nav": round(float(nav.iloc[-2]), 4) if len(nav) > 1 else None,
        "day_pct": round(float(nav.iloc[-1] / nav.iloc[-2] - 1) * 100, 2)
        if len(nav) > 1 else None,
        "returns": _point_returns(nav),
        "cagr": _cagr(nav),
        "max_drawdown": round(dd, 2),
        "since": nav.index[0].date().isoformat(),
        "n_navs": int(len(nav)),
        "rolling": {"1y": _rolling(nav, 1), "3y": _rolling(nav, 3)},
        "spark": [round(float(v), 2) for v in nav.tail(90).values],
    }


# --------------------------------------------------------------- holdings
@db._changes_data
def add_holding(scheme_code, units, buy_nav, buy_date=None, username=None):
    ensure_tables()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO mf_holdings (scheme_code, units, buy_nav, buy_date,"
            " username) VALUES (?,?,?,?,?)",
            (int(scheme_code), float(units), float(buy_nav), buy_date,
             username))


@db._changes_data
def remove_holding(hid, username=None):
    ensure_tables()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM mf_holdings WHERE id=? AND "
                     "(username=? OR username IS NULL)", (hid, username))


def get_holdings(username=None):
    ensure_tables()
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT id, scheme_code, units, buy_nav, buy_date FROM "
            "mf_holdings WHERE username=? OR username IS NULL "
            "ORDER BY buy_date, id", (username,)).fetchall()


# --------------------------------------------------------------- overview
@memo.memoize("fund_overview", per_user=True)
def overview(username=None):
    """One row per fund on the watchlist + totals for the Funds page."""
    from app.portfolio import sip as sip_mod
    bm = _benchmark_returns()
    holdings = {}
    for (hid, code, units, bnav, bdate) in get_holdings(username):
        holdings.setdefault(code, []).append(
            {"id": hid, "units": units, "buy_nav": bnav, "buy_date": bdate})
    sips = {}
    for (sid, code, amount, day, start, _label) in db.get_sips():
        try:
            ev = sip_mod.evaluate(code, amount, day, start)
        except Exception:
            ev = None
        sips.setdefault(code, []).append(
            {"id": sid, "amount": amount, "day": day, "start": start,
             "eval": ev})

    funds, tot_inv, tot_val = [], 0.0, 0.0
    for (iid, atype, _sym, code, label, added) in db.get_watchlist("mf"):
        try:
            code = int(code)
        except (TypeError, ValueError):
            continue                       # malformed row — skip, don't 500
        try:
            st = fund_stats(code)
            err = None
        except Exception as e:             # one bad NAV series != dead page
            st, err = None, f"{e.__class__.__name__}: {e}"
        row = {"id": iid, "scheme_code": code,
               "label": label or f"MF {code}", "added_at": added,
               "stats": st, "error": err, "holdings": holdings.get(code, []),
               "sips": sips.get(code, [])}
        if st and row["holdings"]:
            units = sum(h["units"] for h in row["holdings"])
            invested = sum(h["units"] * h["buy_nav"] for h in row["holdings"])
            value = units * st["latest_nav"]
            row["position"] = {
                "units": round(units, 3), "invested": round(invested, 2),
                "value": round(value, 2), "pnl": round(value - invested, 2),
                "pnl_pct": round((value / invested - 1) * 100, 2)
                if invested else None,
                "avg_nav": round(invested / units, 4) if units else None}
            tot_inv += invested
            tot_val += value
        if st and bm.get("1y") is not None and "1y" in st["returns"]:
            row["vs_index_1y"] = round(st["returns"]["1y"] - bm["1y"], 2)
        funds.append(row)

    sip_inv = sum((s["eval"] or {}).get("invested", 0) or 0
                  for lst in sips.values() for s in lst)
    sip_val = sum((s["eval"] or {}).get("current_value", 0) or 0
                  for lst in sips.values() for s in lst)
    return _clean({
        "funds": funds,
        "benchmark": {"symbol": BENCHMARK, "returns": bm},
        "totals": {
            "funds": len(funds),
            "lumpsum_invested": round(tot_inv, 2),
            "lumpsum_value": round(tot_val, 2),
            "sip_invested": round(sip_inv, 2),
            "sip_value": round(sip_val, 2),
            "invested": round(tot_inv + sip_inv, 2),
            "value": round(tot_val + sip_val, 2),
            "pnl": round(tot_val + sip_val - tot_inv - sip_inv, 2),
        },
    })


def _clean(obj):
    """Starlette's JSON encoder rejects NaN/inf (-> HTTP 500). Replace
    them with null anywhere in the payload."""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


# ------------------------------------------------------------ search/add
def search(query):
    from app.data_sources import downloader
    q = (query or "").strip()
    if len(q) < 3:
        return []
    try:
        hits = downloader.search_schemes(q)
    except Exception as e:
        raise RuntimeError(f"mfapi.in search failed: {e}")
    return [{"scheme_code": int(c), "name": n} for c, n in hits[:25]]


def add(scheme_code, label=None):
    """Add to the watchlist and pull the full NAV history right away.
    Returns (rows_downloaded, official_name)."""
    from app.data_sources import downloader
    code = int(scheme_code)
    db.add_mf(code, label or "VERIFY-ME fund")
    n = downloader.download_mf(code, label or "", progress=lambda m: None)
    with db.get_conn() as conn:
        row = conn.execute("SELECT label FROM watchlist WHERE asset_type="
                           "'mf' AND scheme_code=?", (code,)).fetchone()
    name = row[0] if row else label
    if n == 0:
        # keep the row (user may be offline) but say so
        return 0, name
    return n, name
