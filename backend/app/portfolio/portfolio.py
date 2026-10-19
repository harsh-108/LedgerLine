"""
Portfolio: holdings valuation, allocation, correlation, position sizing.
"""

import numpy as np
import pandas as pd

from app.core import database as db
from app.core import memo


def valuation(username=None):
    """DataFrame of holdings with live P&L, plus totals dict.
    username scopes the portfolio to one account (None = all rows,
    kept for the legacy Streamlit app and CLI digest)."""
    rows = db.get_holdings(username)
    if not rows:
        return pd.DataFrame(), {}
    move_map = {m[0]: m[3] for m in db.latest_moves()}
    out = []
    for hid, symbol, qty, buy_price, buy_date, thesis in rows:
        last = db.last_close(symbol)
        invested = qty * buy_price
        current = qty * last if last else None
        out.append({
            "id": hid, "Symbol": symbol, "Qty": qty,
            "Buy price": buy_price, "Buy date": buy_date or "—",
            "thesis": thesis,
            "Last": last, "Invested": round(invested, 2),
            "Current": round(current, 2) if current else None,
            "P&L": round(current - invested, 2) if current else None,
            "P&L %": round((current / invested - 1) * 100, 2) if current else None,
            "Day %": round(move_map.get(symbol), 2)
                     if symbol in move_map else None,
        })
    df = pd.DataFrame(out)
    priced = df.dropna(subset=["Current"])
    # today's rupee move: qty * (last - prev close) per priced holding
    day_pnl = 0.0
    for _, r in priced.iterrows():
        pair = db.last_two_closes(r["Symbol"])
        if len(pair) == 2 and pair[0] and pair[1]:
            day_pnl += r["Qty"] * (pair[0] - pair[1])
    totals = {
        "invested": float(df["Invested"].sum()),
        "current": float(priced["Current"].sum()),
        "pnl": float(priced["P&L"].sum()),
        "day_pnl": round(day_pnl, 2),
        "unpriced": int(df["Current"].isna().sum()),
    }
    totals["day_pct"] = (
        round(day_pnl / (totals["current"] - day_pnl) * 100, 2)
        if totals["current"] and totals["current"] != day_pnl else 0.0
    )
    # dividends: cash received is part of the true return, but invisible
    # to price-only P&L. Entered manually (Dividends card in the UI).
    div = db.dividend_total(username)
    totals["dividends"] = round(div, 2)
    totals["pnl_incl_div"] = round(totals["pnl"] + div, 2)
    totals["pnl_incl_div_pct"] = (
        round(totals["pnl_incl_div"] / totals["invested"] * 100, 2)
        if totals["invested"] else 0.0
    )
    totals["pnl_pct"] = (
        (totals["current"] / priced["Invested"].sum() - 1) * 100
        if len(priced) else 0.0
    )
    return df, totals


@memo.memoize("correlation")
def correlation_matrix(symbols, days=252):
    """Daily-return correlation across symbols with enough shared history."""
    series = {}
    for s in symbols:
        closes = db.load_closes(s)
        if len(closes) >= 60:
            ser = pd.Series([c[1] for c in closes],
                            index=pd.to_datetime([c[0] for c in closes]))
            series[s] = ser.tail(days).pct_change()
    if len(series) < 2:
        return None
    rets = pd.DataFrame(series).dropna(how="all")
    return rets.corr().round(2)


def aggregated(val):
    """Collapse the per-lot valuation into ONE row per symbol — what you
    actually own. Weighted average cost, earliest buy date, lot count,
    and the lot ids (the dialog manages individual lots)."""
    if val.empty:
        return val
    rows = []
    for sym, g in val.groupby("Symbol", sort=False):
        qty = g["Qty"].sum()
        invested = g["Invested"].sum()
        cur = g["Current"].sum(min_count=1)
        dates = [d for d in g["Buy date"] if d and d != "—"]
        rows.append({
            "Symbol": sym, "Qty": qty,
            "thesis": " | ".join(x for x in g.get("thesis", [])
                                 if isinstance(x, str) and x) or None,
            "Avg cost": round(invested / qty, 2) if qty else None,
            "Since": min(dates) if dates else "—",
            "Lots": int(len(g)),
            "Last": g["Last"].iloc[-1],
            "Invested": round(invested, 2),
            "Current": round(cur, 2) if pd.notna(cur) else None,
            "P&L": round(cur - invested, 2) if pd.notna(cur) else None,
            "P&L %": round((cur / invested - 1) * 100, 2)
            if pd.notna(cur) and invested else None,
            "Day %": g["Day %"].iloc[-1],
            "ids": g["id"].tolist(),
        })
    return pd.DataFrame(rows)


BENCHMARK = "NIFTYBEES.NS"   # "what the index gave for free" comparison


