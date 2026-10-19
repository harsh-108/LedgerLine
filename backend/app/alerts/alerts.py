"""Price alerts: checked after every scan; fire once, notify, deactivate."""

import pandas as pd

from app.core import database as db
from app.alerts import notify
from app.analysis.scanner import compute_indicators

ALERT_KINDS = {
    "price_above": "Price closes at or above ₹VALUE",
    "price_below": "Price closes at or below ₹VALUE",
    "day_move": "Day's move exceeds ±VALUE%",
    "rsi_above": "RSI-14 reaches VALUE or higher",
    "rsi_below": "RSI-14 falls to VALUE or lower",
    "high_52w": "New 52-week high (value ignored)",
    "low_52w": "New 52-week low (value ignored)",
    "vol_spike": "Volume ≥ VALUE× its 20-day average",
}


def _rsi(symbol):
    closes = db.load_closes(symbol)
    if len(closes) < 30:
        return None
    s = pd.Series([c[1] for c in closes])
    return float(compute_indicators(s)["rsi"].iloc[-1])


def check_all():
    """Evaluate active alerts against latest stored prices.
    Returns list of fired-alert messages."""
    fired = []
    for aid, symbol, kind, value, _active, owner in db.get_alerts(
            active_only=True, with_owner=True, all_users=True):
        closes = db.last_two_closes(symbol)
        if not closes:
            continue
        last = closes[0]
        prev = closes[1] if len(closes) > 1 else None
        hit, detail = False, ""
        if kind == "price_above" and last >= value:
            hit, detail = True, f"closed at {last:,.2f}, above {value:,.2f}"
        elif kind == "price_below" and last <= value:
            hit, detail = True, f"closed at {last:,.2f}, below {value:,.2f}"
        elif kind == "day_move" and prev:
            pct = (last / prev - 1) * 100
            if abs(pct) >= value:
                hit, detail = True, f"moved {pct:+.1f}% in a day (≥{value}%)"
        elif kind in ("rsi_above", "rsi_below"):
            rsi = _rsi(symbol)
            if rsi is not None:
                if kind == "rsi_above" and rsi >= value:
                    hit, detail = True, f"RSI {rsi:.0f}, above {value:.0f}"
                elif kind == "rsi_below" and rsi <= value:
                    hit, detail = True, f"RSI {rsi:.0f}, below {value:.0f}"
        elif kind in ("high_52w", "low_52w"):
            closes_yr = [c[1] for c in db.load_closes(symbol)][-252:]
            if len(closes_yr) >= 200:
                if kind == "high_52w" and last >= max(closes_yr):
                    hit, detail = True, f"new 52-week high at {last:,.2f}"
                elif kind == "low_52w" and last <= min(closes_yr):
                    hit, detail = True, f"new 52-week low at {last:,.2f}"
        elif kind == "vol_spike":
            vols = db.recent_volumes(symbol, 21)
            if len(vols) >= 21 and vols[-1]:
                avg = sum(vols[:-1]) / len(vols[:-1])
                mult = vols[-1] / avg if avg else 0
                if mult >= value:
                    hit, detail = True, (f"volume {mult:.1f}× its 20-day "
                                         f"average (≥{value}×)")
        if hit:
            msg = f"🔔 ALERT {symbol}: {detail}"
            db.log_signal(symbol, "PRICE_ALERT", last, detail)
            db.deactivate_alert(aid)   # one-shot: re-add to re-arm
            ok, _err = (notify.send_to_user(owner, msg) if owner
                        else (notify.send(msg) if notify.configured()
                              else (False, None)))
            fired.append(msg + ("  (sent to Telegram)" if ok else ""))
    return fired
