"""
Extras — the "More" tab: features that are useful but depend on fragile
or manual data sources, quarantined here so their failures never touch
the core app.

  shareholding — MANUAL quarterly entry (promoter / pledged / FII / DII
      %). No free API serves this reliably; four numbers per stock per
      quarter typed from Screener.in or the exchange filing is cheap and
      then the trend + warnings are automatic. Reliable by construction.

  option_sentiment — PCR and max pain from NSE's option chain via
      nsepython. NSE's endpoints are cookie-guarded and break routinely;
      every failure mode returns a clear message instead of stale or
      fake numbers. Sentiment context only — a weak signal wearing a
      precise-looking number.
"""

from app.core import database as db


# ------------------------------------------------------------ shareholding
def shareholding_report(symbol):
    rows = db.get_shareholding(symbol)
    if not rows:
        return None
    series = [{"quarter": q, "promoter": p, "pledged": pl,
               "fii": f, "dii": d}
              for (q, p, pl, f, d) in rows]
    notes = []
    if len(series) >= 2:
        a, b = series[-2], series[-1]

        def delta(key):
            if a.get(key) is None or b.get(key) is None:
                return None
            return round(b[key] - a[key], 2)

        dp = delta("promoter")
        if dp is not None and dp <= -2:
            notes.append(f"⚠ Promoter stake fell {abs(dp)} pp last quarter "
                         "— worth reading the filing for why.")
        dpl = delta("pledged")
        if dpl is not None and dpl > 0:
            notes.append(f"⚠ Pledged shares rose {dpl} pp — pledging that "
                         "grows is a classic stress marker.")
        if b.get("pledged") and b["pledged"] >= 20:
            notes.append(f"⚠ {b['pledged']}% of promoter holding is "
                         "pledged — high by any standard.")
        df = delta("fii")
        if df is not None and abs(df) >= 2:
            notes.append(f"FII stake {'rose' if df > 0 else 'fell'} "
                         f"{abs(df)} pp last quarter.")
    return {"series": series, "notes": notes}


# --------------------------------------------------------- option sentiment
_NSE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def option_sentiment(symbol):
    """PCR + max pain for the nearest expiry. Raises RuntimeError with a
    human-readable reason on any failure — the caller shows it as-is.

    NSE retired /api/option-chain-equities (it now answers {}), which is
    what nsepython's scrapper calls. The replacement is option-chain-v3,
    which needs an explicit expiry from option-chain-contract-info."""
    from app.data_sources import nse_source
    base = symbol.split(".")[0].upper()
    kind = "Indices" if base in _NSE_INDICES else "Equity"
    try:
        info = nse_source._api("option-chain-contract-info", {"symbol": base})
        expiries = (info or {}).get("expiryDates") or []
        data = (nse_source._api("option-chain-v3",
                                {"type": kind, "symbol": base,
                                 "expiry": expiries[0]})
                if expiries else None)
    except Exception as e:
        raise RuntimeError(
            "NSE refused the option-chain request (their endpoints are "
            f"cookie-guarded and moody): {e.__class__.__name__}. "
            "Try again in a minute; if it persists all day, NSE changed "
            "something and this feature is down until updated.")
    if not expiries:
        raise RuntimeError(f"No options are listed for {base} on NSE — only "
                           "F&O stocks and indices have an option chain.")
    try:
        records = data["records"]
        expiry = expiries[0]
        underlying = records["underlyingValue"]
        # v3 rows carry "expiryDates" (one value) and are already filtered
        # to the requested expiry; older payloads used "expiryDate"
        rows = [r for r in records["data"]
                if r.get("expiryDate", r.get("expiryDates", expiry)) == expiry]
        if not rows:
            raise KeyError("no rows for nearest expiry")
        put_oi = sum((r.get("PE") or {}).get("openInterest", 0) for r in rows)
        call_oi = sum((r.get("CE") or {}).get("openInterest", 0)
                      for r in rows)
        pcr = round(put_oi / call_oi, 2) if call_oi else None

        # max pain: strike where total option-writer payout is smallest
        strikes = sorted({r["strikePrice"] for r in rows})
        ce_oi = {r["strikePrice"]: (r.get("CE") or {}).get("openInterest", 0)
                 for r in rows}
        pe_oi = {r["strikePrice"]: (r.get("PE") or {}).get("openInterest", 0)
                 for r in rows}
        best, best_pain = None, None
        for s in strikes:
            pain = sum(max(0, s - k) * ce_oi.get(k, 0) for k in strikes) \
                + sum(max(0, k - s) * pe_oi.get(k, 0) for k in strikes)
            if best_pain is None or pain < best_pain:
                best, best_pain = s, pain
        return {
            "symbol": base, "expiry": expiry, "underlying": underlying,
            "pcr": pcr, "max_pain": best,
            "put_oi": int(put_oi), "call_oi": int(call_oi),
            "read": (
                f"PCR {pcr} — "
                + ("put-heavy; crowd positioned for/hedged against downside"
                   if pcr and pcr > 1.2 else
                   "call-heavy; crowd leaning bullish"
                   if pcr and pcr < 0.7 else "roughly balanced")
                + f". Max pain {best} vs spot {underlying} — expiries often "
                  "drift toward max pain, but 'often' is doing heavy "
                  "lifting in that sentence."
            ) if pcr else "Insufficient open interest to read.",
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"NSE's response format changed "
                           f"({e.__class__.__name__}: {e}) — feature needs "
                           "a code update.")