@memo.memoize("value_history", per_user=True)
def value_history(days=730, username=None):
    """Portfolio value over time vs money invested, plus a benchmark:
    the same cash flows put into BENCHMARK (NIFTYBEES) on the same dates.

    For each holding, its qty*close contributes from its buy date onward
    (holdings without a buy date are assumed held for the whole window).
    Invested is a step line that jumps by qty*buy_price on each buy date.
    The benchmark buys amount/price units of the index ETF at each buy
    date's close and holds — an honest answer to "was picking these
    stocks worth it vs just buying the market?"
    Returns DataFrame indexed by date with 'value', 'invested', and
    (when benchmark data exists) 'benchmark', or None.
    """
    rows = db.get_holdings(username)
    if not rows:
        return None
    frames = {}
    for hid, symbol, qty, buy_price, buy_date, thesis in rows:
        closes = db.load_closes(symbol)
        if len(closes) < 2:
            continue
        s = pd.Series([c[1] for c in closes],
                      index=pd.to_datetime([c[0] for c in closes]))
        s = s.tail(days) * qty
        if buy_date:
            s = s[s.index >= pd.Timestamp(buy_date)]
        if len(s):
            frames[hid] = s
    if not frames:
        return None
    value = pd.DataFrame(frames)
    # forward-fill so a holding's value persists across other stocks'
    # trading days, but never before its own first (buy) date
    value = value.ffill()
    out = pd.DataFrame({"value": value.sum(axis=1, min_count=1)}).dropna()

    invested = pd.Series(0.0, index=out.index)
    window_start = out.index[0]
    for hid, symbol, qty, buy_price, buy_date, thesis in rows:
        amt = qty * buy_price
        start = pd.Timestamp(buy_date) if buy_date else window_start
        invested[invested.index >= start] += amt
    out["invested"] = invested

    # benchmark: same rupees, same dates, into the index ETF instead
    bcloses = db.load_closes(BENCHMARK)
    if len(bcloses) > 2:
        b = pd.Series([c[1] for c in bcloses],
                      index=pd.to_datetime([c[0] for c in bcloses]))
        b = b.reindex(out.index, method="ffill")
        units = pd.Series(0.0, index=out.index)
        ok = True
        for hid, symbol, qty, buy_price, buy_date, thesis in rows:
            amt = qty * buy_price
            start = pd.Timestamp(buy_date) if buy_date else window_start
            # price on the first trading day at/after the buy date
            after = b[b.index >= start]
            if after.empty or pd.isna(after.iloc[0]) or not after.iloc[0]:
                ok = False
                break
            units[units.index >= after.index[0]] += amt / after.iloc[0]
        if ok:
            out["benchmark"] = (units * b).round(2)
    return out


def sector_allocation(username=None):
    """Current value grouped by sector (from stored fundamentals).
    Returns [(sector, value), ...] sorted desc; unknown -> 'Other'."""
    rows = db.get_holdings(username)
    if not rows:
        return []
    funds = db.all_fundamentals()
    buckets = {}
    for _hid, symbol, qty, _bp, _bd, _th in rows:
        last = db.last_close(symbol)
        if not last:
            continue
        sector = (funds.get(symbol, {}) or {}).get("sector") or "Other"
        buckets[sector] = buckets.get(sector, 0.0) + qty * last
    return sorted(buckets.items(), key=lambda kv: -kv[1])


