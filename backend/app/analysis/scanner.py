"""
Indicators (SMA 50/200, RSI-14) + daily signal scan over the DB watchlist.

CLI usage:  python scanner.py
Also imported by the Streamlit UI (scan_all returns a DataFrame).
"""

import pandas as pd

from app.core import config
from app.core import database as db


def compute_indicators(closes: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"close": closes})
    df["sma_fast"] = df["close"].rolling(config.SMA_FAST).mean()
    df["sma_slow"] = df["close"].rolling(config.SMA_SLOW).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss))
    return df


def _detect_signals(df):
    today, prev = df.iloc[-1], df.iloc[-2]
    signals = []
    if prev["sma_fast"] <= prev["sma_slow"] and today["sma_fast"] > today["sma_slow"]:
        signals.append("GOLDEN_CROSS")
    if prev["sma_fast"] >= prev["sma_slow"] and today["sma_fast"] < today["sma_slow"]:
        signals.append("DEATH_CROSS")
    if prev["rsi"] >= config.RSI_OVERSOLD and today["rsi"] < config.RSI_OVERSOLD:
        signals.append("RSI_OVERSOLD")
    if prev["rsi"] <= config.RSI_OVERBOUGHT and today["rsi"] > config.RSI_OVERBOUGHT:
        signals.append("RSI_OVERBOUGHT")
    return signals, today




# --------------------------------------------------------- automatic events
# Thresholds for notable one-day moves. India's price bands are typically
# 2/5/10/20% depending on the stock, and exact bands per stock are not in
# free data — so >=9.5% is labelled "possible circuit", which is a heuristic,
# not an exchange confirmation.
BIG_MOVE_PCT = 5.0
CIRCUIT_PCT = 9.5


def detect_events(name, closes: pd.Series):
    """Return list of (event, detail) for notable happenings on the last bar."""
    if len(closes) < 2:
        return []
    events = []
    last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
    if prev:
        pct = (last / prev - 1) * 100
        if pct >= CIRCUIT_PCT:
            events.append(("POSSIBLE_UPPER_CIRCUIT", f"+{pct:.1f}% in a day"))
        elif pct >= BIG_MOVE_PCT:
            events.append(("BIG_GAIN", f"+{pct:.1f}% in a day"))
        elif pct <= -CIRCUIT_PCT:
            events.append(("POSSIBLE_LOWER_CIRCUIT", f"{pct:.1f}% in a day"))
        elif pct <= -BIG_MOVE_PCT:
            events.append(("BIG_DROP", f"{pct:.1f}% in a day"))
    if len(closes) >= 252:
        yr = closes.tail(252)
        if last >= float(yr.max()):
            events.append(("NEW_52W_HIGH", f"at {last:,.2f}"))
        elif last <= float(yr.min()):
            events.append(("NEW_52W_LOW", f"at {last:,.2f}"))
    return events


def _log_once(name, event, price, detail):
    """Journal an event, skipping duplicates for the same day."""
    if not db.signal_logged_today(name, event):
        db.log_signal(name, event, price, detail)
        return True
    return False


def scan_all(log_to_journal=True):
    """Scan every stock/ETF in the watchlist. Returns a DataFrame."""
    db.init_db()
    out = []
    for (_id, asset_type, symbol, scheme_code, label, _a) in db.get_watchlist():
        if asset_type == "mf":
            navs = db.load_navs(scheme_code)
            if len(navs) < config.SMA_SLOW + 5:
                continue
            series = pd.Series(
                [r[1] for r in navs], index=pd.to_datetime([r[0] for r in navs])
            )
            name = label
        else:
            rows = db.load_closes(symbol)
            if len(rows) < config.SMA_SLOW + 5:
                continue
            series = pd.Series(
                [r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows])
            )
            name = symbol

        df = compute_indicators(series)
        signals, today = _detect_signals(df)
        out.append({
            "name": name,
            "type": asset_type,
            "close": round(float(today["close"]), 2),
            "rsi": round(float(today["rsi"]), 1),
            "trend": "UP" if today["sma_fast"] > today["sma_slow"] else "DOWN",
            "signals": ", ".join(signals) if signals else "",
        })
        events = detect_events(name, series)
        if log_to_journal:
            for s in signals:
                if not db.signal_logged_today(name, s):
                    db.log_signal(name, s, float(today["close"]))
            for ev, detail in events:
                _log_once(name, ev, float(today["close"]), detail)
        if events:
            existing = out[-1]["signals"]
            ev_txt = ", ".join(e for e, _ in events)
            out[-1]["signals"] = f"{existing}, {ev_txt}" if existing else ev_txt
    return pd.DataFrame(out)


if __name__ == "__main__":
    result = scan_all()
    if result.empty:
        print("No data yet — run: python downloader.py")
    else:
        print(result.to_string(index=False))
        fired = result[result["signals"] != ""]
        if not fired.empty:
            print(f"\n{len(fired)} signal(s) fired — logged to journal.")
            print("A signal is a prompt to LOOK, not an order to trade.")
