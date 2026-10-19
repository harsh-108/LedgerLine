"""
Backtester — the honesty machine.

Simulates the app's own golden-cross signal (long when SMA-50 > SMA-200,
flat otherwise) on stored history, with per-side transaction costs, and
compares it against simply buying and holding. No shorting, no leverage,
next-day execution at close after a signal (no lookahead).

Costs default to 0.20% per side — roughly delivery STT (0.1%) + stamp,
exchange charges, GST and slippage for a discount broker. Adjust to taste;
the POINT of this module is watching costs eat a strategy alive.

This is an educational simulator: past performance predicts nothing, and
a strategy that won historically can lose from tomorrow onward.
"""

import numpy as np
import pandas as pd

from app.analysis import charts
from app.core import config
from app.core import memo


# --------------------------------------------------------------- strategies
# Each returns a 0/1 "want to be long" series from the indicator frame.
# All are classic, widely-taught rules — that is the point: test the
# folklore against buy-and-hold with real costs, per rule, per stock.

def _sig_golden_cross(d):
    """Trend-following: long while SMA-50 is above SMA-200."""
    return (d["sma_fast"] > d["sma_slow"]).astype(int)


def _sig_price_above_200(d):
    """The 200-day filter: long while price closes above its 200-day SMA."""
    return (d["close"] > d["sma_slow"]).astype(int)


def _sig_rsi_reversion(d):
    """Mean reversion: buy fear (RSI < 30), sell the recovery (RSI > 60).
    Between the two thresholds, keep the previous state."""
    s = pd.Series(np.nan, index=d.index)
    s[d["rsi"] < 30] = 1
    s[d["rsi"] > 60] = 0
    return s.ffill().fillna(0).astype(int)


def _sig_macd(d):
    """Momentum: long while MACD (12-26 EMA spread) is above its 9-EMA
    signal line."""
    macd = (d["close"].ewm(span=12, adjust=False).mean()
            - d["close"].ewm(span=26, adjust=False).mean())
    return (macd > macd.ewm(span=9, adjust=False).mean()).astype(int)


def _sig_breakout(d):
    """Channel breakout (Donchian / turtle-style): enter on a close above
    the prior 20-day high, exit on a close below the prior 10-day low."""
    hi = d["close"].rolling(20).max().shift(1)
    lo = d["close"].rolling(10).min().shift(1)
    s = pd.Series(np.nan, index=d.index)
    s[d["close"] > hi] = 1
    s[d["close"] < lo] = 0
    return s.ffill().fillna(0).astype(int)


STRATEGIES = {
    "golden_cross": {
        "label": "Golden cross (SMA 50/200)",
        "desc": "Long while the 50-day average is above the 200-day.",
        "why_in": "the 50-day average moved above the 200-day",
        "why_out": "the 50-day average fell below the 200-day",
        "fn": _sig_golden_cross,
    },
    "price_above_200": {
        "label": "200-day filter",
        "desc": "Long while price closes above its 200-day average.",
        "why_in": "the price closed above its 200-day average",
        "why_out": "the price closed below its 200-day average",
        "fn": _sig_price_above_200,
    },
    "rsi_reversion": {
        "label": "RSI mean reversion (30/60)",
        "desc": "Buy when RSI drops under 30, exit when it recovers past 60.",
        "why_in": "RSI dropped under 30",
        "why_out": "RSI recovered past 60",
        "fn": _sig_rsi_reversion,
    },
    "macd": {
        "label": "MACD signal cross (12-26-9)",
        "desc": "Long while the MACD line is above its signal line.",
        "why_in": "the MACD line crossed above its signal line",
        "why_out": "the MACD line crossed below its signal line",
        "fn": _sig_macd,
    },
    "breakout": {
        "label": "20/10 channel breakout",
        "desc": "Enter on a 20-day-high close, exit on a 10-day-low close.",
        "why_in": "the stock closed at a 20-day high",
        "why_out": "the stock closed at a 10-day low",
        "fn": _sig_breakout,
    },
}


