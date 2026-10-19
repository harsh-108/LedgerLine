"""One synthesized verdict per stock.

Combines the four opinions the app already produces — checklist,
composite z-score rank, trend state, and active base-rate signals —
into a single card with the strongest evidence on BOTH sides.

Tiers strong / mixed / weak are shown as BUY / HOLD / SELL
(analysis.ACTION). The evidence for and against stays on the card, so a
call can always be checked against its reasons.
"""
import logging
import time

import pandas as pd

from app.core import database as db
from app.core import memo
from app.analysis import analysis, base_rates

_log = logging.getLogger(__name__)

def _ranked_symbols():
    """Watchlist symbols in composite-score order (best first), NaN scores
    dropped. ml.rank_watchlist is memoised per user until the data changes
    (app.core.memo), so composing many verdicts ranks the list once."""
    from app.analysis import ml
    ranks, _weights = ml.rank_watchlist()
    return ([] if ranks.empty else
            ranks.dropna(subset=["Score"])["Symbol"].tolist())


def _trend_state(symbol):
    rows = db.load_closes(symbol)
    if len(rows) < 210:
        return None
    close = pd.Series([r[1] for r in rows], dtype=float)
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    last = close.iloc[-1]
    return {"above_200": last > sma200, "golden": sma50 > sma200,
            "last": round(float(last), 2)}


@memo.memoize("verdict", per_user=True)
def compose(symbol, record=True):
    """Build the card. Unless record=False, the tier is also written to
    the prediction ledger (ledger.py) so it can be graded later."""
    score, pros, cons = 0, [], []

    try:                                            # 1. checklist
        ck = analysis.checklist(symbol)
        if ck:
            pts = {"strong": 2, "mixed": 0, "weak": -2}.get(ck["tier"], 0)
            score += pts
            (pros if pts >= 0 else cons).append(
                {"text": f'Checklist says {analysis.ACTION[ck["tier"]]} '
                         f'({ck["passed"]}/{ck["applicable"]} passed)',
                 "source": "Checklist"})
            for p in ck.get("pros", [])[:1]:
                pros.append({"text": p, "source": "Checklist"})
            for c in ck.get("cons", [])[:1]:
                cons.append({"text": c, "source": "Checklist"})
    except Exception as e:
        _log.warning("verdict %s: checklist failed: %r", symbol, e)

    try:                                            # 2. composite rank
        order = _ranked_symbols()
        if symbol in order:
            rank, n = order.index(symbol) + 1, len(order)
            if n >= 5:                     # quintiles of 1-4 stocks mean nothing
                if rank <= n * 0.2:
                    score += 1
                    pros.append({"text": f"Composite score ranks "
                                 f"{rank}/{n} on the watchlist",
                                 "source": "Screener"})
                elif rank >= n * 0.8:
                    score -= 1
                    cons.append({"text": f"Composite score ranks "
                                 f"{rank}/{n} — bottom quintile",
                                 "source": "Screener"})
    except Exception as e:
        _log.warning("verdict %s: composite rank failed: %r", symbol, e)

    try:                                            # 3. trend
        tr = _trend_state(symbol)
        if tr:
            if tr["above_200"] and tr["golden"]:
                score += 1
                pros.append({"text": "Uptrend: price above 200-DMA with "
                             "golden cross intact", "source": "Technical"})
            elif not tr["above_200"]:
                score -= 1
                cons.append({"text": "Price below its 200-DMA — "
                             "fighting the tape", "source": "Technical"})
    except Exception as e:
        _log.warning("verdict %s: trend failed: %r", symbol, e)

    try:                                            # 4. active signals
        from app.analysis import charts
        br = base_rates.base_rates(charts.load_stock_df(symbol)) or {}
        for s in br.get("signals", []):
            if s["signal"] in br.get("active", []):
                med3 = (s["horizons"].get("3m") or {}).get("median")
                if med3 is not None:
                    good = med3 > 0
                    score += 1 if good else -1
                    ({True: pros, False: cons}[good]).append(
                        {"text": f'{s["label"]} active — historical '
                                 f'3M median {med3:+.1f}% '
                                 f'({s["occurrences"]}x)',
                         "source": "Base rates"})
    except Exception as e:
        _log.warning("verdict %s: base rates failed: %r", symbol, e)

    tier = ("strong" if score >= 3 else
            "weak" if score <= -2 else "mixed")
    if record:
        try:
            from app.analysis import ledger
            ledger.record(symbol, "verdict", tier, score,
                          {"for": [p["text"] for p in pros[:3]],
                           "against": [c["text"] for c in cons[:3]]})
        except Exception:
            pass
    return {
        "symbol": symbol, "tier": tier, "action": analysis.ACTION[tier],
        "score": score, "for": pros[:3], "against": cons[:3],
        "note": "The call combines the app's own checks on stored, "
                "possibly delayed data; the evidence on both sides is "
                "why. Not investment advice: you make the trade.",
    }
