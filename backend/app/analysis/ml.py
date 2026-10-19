"""
AI/ML layer — built to be honest, not impressive.

Two parts:

1. predict(symbol): a gradient-boosted classifier predicting next-day
   direction from technical features. Evaluated chronologically (train on
   the past, test on the most recent 30% — never shuffled), and ALWAYS
   reported next to the naive baseline. Expect 50-55% accuracy: that is
   what genuine next-day prediction looks like. Anything much higher
   means leakage, not genius.

2. rank_watchlist(): a transparent factor score — momentum + value +
   quality + trend — computed as z-scores across your watchlist. No
   black box: every input and weight is visible. This is closer to how
   real quant funds rank stocks than any next-day predictor.

Requires: scikit-learn  (pip install scikit-learn)
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance

from app.analysis import charts
from app.core import database as db
from app.core import memo
from app.analysis import query_engine as qe

FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d",
    "rsi", "dist_sma50", "dist_sma200",
    "vol_20d", "volume_ratio",
]
FEATURE_LABELS = {
    "ret_1d": "1-day return", "ret_3d": "3-day return",
    "ret_5d": "5-day return", "ret_10d": "10-day return",
    "rsi": "RSI (14)", "dist_sma50": "Distance from SMA-50",
    "dist_sma200": "Distance from SMA-200",
    "vol_20d": "20-day volatility", "volume_ratio": "Volume vs 20-day avg",
}


# The model needs ~300 feature rows AFTER the 200-day SMA warm-up
# consumes the first ~200 — so roughly 460 stored trading days (~2 years).
MIN_ROWS = 460


def eligible_stocks():
    """(eligible, excluded) watchlist stock rows, by stored history depth."""
    counts = db.price_counts()
    eligible, excluded = [], []
    for r in db.get_watchlist("stock"):
        (eligible if counts.get(r[2], 0) >= MIN_ROWS else excluded).append(r)
    return eligible, excluded


# ------------------------------------------------------------------ features
def build_features(symbol):
    """Feature matrix + next-day-up target from stored OHLCV."""
    df = charts.load_stock_df(symbol)
    if df is None or len(df) < 300:
        return None
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    f["ret_1d"] = c.pct_change(1)
    f["ret_3d"] = c.pct_change(3)
    f["ret_5d"] = c.pct_change(5)
    f["ret_10d"] = c.pct_change(10)
    f["rsi"] = df["rsi"]
    f["dist_sma50"] = c / df["sma_fast"] - 1
    f["dist_sma200"] = c / df["sma_slow"] - 1
    f["vol_20d"] = f["ret_1d"].rolling(20).std()
    vol_avg = df["volume"].rolling(20).mean()
    f["volume_ratio"] = (df["volume"] / vol_avg).replace([np.inf, -np.inf], np.nan)
    # target: is TOMORROW's close above today's? (shift -1 => no lookahead
    # in features; the last row has no target and becomes the live query row)
    f["target"] = (c.shift(-1) > c).astype(int)
    return f


# ---------------------------------------------------------------- prediction
@memo.memoize("predict")
def predict(symbol, test_frac=0.3, seed=42):
    """Train chronologically, evaluate on the untouched recent segment,
    then predict tomorrow. Returns dict or None (not enough data)."""
    f = build_features(symbol)
    if f is None:
        return None
    live_row = f[FEATURES].iloc[[-1]]
    data = f.iloc[:-1].dropna()
    if len(data) < 250:
        return None

    split = int(len(data) * (1 - test_frac))
    X_train, y_train = data[FEATURES].iloc[:split], data["target"].iloc[:split]
    X_test, y_test = data[FEATURES].iloc[split:], data["target"].iloc[split:]

    model = HistGradientBoostingClassifier(
        max_depth=3, max_iter=150, learning_rate=0.05, random_state=seed
    )
    model.fit(X_train, y_train)

    test_acc = float((model.predict(X_test) == y_test).mean())
    baseline = float(max(y_test.mean(), 1 - y_test.mean()))  # majority class
    prob_up = float(model.predict_proba(live_row)[0][1])

    imp = permutation_importance(
        model, X_test, y_test, n_repeats=5, random_state=seed
    )
    importances = sorted(
        zip(FEATURES, imp.importances_mean), key=lambda x: -x[1]
    )

    return {
        "symbol": symbol,
        "prob_up": prob_up,
        "test_accuracy": test_acc,
        "baseline_accuracy": baseline,
        "edge": test_acc - baseline,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "test_period": f"{X_test.index[0].date()} → {X_test.index[-1].date()}",
        "importances": [
            (FEATURE_LABELS[k], round(float(v), 4)) for k, v in importances
        ],
    }


def verdict(result):
    """Plain-language honesty about whether the model is worth listening to."""
    edge = result["edge"]
    if edge <= 0.005:
        return ("no_edge",
                "On unseen data this model did NOT beat simply guessing the "
                "majority class. Its probability below is noise — ignore it.")
    if edge <= 0.03:
        return ("weak",
                "A marginal edge over the naive baseline — typical for honest "
                "next-day prediction. Treat the probability as a whisper, "
                "not a signal.")
    return ("caution",
            "An edge this large on daily data is unusual — before trusting "
            "it, suspect data quirks or an unusually trending test period.")


# ------------------------------------------------------------------ rankings
FACTOR_WEIGHTS = {"momentum": 0.30, "value": 0.25, "quality": 0.25, "trend": 0.20}


@memo.memoize("rank", per_user=True)
def rank_watchlist():
    """Composite factor score per stock. Fully transparent:
    momentum = 6M return | value = earnings yield (1/PE) |
    quality = ROE | trend = above/below 200-day SMA (via trend flag).
    Each is z-scored across the watchlist, then weighted."""
    m = qe.build_metrics()
    if m.empty:
        return pd.DataFrame(), FACTOR_WEIGHTS

    df = m[["name", "sector", "close", "pe", "roe", "ret6m", "trend",
            "rsi"]].copy()

    def z(series):
        s = pd.to_numeric(series, errors="coerce")
        if s.std(skipna=True) in (0, None) or s.notna().sum() < 3:
            return pd.Series(np.nan, index=s.index)
        return ((s - s.mean(skipna=True)) / s.std(skipna=True)).clip(-3, 3)

    df["momentum_z"] = z(df["ret6m"])
    with np.errstate(divide="ignore"):
        earnings_yield = 1 / pd.to_numeric(df["pe"], errors="coerce")
    df["value_z"] = z(earnings_yield.replace([np.inf, -np.inf], np.nan))
    df["quality_z"] = z(df["roe"])
    df["trend_z"] = df["trend"].map({"up": 1.0, "down": -1.0})

    parts = {
        "momentum": df["momentum_z"], "value": df["value_z"],
        "quality": df["quality_z"], "trend": df["trend_z"],
    }
    weighted, weight_sum = 0.0, 0.0
    score = pd.Series(0.0, index=df.index)
    wsum = pd.Series(0.0, index=df.index)
    for name, series in parts.items():
        w = FACTOR_WEIGHTS[name]
        valid = series.notna()
        score[valid] += series[valid] * w
        wsum[valid] += w
    df["score"] = (score / wsum.replace(0, np.nan)).round(2)

    out = df.rename(columns={
        "name": "Symbol", "sector": "Sector", "close": "Close",
        "pe": "P/E", "roe": "ROE %", "ret6m": "6M %", "trend": "Trend",
        "rsi": "RSI", "momentum_z": "Momentum z", "value_z": "Value z",
        "quality_z": "Quality z", "trend_z": "Trend z", "score": "Score",
    })
    for col in ["P/E", "ROE %", "6M %", "RSI", "Momentum z", "Value z",
                "Quality z"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)
    out = out.sort_values("Score", ascending=False, na_position="last")
    return out.reset_index(drop=True), FACTOR_WEIGHTS
