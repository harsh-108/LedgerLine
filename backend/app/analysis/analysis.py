"""
Checklist verdict: "should I buy this?"

Runs every quality / valuation / momentum check the free data supports,
shows exactly which passed and failed, and summarizes into a tier, which
is shown as an action: strong = BUY, mixed = HOLD, weak = SELL (2026-10:
the owner asked for explicit buy/sell calls across the app). The pros and
cons stay next to the call, because the reasons are what make it
checkable. It cannot know the user's horizon or risk tolerance, so every
call is labelled "not investment advice".
"""

# The one mapping from the app's tiers to the call people see. Tiers are
# still what is stored and graded on the Scorecard.
ACTION = {"strong": "BUY", "mixed": "HOLD", "weak": "SELL"}

import pandas as pd

from app.core import config
from app.core import database as db
from app.core import memo
from app.analysis.scanner import compute_indicators


def _technicals(symbol):
    rows = db.load_closes(symbol)
    if len(rows) < config.SMA_SLOW + 5:
        return None
    s = pd.Series([r[1] for r in rows],
                  index=pd.to_datetime([r[0] for r in rows]))
    ind = compute_indicators(s)
    yr = s.tail(252)
    return {
        "close": float(s.iloc[-1]),
        "rsi": float(ind["rsi"].iloc[-1]),
        "above_sma200": bool(s.iloc[-1] > ind["sma_slow"].iloc[-1]),
        "trend_up": bool(ind["sma_fast"].iloc[-1] > ind["sma_slow"].iloc[-1]),
        "ret6m": (float(s.iloc[-1] / s.iloc[-127] - 1) * 100
                  if len(s) > 127 else None),
        "pct_off_52w_high": float(s.iloc[-1] / yr.max() - 1) * 100,
        "pct_off_52w_low": float(s.iloc[-1] / yr.min() - 1) * 100,
    }


def _watchlist_pe_median():
    pes = [f.get("trailingPE") for f in db.all_fundamentals().values()
           if f.get("trailingPE")]
    if len(pes) < 5:
        return None
    return float(pd.Series(pes).median())


@memo.memoize("checklist", per_user=True)
def checklist(symbol):
    """Return dict: pros, cons, notes, passed, applicable, tier, tier_text."""
    fund, _updated = db.get_fundamentals(symbol)
    fund = fund or {}
    tech = _technicals(symbol)

    pros, cons, notes = [], [], []
    passed = applicable = 0

    def check(condition, pro_text, con_text):
        nonlocal passed, applicable
        applicable += 1
        if condition:
            passed += 1
            pros.append(pro_text)
        else:
            cons.append(con_text)

    # ---------------- quality (fundamentals)
    roe = fund.get("returnOnEquity")
    if roe is not None:
        check(roe * 100 >= 15,
              f"Healthy ROE of {roe * 100:.1f}%",
              f"Low ROE of {roe * 100:.1f}% (below 15%)")
    margin = fund.get("profitMargins")
    if margin is not None:
        check(margin * 100 >= 8,
              f"Solid net margin of {margin * 100:.1f}%",
              f"Thin net margin of {margin * 100:.1f}%")
    de = fund.get("debtToEquity")
    if de is not None:
        check(de <= 100,
              f"Manageable debt (D/E {de:.0f}%)",
              f"High leverage (D/E {de:.0f}%)")
    dy = fund.get("dividendYield")
    if dy:
        # Yahoo reports this in PERCENT (0.15 = 0.15%). The old "<1 means
        # a fraction" guess turned Kotak's 0.15% into 15%.
        notes.append(f"Pays a dividend ({dy:.2f}% yield)")

    # ---------------- valuation (relative to YOUR watchlist)
    pe = fund.get("trailingPE")
    pe_med = _watchlist_pe_median()
    if pe is not None and pe_med:
        check(pe <= pe_med * 1.2,
              f"P/E {pe:.1f} at or below watchlist median (~{pe_med:.0f})",
              f"P/E {pe:.1f} rich vs watchlist median (~{pe_med:.0f})")

    # ---------------- momentum / trend (technicals)
    if tech:
        check(tech["trend_up"],
              "Uptrend: 50-day SMA above 200-day",
              "Downtrend: 50-day SMA below 200-day")
        check(tech["above_sma200"],
              "Trading above its 200-day average",
              "Trading below its 200-day average")
        if tech["ret6m"] is not None:
            check(tech["ret6m"] > 0,
                  f"Positive 6-month momentum ({tech['ret6m']:+.1f}%)",
                  f"Negative 6-month momentum ({tech['ret6m']:+.1f}%)")
        check(tech["rsi"] < config.RSI_OVERBOUGHT,
              f"RSI {tech['rsi']:.0f} — not overbought",
              f"RSI {tech['rsi']:.0f} — overbought territory")
        if tech["rsi"] < config.RSI_OVERSOLD:
            notes.append(
                f"RSI {tech['rsi']:.0f} is oversold — could be an "
                "opportunity or a falling knife; check the news first")
        if tech["pct_off_52w_high"] > -5 and tech["trend_up"]:
            notes.append("Within 5% of its 52-week high in an uptrend "
                         "(strength, but little margin of safety)")
        if tech["pct_off_52w_low"] < 5 and not tech["trend_up"]:
            notes.append("Sitting near its 52-week low in a downtrend — "
                         "understand WHY before touching it")

    if applicable == 0:
        return None

    ratio = passed / applicable
    if ratio >= 0.75:
        tier, tier_text = "strong", (
            "BUY. Passes most checks: quality, valuation and trend line up. "
            "Decide the position size and the price at which you would exit "
            "before buying.")
    elif ratio >= 0.45:
        tier, tier_text = "mixed", (
            "HOLD. Some strengths, some real concerns. If you own it, hold "
            "and watch the failed checks; if you don't, wait for them to "
            "improve before buying.")
    else:
        tier, tier_text = "weak", (
            "SELL. Fails most checks right now. If you own it, consider "
            "selling or cutting the position; if you don't, avoid buying "
            "until the checks improve.")

    return {
        "symbol": symbol, "pros": pros, "cons": cons, "notes": notes,
        "passed": passed, "applicable": applicable,
        "tier": tier, "tier_text": tier_text, "action": ACTION[tier],
        "decision_frame": {
            "strong": ("Nothing here argues against owning it. Whether to "
                       "buy is about the price you pay vs your alternatives "
                       "and how it fits your portfolio — check the base "
                       "rates below and recent news the data can't see."),
            "mixed": ("Neither a clear yes nor a clear no. Decide which of "
                      "the cons above would actually break your thesis — "
                      "that answer, not the tier, is the decision."),
            "weak": ("The burden of proof is on buying. If you already "
                     "hold it, name the one specific strength you are "
                     "betting on; if you can't, that is itself an answer."),
        }[tier],
        "data_coverage": ("full" if (fund and tech) else
                          "technicals only" if tech else "fundamentals only"),
    }
