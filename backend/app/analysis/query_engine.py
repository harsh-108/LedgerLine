"""
Screener-style query language over the watchlist.

Example queries:
    pe < 20 and roe > 15
    market cap > 100000 and dividend yield > 1
    rsi < 35 and trend = up
    sector = energy and pb < 3 sort by roe desc top 5
    return 1y > 20 sort by market cap desc

Grammar (tolerant, case-insensitive):
    condition  := FIELD OP VALUE
    query      := condition (and|or condition)* [sort by FIELD (asc|desc)] [top N]
    OP         := > | < | >= | <= | = | !=
Field names accept many synonyms ("pe", "p/e", "price to earnings"...).
Values: numbers (market cap in ₹ Crore) or words (sector names, up/down).

This is deliberately a whitelist parser — user text is never eval'd.
"""

import re

import pandas as pd

from app.core import database as db
from app.analysis.scanner import compute_indicators
from app.core import config

# canonical field -> synonyms (longest matched first at parse time)
FIELD_SYNONYMS = {
    "mcap":    ["market capitalization", "market cap", "marketcap", "mcap"],
    "pe":      ["price to earnings", "price to earning", "p/e", "pe ratio", "pe"],
    "pb":      ["price to book", "p/b", "pb ratio", "pb"],
    "roe":     ["return on equity", "roe"],
    "margin":  ["net profit margin", "net margin", "profit margin", "margin"],
    "divyield": ["dividend yield", "div yield", "divyield", "yield"],
    "de":      ["debt to equity", "debt/equity", "d/e", "de ratio", "de"],
    "eps":     ["earnings per share", "eps"],
    "beta":    ["beta"],
    "close":   ["current price", "last close", "price", "close", "cmp"],
    "rsi":     ["rsi"],
    "ret1m":   ["return 1m", "1m return", "ret1m", "return 1 month"],
    "ret6m":   ["return 6m", "6m return", "ret6m", "return 6 months"],
    "ret1y":   ["return 1y", "1y return", "ret1y", "return 1 year"],
    "trend":   ["trend"],
    "sector":  ["sector"],
    "name":    ["symbol", "name", "stock"],
}

NUMERIC_FIELDS = {"mcap", "pe", "pb", "roe", "margin", "divyield", "de",
                  "eps", "beta", "close", "rsi", "ret1m", "ret6m", "ret1y"}
TEXT_FIELDS = {"trend", "sector", "name"}

DISPLAY = {
    "name": "Symbol", "sector": "Sector", "mcap": "Mkt cap (₹Cr)",
    "close": "Close", "pe": "P/E", "pb": "P/B", "roe": "ROE %",
    "margin": "Margin %", "divyield": "Div yield %", "de": "D/E",
    "eps": "EPS", "beta": "Beta", "rsi": "RSI", "trend": "Trend",
    "ret1m": "1M %", "ret6m": "6M %", "ret1y": "1Y %",
}

_OPS = {
    ">=": lambda s, v: s >= v, "<=": lambda s, v: s <= v,
    "!=": lambda s, v: s != v, ">": lambda s, v: s > v,
    "<": lambda s, v: s < v, "=": lambda s, v: s == v,
}


class QueryError(ValueError):
    pass


# ------------------------------------------------------------- build metrics
def _pct_return(series, days):
    if len(series) > days:
        return (series.iloc[-1] / series.iloc[-days - 1] - 1) * 100
    return None


