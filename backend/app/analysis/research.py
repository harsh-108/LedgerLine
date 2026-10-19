"""
Deeper per-stock research on the free stack — the Kite/Groww-style tabs.

  statements(symbol)  — quarterly + annual revenue / profit / margins,
                        balance-sheet basics, cash flow (yfinance
                        statements, cached in SQLite for 7 days)
  events(symbol)      — next earnings date, recent dividends, splits
  peers(symbol)       — same-sector comparison from stored fundamentals

Coverage honesty: Yahoo carries full statements for most NSE large/mid
caps; small caps and BSE-only scrips often return partial or empty
statements. Every function degrades to "not available" rather than
guessing, and the UI says so.
"""

import datetime as dt
import json

import pandas as pd

from app.core import database as db

STATEMENTS_TTL_DAYS = 7


# ---------------------------------------------------------------- helpers
def _row(frame, names):
    """First matching row label from a yfinance statement frame."""
    if frame is None or frame.empty:
        return None
    for n in names:
        if n in frame.index:
            return frame.loc[n]
    return None


def _series_to_periods(rev, ni, op):
    out = []
    if rev is None:
        return out
    for col in rev.index if isinstance(rev, pd.Series) else []:
        pass
    for col in rev.dropna().index:
        r = float(rev[col])
        item = {"period": str(pd.Timestamp(col).date()), "revenue": r}
        if ni is not None and col in ni and ni[col] == ni[col]:
            item["net_income"] = float(ni[col])
            item["net_margin"] = round(float(ni[col]) / r * 100, 1) if r else None
        if op is not None and col in op and op[col] == op[col]:
            item["op_income"] = float(op[col])
        out.append(item)
    out.sort(key=lambda x: x["period"])
    return out[-8:]      # last 8 periods is plenty for the charts


# ------------------------------------------------------------- statements
def fetch_statements(symbol):
    """Pull statements from Yahoo and reduce to the chart-ready shape.
    Slow (2-5 s); call lazily or from a background refresh."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    data = {"fetched": dt.date.today().isoformat()}

    for kind, inc in (("annual", t.income_stmt),
                      ("quarterly", t.quarterly_income_stmt)):
        rev = _row(inc, ["Total Revenue", "Operating Revenue"])
        ni = _row(inc, ["Net Income",
                        "Net Income Common Stockholders"])
        op = _row(inc, ["Operating Income", "EBIT"])
        data[kind] = _series_to_periods(rev, ni, op)

    bs = t.balance_sheet
    eq = _row(bs, ["Stockholders Equity", "Common Stock Equity"])
    debt = _row(bs, ["Total Debt"])
    cash = _row(bs, ["Cash And Cash Equivalents",
                     "Cash Cash Equivalents And Short Term Investments"])
    data["balance"] = []
    if eq is not None:
        for col in eq.dropna().index:
            item = {"period": str(pd.Timestamp(col).date()),
                    "equity": float(eq[col])}
            if debt is not None and col in debt and debt[col] == debt[col]:
                item["debt"] = float(debt[col])
            if cash is not None and col in cash and cash[col] == cash[col]:
                item["cash"] = float(cash[col])
            data["balance"].append(item)
        data["balance"].sort(key=lambda x: x["period"])
        data["balance"] = data["balance"][-5:]

    cf = t.cashflow
    ocf = _row(cf, ["Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities"])
    fcf = _row(cf, ["Free Cash Flow"])
    data["cashflow"] = []
    if ocf is not None:
        for col in ocf.dropna().index:
            item = {"period": str(pd.Timestamp(col).date()),
                    "operating": float(ocf[col])}
            if fcf is not None and col in fcf and fcf[col] == fcf[col]:
                item["free"] = float(fcf[col])
            data["cashflow"].append(item)
        data["cashflow"].sort(key=lambda x: x["period"])
        data["cashflow"] = data["cashflow"][-5:]

    has_any = any(data.get(k) for k in ("annual", "quarterly",
                                        "balance", "cashflow"))
    return data if has_any else None


def statements(symbol, force=False):
    """Cached statements: DB copy if under a week old, else live fetch."""
    if not force:
        cached = db.get_statements(symbol)
        if cached:
            payload, updated = cached
            age = (dt.date.today()
                   - dt.date.fromisoformat(updated[:10])).days
            if age <= STATEMENTS_TTL_DAYS:
                return json.loads(payload)
    data = fetch_statements(symbol)
    if data:
        db.save_statements(symbol, json.dumps(data))
    return data


# ----------------------------------------------------------------- events
def events(symbol):
    """Next earnings date + recent dividends + split history. Live call
    (fast-ish); degrades field-by-field."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    out = {"next_earnings": None, "dividends": [], "splits": []}
    try:
        cal = t.calendar
        dates = (cal or {}).get("Earnings Date") if isinstance(cal, dict) \
            else None
        if dates:
            out["next_earnings"] = str(dates[0])
    except Exception:
        pass
    try:
        divs = t.dividends.tail(6)
        out["dividends"] = [{"date": str(i.date()), "amount": float(v)}
                            for i, v in divs.items()][::-1]
    except Exception:
        pass
    try:
        sp = t.splits.tail(5)
        out["splits"] = [{"date": str(i.date()), "ratio": float(v)}
                         for i, v in sp.items()][::-1]
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ peers
def _ret1y(symbol):
    closes = [c[1] for c in db.load_closes(symbol)]
    if len(closes) < 253 or not closes[-253]:        # 252 sessions back
        return None
    return round((closes[-1] / closes[-253] - 1) * 100, 1)


def peers(symbol):
    """Same-sector stocks from everything we have fundamentals for,
    sorted by market cap, the subject marked. Uses the whole DB (so a
    prepared NIFTY universe widens the peer set automatically)."""
    funds = db.all_fundamentals()
    me = funds.get(symbol)
    if not me or not me.get("sector"):
        return None
    sector = me["sector"]
    # Yahoo's "sector" is very coarse (Asian Paints, UltraTech, JSW Steel
    # and Hindalco are all "Basic Materials"). Prefer the finer "industry"
    # when at least one other stored stock shares it; fall back to sector.
    industry = me.get("industry")
    basis, key = "sector", sector
    if industry and sum(1 for f in funds.values()
                        if f.get("industry") == industry) >= 2:
        basis, key = "industry", industry
    rows = []
    for sym, f in funds.items():
        if f.get(basis) != key:
            continue
        mcap = f.get("marketCap")
        rows.append({
            "symbol": sym.split(".")[0],
            "is_subject": sym == symbol,
            "mcap_cr": round(mcap / 1e7) if mcap else None,
            "pe": round(f["trailingPE"], 1) if f.get("trailingPE") else None,
            "roe": round(f["returnOnEquity"] * 100, 1)
            if f.get("returnOnEquity") else None,
            "margin": round(f["profitMargins"] * 100, 1)
            if f.get("profitMargins") else None,
            "ret1y": _ret1y(sym),
        })
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: -(r["mcap_cr"] or 0))
    pes = [r["pe"] for r in rows if r["pe"]]
    return {"sector": sector, "industry": industry,
            "grouped_by": basis, "group": key,
            "note": (f"Peers = stored stocks sharing the same Yahoo {basis} "
                     f"'{key}'. Only stocks in the watchlist / prepared "
                     "universe appear; true competitors may be missing."),
            "rows": rows[:12],
            "median_pe": round(pd.Series(pes).median(), 1) if pes else None}
