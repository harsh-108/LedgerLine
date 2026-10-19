"""
Base rates: what ACTUALLY happened after each signal in this stock's own
history. The honest alternative to a BUY/SELL prediction.

For every past occurrence of a signal (golden cross, death cross, RSI
oversold/overbought — same definitions as scanner.py), measure the
stock's forward return 1, 3, and 6 months later, then summarize:
occurrences, median return, hit rate (% positive), best, worst.

Alongside each signal, a BASELINE: the same statistics for *every*
possible period of that length in the stock's history. A signal only
means something if its numbers beat the baseline — otherwise it just
inherited the stock's general drift.

What this is NOT: a prediction. Small samples (a signal that fired 4
times) prove nothing; regimes change; and the spread (best-to-worst)
is part of the answer, not noise around it. That's why every stat is
reported with its n, and why n < MIN_OCCURRENCES is flagged instead of
summarized.
"""

import pandas as pd

from app.core import config

# forward horizons in trading days (~21 per month)
HORIZONS = {"1m": 21, "3m": 63, "6m": 126}
MIN_OCCURRENCES = 3

SIGNAL_LABELS = {
    "GOLDEN_CROSS": "Golden cross (SMA50 above SMA200)",
    "DEATH_CROSS": "Death cross (SMA50 below SMA200)",
    "RSI_OVERSOLD": f"RSI dropped below {config.RSI_OVERSOLD}",
    "RSI_OVERBOUGHT": f"RSI rose above {config.RSI_OVERBOUGHT}",
}


def _event_dates(df):
    """Positional indices where each signal fired, using scanner.py's
    exact crossing definitions applied across the whole history."""
    f, s, r = df["sma_fast"], df["sma_slow"], df["rsi"]
    pf, ps, pr = f.shift(1), s.shift(1), r.shift(1)
    return {
        "GOLDEN_CROSS": df.index[(pf <= ps) & (f > s)],
        "DEATH_CROSS": df.index[(pf >= ps) & (f < s)],
        "RSI_OVERSOLD": df.index[(pr >= config.RSI_OVERSOLD)
                                 & (r < config.RSI_OVERSOLD)],
        "RSI_OVERBOUGHT": df.index[(pr <= config.RSI_OVERBOUGHT)
                                   & (r > config.RSI_OVERBOUGHT)],
    }


def _fwd_returns(close, positions, ndays):
    """Percent return ndays trading days after each position; events too
    close to the end of history (outcome not yet known) are dropped."""
    out = []
    for p in positions:
        if p + ndays < len(close):
            out.append((close.iloc[p + ndays] / close.iloc[p] - 1) * 100)
    return pd.Series(out, dtype=float)


def _summary(rets):
    if len(rets) < MIN_OCCURRENCES:
        return {"n": int(len(rets))}
    return {
        "n": int(len(rets)),
        "median": round(float(rets.median()), 1),
        "hit_rate": round(float((rets > 0).mean() * 100)),
        "best": round(float(rets.max()), 1),
        "worst": round(float(rets.min()), 1),
    }


def _active_now(df):
    """Which of the four states applies today (for highlighting only)."""
    last, prev10 = df.iloc[-1], df.tail(11)
    active = []
    crosses = _event_dates(df.tail(12))
    if len(crosses["GOLDEN_CROSS"]):
        active.append("GOLDEN_CROSS")
    if len(crosses["DEATH_CROSS"]):
        active.append("DEATH_CROSS")
    if pd.notna(last["rsi"]):
        if last["rsi"] < config.RSI_OVERSOLD:
            active.append("RSI_OVERSOLD")
        elif last["rsi"] > config.RSI_OVERBOUGHT:
            active.append("RSI_OVERBOUGHT")
    return active


def base_rates(df):
    """df: charts.load_stock_df output (close/sma_fast/sma_slow/rsi).
    Returns the full base-rate report for the drawer, or None if the
    history is too short to say anything."""
    if df is None or len(df) < 260:      # need ~1y just for the baseline
        return None
    close = df["close"]
    pos_of = {ts: i for i, ts in enumerate(df.index)}

    baseline = {}
    for hname, nd in HORIZONS.items():
        all_fwd = (close.shift(-nd) / close - 1).dropna() * 100
        baseline[hname] = _summary(all_fwd)

    events = _event_dates(df)
    signals = []
    for sig, dates in events.items():
        positions = [pos_of[d] for d in dates]
        horizons = {h: _summary(_fwd_returns(close, positions, nd))
                    for h, nd in HORIZONS.items()}
        signals.append({
            "signal": sig,
            "label": SIGNAL_LABELS[sig],
            "occurrences": int(len(positions)),
            "horizons": horizons,
        })

    years = round((df.index[-1] - df.index[0]).days / 365.25, 1)
    return {
        "years": years,
        "baseline": baseline,
        "signals": signals,
        "active": _active_now(df),
        "note": ("Measured history, not prediction. Small samples prove "
                 "nothing; past regimes need not repeat; the worst case "
                 "is part of the answer."),
    }
