"""
Pattern detection — the honest version of "AI chart reading".

Detects classic candlestick / structure patterns with deterministic,
inspectable rules (no black box), then does the only thing that makes a
pattern worth knowing: measures what happened after every PAST
occurrence of that same pattern on THIS stock — count, median 1-month
forward return, hit rate — next to the stock's own baseline.

Why rules, not a neural net: pattern names are definitions, so a
transparent rule detects them exactly as well as a CNN would, and the
CNN adds only unfalsifiable confidence. The genuinely unknown part —
whether a pattern predicts anything — is answered by measurement, and
the honest answer is usually "barely, if at all". Showing that IS the
feature.

Detected:
  candles   — hammer, shooting star, bullish/bearish engulfing, doji
  structure — near support / near resistance (swing-point clusters),
              distance from 52-week high/low, trend + volatility regime
"""

import numpy as np
import pandas as pd

FWD_DAYS = 21          # 1-month forward window for outcome measurement
MIN_OCCURRENCES = 5


# ------------------------------------------------------- candle patterns
def _candle_masks(df):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    avg_body = body.rolling(20).mean()

    po, pc = o.shift(1), c.shift(1)
    downtrend = c < c.rolling(10).mean()
    uptrend = c > c.rolling(10).mean()

    return {
        "HAMMER": ((lower >= 2 * body) & (upper <= 0.3 * body.clip(lower=1e-9))
                   & (body > 0) & downtrend),
        "SHOOTING_STAR": ((upper >= 2 * body)
                          & (lower <= 0.3 * body.clip(lower=1e-9))
                          & (body > 0) & uptrend),
        "BULL_ENGULF": ((pc < po) & (c > o) & (c >= po) & (o <= pc)
                        & (body > avg_body)),
        "BEAR_ENGULF": ((pc > po) & (c < o) & (c <= po) & (o >= pc)
                        & (body > avg_body)),
        "DOJI": (body <= 0.1 * rng),
    }


LABELS = {
    "HAMMER": ("Hammer", "long lower wick after weakness — "
               "taught as a reversal-up hint"),
    "SHOOTING_STAR": ("Shooting star", "long upper wick after strength — "
                      "taught as a reversal-down hint"),
    "BULL_ENGULF": ("Bullish engulfing", "big up-candle swallowing the "
                    "prior down-candle"),
    "BEAR_ENGULF": ("Bearish engulfing", "big down-candle swallowing the "
                    "prior up-candle"),
    "DOJI": ("Doji", "open ≈ close — indecision"),
}


def _fwd_stats(close, mask):
    fwd = (close.shift(-FWD_DAYS) / close - 1) * 100
    rets = fwd[mask].dropna()
    if len(rets) < MIN_OCCURRENCES:
        return {"n": int(len(rets))}
    return {"n": int(len(rets)),
            "median": round(float(rets.median()), 1),
            "hit_rate": round(float((rets > 0).mean() * 100))}


# --------------------------------------------------- support / resistance
def _swing_levels(df, lookback=250, wing=5, tol=0.015):
    """Cluster swing highs/lows of the last ~year into levels."""
    d = df.tail(lookback)
    highs, lows = [], []
    h, l = d["high"].values, d["low"].values
    for i in range(wing, len(d) - wing):
        if h[i] == max(h[i - wing:i + wing + 1]):
            highs.append(h[i])
        if l[i] == min(l[i - wing:i + wing + 1]):
            lows.append(l[i])

    def cluster(vals):
        vals = sorted(vals)
        out = []
        for v in vals:
            if out and abs(v - out[-1][-1]) / v < tol:
                out[-1].append(v)
            else:
                out.append([v])
        # a level touched once is noise; twice+ is a level
        return [round(float(np.mean(g)), 2) for g in out if len(g) >= 2]

    return cluster(lows), cluster(highs)


# ------------------------------------------------------------------ main
def detect(df):
    """Full pattern report for the dialog. df = charts.load_stock_df."""
    if df is None or len(df) < 120:
        return None
    close = df["close"]
    last = float(close.iloc[-1])
    masks = _candle_masks(df)

    # today's active candle patterns + base rates for each type
    recent = df.index[-1]
    candles = []
    baseline = _fwd_stats(close, pd.Series(True, index=df.index))
    for key, mask in masks.items():
        active = bool(mask.loc[recent]) if recent in mask.index else False
        stats = _fwd_stats(close, mask)
        if active or stats.get("n", 0) >= MIN_OCCURRENCES:
            name, desc = LABELS[key]
            candles.append({"key": key, "name": name, "desc": desc,
                            "active_today": active, **stats})
    candles.sort(key=lambda x: (not x["active_today"], -x.get("n", 0)))

    # structure
    supports, resistances = _swing_levels(df)
    near_sup = [s for s in supports if 0 <= (last - s) / last < 0.03]
    near_res = [r for r in resistances if 0 <= (r - last) / last < 0.03]
    below = [s for s in supports if s < last]
    above = [r for r in resistances if r > last]

    yr = df.tail(252)
    hi, lo = float(yr["high"].max()), float(yr["low"].min())

    # regime: trend via SMA structure, volatility vs own history
    vol20 = close.pct_change().rolling(20).std() * np.sqrt(252) * 100
    vol_now = float(vol20.iloc[-1]) if vol20.notna().iloc[-1] else None
    vol_pctile = (round(float((vol20.dropna() <= vol_now).mean() * 100))
                  if vol_now is not None else None)
    trend = ("up" if df["sma_fast"].iloc[-1] > df["sma_slow"].iloc[-1]
             else "down")

    return {
        "baseline_1m": baseline,
        "candles": candles,
        "structure": {
            "last": round(last, 2),
            "near_support": near_sup[-1] if near_sup else None,
            "near_resistance": near_res[0] if near_res else None,
            "next_support": round(max(below), 2) if below else None,
            "next_resistance": round(min(above), 2) if above else None,
            "off_52w_high_pct": round((last / hi - 1) * 100, 1),
            "off_52w_low_pct": round((last / lo - 1) * 100, 1),
        },
        "regime": {
            "trend": trend,
            "ann_vol_pct": round(vol_now, 1) if vol_now else None,
            "vol_percentile": vol_pctile,
            "read": (f"{'Up' if trend == 'up' else 'Down'}trend, "
                     + (f"volatility at its {vol_pctile}th percentile — "
                        + ("quiet tape" if vol_pctile < 35 else
                           "stormy tape" if vol_pctile > 75 else
                           "normal tape")
                        if vol_pctile is not None else "")),
        },
        "note": ("Patterns are folklore until measured. The base rates "
                 "above are this stock's own record; compare every "
                 "pattern against the baseline before caring."),
    }