@memo.memoize("backtest", max_items=30)
def run(symbol, cost_per_side_pct=0.20, strategy="golden_cross"):
    """Backtest one rule on one symbol. Returns dict or None."""
    if strategy not in STRATEGIES:
        strategy = "golden_cross"
    df = charts.load_stock_df(symbol)
    if df is None or len(df) < config.SMA_SLOW + 60:
        return None
    d = df.dropna(subset=["sma_fast", "sma_slow", "rsi"]).copy()
    if len(d) < 60:
        return None

    # signal today -> position from TOMORROW (shift avoids lookahead)
    d["signal"] = STRATEGIES[strategy]["fn"](d)
    d["position"] = d["signal"].shift(1).fillna(0)
    d["ret"] = d["close"].pct_change().fillna(0)

    cost = cost_per_side_pct / 100
    d["trade"] = d["position"].diff().abs().fillna(d["position"])
    d["strat_ret"] = d["position"] * d["ret"] - d["trade"] * cost

    d["strat_curve"] = (1 + d["strat_ret"]).cumprod()
    d["hold_curve"] = (1 + d["ret"]).cumprod()

    years = (d.index[-1] - d.index[0]).days / 365.25
    if years < 0.5:
        return None

    def cagr(curve):
        return (curve.iloc[-1] ** (1 / years) - 1) * 100

    def max_dd(curve):
        return ((curve / curve.cummax()) - 1).min() * 100

    # trade log
    entries = d.index[(d["position"].diff() == 1)]
    exits = d.index[(d["position"].diff() == -1)]
    trades = []
    for i, ein in enumerate(entries):
        eout = exits[i] if i < len(exits) else d.index[-1]
        pin, pout = d.loc[ein, "close"], d.loc[eout, "close"]
        gross = (pout / pin - 1) * 100
        net = gross - 2 * cost_per_side_pct
        trades.append({
            "Entry": ein.date(), "Exit": eout.date(),
            "Entry px": round(pin, 2), "Exit px": round(pout, 2),
            "Net %": round(net, 2),
        })
    wins = sum(1 for t in trades if t["Net %"] > 0)

    n_sides = int(d["trade"].sum())
    total_cost_drag = (1 + d["position"] * d["ret"]).prod() - d["strat_curve"].iloc[-1]

    # what the rule says TODAY: invested or out, and since when.
    # This is the rule's own current state — a fact about the rule,
    # not a recommendation from the app.
    now_invested = bool(d["signal"].iloc[-1])
    flips = d.index[d["signal"].diff().abs() > 0]
    now_since = flips[-1].date().isoformat() if len(flips) else None

    return {
        "symbol": symbol,
        "now": {"invested": now_invested, "since": now_since,
                "why": STRATEGIES[strategy]["why_in" if now_invested
                                            else "why_out"],
                "price": round(float(d["close"].iloc[-1]), 2),
                "date": d.index[-1].date().isoformat()},
        "strategy_key": strategy,
        "strategy_label": STRATEGIES[strategy]["label"],
        "strategy_desc": STRATEGIES[strategy]["desc"],
        "years": round(years, 1),
        "curves": d[["strat_curve", "hold_curve"]],
        "strategy": {
            "total_return": round((d["strat_curve"].iloc[-1] - 1) * 100, 1),
            "cagr": round(cagr(d["strat_curve"]), 2),
            "max_dd": round(max_dd(d["strat_curve"]), 1),
        },
        "buy_hold": {
            "total_return": round((d["hold_curve"].iloc[-1] - 1) * 100, 1),
            "cagr": round(cagr(d["hold_curve"]), 2),
            "max_dd": round(max_dd(d["hold_curve"]), 1),
        },
        "n_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 0) if trades else None,
        "n_cost_events": n_sides,
        "trades": pd.DataFrame(trades),
        "beat_hold": cagr(d["strat_curve"]) > cagr(d["hold_curve"]),
    }


def summary_text(res):
    s, h = res["strategy"], res["buy_hold"]
    name = res.get("strategy_label", "the strategy")
    if res["beat_hold"]:
        return (f"Over {res['years']} years, {name} beat buy-and-hold "
                f"({s['cagr']}% vs {h['cagr']}% CAGR) on this stock — rare, "
                "and often driven by dodging one big crash. Before trusting "
                "it: does the same rule win on your OTHER stocks, or only "
                "this one? An edge that appears once is usually luck.")
    return (f"Over {res['years']} years, buy-and-hold won ({h['cagr']}% vs "
            f"{s['cagr']}% CAGR, after paying costs on "
            f"{res['n_cost_events']} buys and sells). "
            "This is the usual outcome — and knowing it is worth more than "
            "any signal. Note the drawdowns: the rule's worst fall "
            f"({s['max_dd']}%) vs holding ({h['max_dd']}%) is the real "
            "trade-off being priced.")


@memo.memoize("backtest_all")
def compare_all(symbol, cost_per_side_pct=0.20):
    """Run every strategy on one symbol — the scoreboard view."""
    rows = []
    for key, meta in STRATEGIES.items():
        r = run(symbol, cost_per_side_pct, key)
        if not r:
            continue
        rows.append({
            "key": key, "label": meta["label"],
            "cagr": float(r["strategy"]["cagr"]),
            "max_dd": float(r["strategy"]["max_dd"]),
            "trades": int(r["n_trades"]),
            "win_rate": float(r["win_rate"]) if r["win_rate"] is not None
            else None,
            "beat_hold": bool(r["beat_hold"]),
            "now": r["now"],
            "hold_cagr": float(r["buy_hold"]["cagr"]),
            "hold_dd": float(r["buy_hold"]["max_dd"]),
        })
    return rows