def position_size(capital, risk_pct, entry, stop):
    """Risk-based sizing: shares such that hitting the stop loses only
    risk_pct of capital. Returns dict or None on bad inputs."""
    if (capital <= 0 or entry <= 0 or stop <= 0 or stop >= entry
            or not 0 < risk_pct <= 100):
        return None
    risk_amount = capital * risk_pct / 100
    per_share_risk = entry - stop
    shares = int(risk_amount / per_share_risk)
    if shares == 0:
        return {"shares": 0, "note": "Stop too wide for this capital/risk."}
    # a very tight stop can ask for more shares than the capital buys
    affordable = int(capital // entry)
    out = {}
    if shares > affordable:
        shares = affordable
        out["note"] = ("Capped at what the capital can buy — the stop is "
                       "tight enough that the risk budget isn't the limit.")
    out.update({
        "shares": shares,
        "outlay": round(shares * entry, 2),
        "outlay_pct": round(shares * entry / capital * 100, 1),
        "risk_amount": round(shares * per_share_risk, 2),
        "stop_pct": round((stop / entry - 1) * 100, 1),
    })
    return out


def is_long_term(buy_date, sell_date):
    """Listed equity is long-term when held MORE than 12 months. That is
    calendar months, not 365 days: across a 29 Feb the anniversary is 366
    days away, and selling on the anniversary is still short-term."""
    try:
        anniversary = buy_date.replace(year=buy_date.year + 1)
    except ValueError:                       # bought on 29 Feb
        anniversary = buy_date.replace(year=buy_date.year + 1, day=28)
    return sell_date > anniversary


def _iso(s):
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def realized_summary(username=None):
    """Realized gains from recorded sells: overall, per Indian financial
    year (Apr-Mar), split short/long term by the 12-month rule."""
    rows = db.get_sells(username)
    if not rows:
        return None
    out_rows, fy = [], {}
    total = st = lt = 0.0
    for (sid, sym, qty, bp, bd, sp, sd) in rows:
        pnl = qty * (sp - bp)
        d, bought = _iso(sd), _iso(bd)
        if d is None:
            continue                 # unparseable sell date: can't place it
        days = (d - bought).days if bought else None
        long_term = bool(bought and is_long_term(bought, d))
        fy_key = f"FY{d.year % 100 + (1 if d.month >= 4 else 0):02d}"
        b = fy.setdefault(fy_key, {"total": 0.0, "st": 0.0, "lt": 0.0})
        b["total"] += pnl
        b["lt" if long_term else "st"] += pnl
        total += pnl
        lt += pnl if long_term else 0
        st += 0 if long_term else pnl
        out_rows.append({"id": sid, "symbol": sym.split(".")[0], "qty": qty,
                         "buy_price": bp, "sell_price": sp,
                         "sell_date": sd, "pnl": round(pnl, 2),
                         "term": "LT" if long_term else
                         ("ST" if days is not None else "?")})
    return {"rows": out_rows[:20],
            "total": round(total, 2), "short_term": round(st, 2),
            "long_term": round(lt, 2),
            "fy": [{"fy": k, **{x: round(v, 2) for x, v in b.items()}}
                   for k, b in sorted(fy.items(), reverse=True)]}


# --------------------------------------------------------- price repair
STALE_DAYS = 4          # covers a weekend plus one holiday


_missing_seen = {}      # symbol -> when Yahoo last had nothing for it
_MISSING_TTL = 3600     # don't re-ask about a dead ticker on every run


def _needs_prices(symbol):
    """No rows, or the newest row is older than STALE_DAYS. A short
    history alone is fine: a recent listing (NSE.BO) simply has few days."""
    import datetime as _dt
    last = db.last_stored_date(symbol)
    return not last or (_dt.date.today()
                        - _dt.date.fromisoformat(last)).days > STALE_DAYS


def _fetch(symbol, progress):
    """download_ticker, skipped for a symbol Yahoo recently had nothing for."""
    import time as _t
    from app.data_sources import downloader
    if _t.time() - _missing_seen.get(symbol, 0) < _MISSING_TTL:
        return
    try:
        downloader.download_ticker(symbol, "stock", progress)
    except Exception as e:
        progress(f"[repair] {symbol}: {e}")
    if not db.stored_rows(symbol):
        _missing_seen[symbol] = _t.time()


def repair_holding_prices(username=None, progress=lambda m: None):
    """Make every held symbol valuable. A holding is recorded even when its
    first download fails (Yahoo blocking the phone, a typo), and the daily
    refresh only walks the watchlist, so such a lot used to show no price
    forever. For each held symbol that has no or stale prices:
      - a bare ticker (LICI) moves to its exchange listing;
      - the listing is downloaded again;
      - a listing with under 30 days of history swaps to its sister
        exchange (.BO <-> .NS) when that one has real history.
    username=None repairs every account (background jobs).
    Returns {"fixed": [...], "missing": [...]}, one dict per symbol."""
    import time as _t
    from app.data_sources import downloader
    fixed, missing = [], []
    held = sorted({r[1] for r in db.get_holdings(username)})
    for sym in held:
        target = sym
        if "." not in sym:
            known = [c for c in (f"{sym}.NS", f"{sym}.BO")
                     if db.stored_rows(c)]
            if known:
                target = known[0]
            elif _t.time() - _missing_seen.get(sym, 0) < _MISSING_TTL:
                target = f"{sym}.NS"
            else:
                try:
                    ok, res, _msg = downloader.resolve_and_validate(sym)
                except Exception:
                    ok, res = False, sym
                target = res if ok else f"{sym}.NS"
                if not ok:          # neither listing exists right now
                    for x in (sym, f"{sym}.NS", f"{sym}.BO"):
                        _missing_seen[x] = _t.time()
        if not _needs_prices(target) and target == sym:
            continue
        if _needs_prices(target):
            _fetch(target, progress)
        # Little or nothing on this exchange (Yahoo's .BO coverage is
        # patchy: LICI.BO has 1 day, LICI.NS 4 years): the other listing
        # of the same company may have real history. A genuinely new
        # listing (NSE.BO, no .NS) keeps its short history.
        rows = db.stored_rows(target)
        if rows < 30 and target.endswith((".NS", ".BO")):
            base, suf = target.rsplit(".", 1)
            alt = f"{base}.{'BO' if suf == 'NS' else 'NS'}"
            if _needs_prices(alt):
                _fetch(alt, progress)
            alt_rows = db.stored_rows(alt)
            if alt_rows > rows and (alt_rows >= 30 or rows == 0):
                target = alt
        if db.stored_rows(target) == 0:
            missing.append({"symbol": sym,
                            "reason": "No price history found on Yahoo or "
                                      "the other exchange. Check the ticker "
                                      "(LIC, for example, trades as LICI)."})
            continue
        if target != sym:
            db.repoint_holding_symbol(sym, target, username)
        fixed.append({"symbol": sym, "now": target,
                      "rows": db.stored_rows(target),
                      "through": db.last_stored_date(target)})
        progress(f"[repair] {sym} -> {target}: "
                 f"{db.stored_rows(target)} rows")
    return {"fixed": fixed, "missing": missing}
