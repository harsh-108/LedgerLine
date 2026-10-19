"""SIP tracking with real XIRR from NAV history."""

from datetime import date, timedelta

import pandas as pd

from app.core import database as db


def _sip_dates(start_date, day_of_month, until):
    """Monthly dates from start to `until` on the given day (clamped)."""
    d = date.fromisoformat(str(start_date))
    out = []
    y, m = d.year, d.month
    while True:
        day = min(day_of_month, 28)  # clamp: every month has 28 days
        cur = date(y, m, day)
        if cur > until:
            break
        if cur >= d:
            out.append(cur)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _nav_on_or_after(nav_series, when):
    """First NAV on/after a date (SIPs execute on the next business day)."""
    idx = nav_series.index.searchsorted(pd.Timestamp(when))
    if idx >= len(nav_series):
        return None, None
    return nav_series.index[idx].date(), float(nav_series.iloc[idx])


def xirr(cashflows, guess=0.12):
    """cashflows: [(date, amount)] — outflows negative. Newton's method."""
    if len(cashflows) < 2:
        return None
    t0 = cashflows[0][0]
    years = [(d - t0).days / 365.25 for d, _ in cashflows]
    if max(years) == 0:
        return None          # all flows on one day: no time, no rate
    amts = [a for _, a in cashflows]

    def f(r):
        return sum(a / (1 + r) ** t for a, t in zip(amts, years))

    def fp(r):
        return sum(-t * a / (1 + r) ** (t + 1)
                   for a, t in zip(amts, years) if t > 0)

    r = guess
    for _ in range(80):
        fv, fpv = f(r), fp(r)
        if abs(fpv) < 1e-12:
            break
        step = fv / fpv
        r -= step
        if r <= -0.99:
            r = -0.9
        if abs(step) < 1e-8:
            return r
    return r if abs(f(r)) < 1.0 else None


def evaluate(scheme_code, amount, day_of_month, start_date):
    """Simulate the SIP against actual NAV history. Returns dict or None."""
    navs = db.load_navs(scheme_code)
    if len(navs) < 30:
        return None
    nav = pd.Series([r[1] for r in navs],
                    index=pd.to_datetime([r[0] for r in navs])).sort_index()
    today = nav.index[-1].date()
    dates = _sip_dates(start_date, day_of_month, today)
    if not dates:
        return None

    units, flows, executed = 0.0, [], 0
    for d in dates:
        exec_date, px = _nav_on_or_after(nav, d)
        if px is None:
            continue
        units += amount / px
        flows.append((exec_date, -amount))
        executed += 1
    if not flows:
        return None
    current_value = units * float(nav.iloc[-1])
    flows.append((today, current_value))
    invested = executed * amount
    rate = xirr(sorted(flows))
    return {
        "installments": executed,
        "invested": round(invested, 2),
        "units": round(units, 3),
        "current_value": round(current_value, 2),
        "abs_return_pct": round((current_value / invested - 1) * 100, 2),
        "xirr_pct": round(rate * 100, 2) if rate is not None else None,
    }