def build_metrics(symbols=None):
    """One row per stock: fundamentals + technicals combined.
    Default universe = the watchlist; pass an explicit symbol list to
    screen a wider universe (see universe.py)."""
    funds = db.all_fundamentals()
    if symbols is None:
        symbols = [w[2] for w in db.get_watchlist("stock") if w[2]]
    rows = []
    for symbol in symbols:
        f = funds.get(symbol, {})
        closes = db.load_closes(symbol)
        row = {
            "name": symbol,
            "sector": (f.get("sector") or "").lower(),
            "sector_full": ((f.get("sector") or "") + " "
                            + (f.get("industry") or "")).lower(),
            "mcap": (f.get("marketCap") or 0) / 1e7 or None,
            "pe": f.get("trailingPE"),
            "pb": f.get("priceToBook"),
            "roe": f.get("returnOnEquity") * 100 if f.get("returnOnEquity") else None,
            "margin": f.get("profitMargins") * 100 if f.get("profitMargins") else None,
            "divyield": None,
            "de": f.get("debtToEquity"),
            "eps": f.get("trailingEps"),
            "beta": f.get("beta"),
            "close": None, "rsi": None, "trend": None,
            "ret1m": None, "ret6m": None, "ret1y": None,
        }
        dy = f.get("dividendYield")
        if dy is not None:
            # already a percentage from Yahoo (0.54 = 0.54%, not 54%)
            row["divyield"] = dy
        if len(closes) >= config.SMA_SLOW + 5:
            s = pd.Series([c[1] for c in closes],
                          index=pd.to_datetime([c[0] for c in closes]))
            ind = compute_indicators(s)
            row["close"] = round(float(s.iloc[-1]), 2)
            row["rsi"] = round(float(ind["rsi"].iloc[-1]), 1)
            row["trend"] = ("up" if ind["sma_fast"].iloc[-1] >
                            ind["sma_slow"].iloc[-1] else "down")
            row["ret1m"] = _pct_return(s, 21)
            row["ret6m"] = _pct_return(s, 126)
            row["ret1y"] = _pct_return(s, 252)
        rows.append(row)
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- parser
def _normalize_fields(q):
    """Replace every synonym with its canonical token."""
    # longest synonyms first so "market cap" wins over "cap"
    pairs = [(syn, canon) for canon, syns in FIELD_SYNONYMS.items()
             for syn in syns]
    pairs.sort(key=lambda p: -len(p[0]))
    for syn, canon in pairs:
        q = re.sub(rf"\b{re.escape(syn)}\b", canon, q)
    return q


def _parse_condition(text):
    m = re.match(r"^\s*(\w+)\s*(>=|<=|!=|=|>|<)\s*(.+?)\s*$", text)
    if not m:
        raise QueryError(f"Couldn't understand condition: '{text.strip()}'")
    field, op, value = m.group(1), m.group(2), m.group(3).strip().strip("'\"")
    if field not in NUMERIC_FIELDS | TEXT_FIELDS:
        raise QueryError(f"Unknown field '{field}'. Known: "
                         + ", ".join(sorted(NUMERIC_FIELDS | TEXT_FIELDS)))
    if field in NUMERIC_FIELDS:
        try:
            value = float(value.replace(",", "").replace("%", ""))
        except ValueError:
            raise QueryError(f"'{field}' needs a number, got '{value}'")
        if op not in _OPS:
            raise QueryError(f"Bad operator '{op}'")
    else:
        value = value.lower()
        if op not in ("=", "!="):
            raise QueryError(f"Text field '{field}' only supports = and !=")
    return field, op, value


def run_query(query, metrics=None):
    """Execute a query string. Returns (DataFrame, explanation)."""
    if metrics is None:
        metrics = build_metrics()
    if metrics.empty:
        raise QueryError("No stock data yet — run a download first.")

    q = _normalize_fields(query.lower().strip())

    # sort / top clauses
    sort_field, sort_asc, top_n = None, False, None
    m = re.search(r"\btop\s+(\d+)\s*$", q)
    if m:
        top_n = int(m.group(1))
        q = q[:m.start()].strip()
    m = re.search(r"\bsort\s+by\s+(\w+)(?:\s+(asc|desc))?\s*$", q)
    if m:
        sort_field = m.group(1)
        if sort_field not in metrics.columns:
            raise QueryError(f"Can't sort by unknown field '{sort_field}'")
        sort_asc = (m.group(2) == "asc")
        q = q[:m.start()].strip()

    mask = pd.Series(True, index=metrics.index)
    explanation = []
    diag_conds = []
    if q:
        # split into OR groups of AND conditions
        or_groups = re.split(r"\bor\b", q)
        or_mask = pd.Series(False, index=metrics.index)
        cond_masks = []   # (label, field, mask) — for near-miss diagnosis
        for group in or_groups:
            g_mask = pd.Series(True, index=metrics.index)
            for cond in re.split(r"\band\b", group):
                if not cond.strip():
                    continue
                field, op, value = _parse_condition(cond)
                col = metrics[field]
                cond_label = f"{DISPLAY.get(field, field)} {op} {value}"
                if field == "sector":
                    # Yahoo's taxonomy is inconsistent ("Technology" vs
                    # "Information Technology Services", banks live under
                    # "Financial Services"), so match any meaningful token
                    # of the query against sector+industry combined.
                    hay = metrics["sector_full"].fillna("")
                    tokens = [t for t in value.split() if len(t) >= 3] or [value]
                    c = pd.Series(False, index=metrics.index)
                    for t in tokens:
                        c |= hay.str.contains(re.escape(t), na=False)
                    if op == "!=":
                        c = ~c
                elif field in TEXT_FIELDS:
                    c = _OPS[op](col.fillna(""), value)
                else:
                    c = _OPS[op](col, value) & col.notna()
                g_mask &= c
                explanation.append(cond_label)
                dc = {"condition": cond_label, "matched": int(c.sum())}
                if field == "sector" and dc["matched"] == 0:
                    dc["available"] = sorted(
                        {s.title() for s in metrics["sector"].dropna()
                         if s})
                diag_conds.append(dc)
                if len(or_groups) == 1:
                    cond_masks.append((cond_label, field, c))
            or_mask |= g_mask
        mask = or_mask

    # near-misses: when an AND-only query returns nothing, name the
    # stocks that passed all conditions but ONE, and which one failed —
    # turns "no rows" into "INFY misses only P/E < 20 (it's 24.1)".
    near = []
    if q and len(or_groups) == 1 and len(cond_masks) >= 2 \
            and not mask.any():
        passed = sum(m for _l, _f, m in cond_masks)
        for idx in metrics.index[passed == len(cond_masks) - 1][:60]:
            fails = [(l, f) for (l, f, m) in cond_masks if not m[idx]]
            if not fails:
                continue
            label, field = fails[0]
            v = metrics.at[idx, field]
            if isinstance(v, float):
                v = round(v, 2)
            near.append({"name": str(metrics.at[idx, "name"]).split(".")[0],
                         "failed": label,
                         "value": None if v != v else v})
        near = near[:8]

    diagnostics = {
        "near_misses": near,
        "universe_size": int(len(metrics)),
        "with_fundamentals": int((metrics["pe"].notna()
                                  | metrics["mcap"].notna()).sum()),
        "with_technicals": int(metrics["rsi"].notna().sum())
                           if "rsi" in metrics else 0,
        "conditions": diag_conds,
    }
    result = metrics[mask].copy()
    if sort_field:
        result = result.sort_values(sort_field, ascending=sort_asc,
                                    na_position="last")
    elif "mcap" in result:
        result = result.sort_values("mcap", ascending=False, na_position="last")
    if top_n:
        result = result.head(top_n)

    # pretty output — fixed column order, internal columns hidden
    col_order = [c for c in DISPLAY if c in result.columns]
    out = result[col_order].rename(columns=DISPLAY)
    for col in ["Mkt cap (₹Cr)"]:
        if col in out:
            out[col] = out[col].round(0)
    for col in ["P/E", "P/B", "ROE %", "Margin %", "Div yield %", "D/E",
                "EPS", "Beta", "1M %", "6M %", "1Y %"]:
        if col in out:
            out[col] = out[col].astype(float).round(2)
    return (out.reset_index(drop=True),
            " AND ".join(explanation) or "all stocks",
            diagnostics)


EXAMPLES = [
    "pe < 25 and roe > 15",
    "market cap > 100000 sort by roe desc",
    "rsi < 40 and trend = up",
    "sector = bank and pb < 2",
    "dividend yield > 1.5 sort by dividend yield desc top 5",
    "return 1y > 20 and pe < 30",
]