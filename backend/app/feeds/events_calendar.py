"""Results and events calendar, built from data the app already has.

  results    next earnings date stored with each stock's fundamentals
  dividend   ex-dates / split dates from research.events(), cached here
             because that call goes to Yahoo once per stock
  ipo        open, close and listing dates from the ipos table
"""
import datetime as dt
import json
import threading

from app.core import database as db
from app.feeds import ipos

STATE = {"running": False, "log": [], "done": False}
_lock = threading.Lock()


def ensure_tables():
    with db.get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS events_cache (
            symbol TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched TEXT NOT NULL)""")


def refresh_events(progress=lambda m: None, max_age_days=3):
    """Cache dividends / splits for every watchlist stock."""
    from app.analysis import research
    ensure_tables()
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=max_age_days)).isoformat()
    with db.get_conn() as conn:
        fresh = {r[0] for r in conn.execute(
            "SELECT symbol FROM events_cache WHERE fetched > ?", (cutoff,))}
    n = 0
    for (_i, atype, symbol, _s, _l, _a) in db.get_watchlist():
        if atype == "mf" or not symbol or symbol in fresh:
            continue
        try:
            payload = research.events(symbol)
            with db.get_conn() as conn:
                conn.execute("INSERT OR REPLACE INTO events_cache VALUES (?,?,?)",
                             (symbol, json.dumps(payload, default=str),
                              dt.datetime.utcnow().isoformat()))
            n += 1
        except Exception as e:
            progress(f"[calendar] {symbol}: {e}")
    progress(f"[calendar] events updated for {n} stocks")
    return n


def refresh_in_background():
    with _lock:
        if STATE["running"]:
            return False
        STATE.update(running=True, done=False, log=[])

    def work():
        try:
            refresh_events(progress=lambda m: STATE["log"].append(str(m)))
        except Exception as e:
            STATE["log"].append(f"[calendar] failed: {e}")
        STATE.update(running=False, done=True)
    threading.Thread(target=work, daemon=True).start()
    return True


def events(start=None, days=35, username=None):
    ensure_tables()
    start = dt.date.fromisoformat(start) if start else dt.date.today()
    end = start + dt.timedelta(days=days)
    lo, hi = start.isoformat(), end.isoformat()
    held = {h[1] for h in db.get_holdings(username)}
    watch = {w[2]: (w[4] or w[2].split(".")[0]) for w in db.get_watchlist() if w[2]}
    out = []

    def add(date, kind, title, symbol=None, detail=""):
        d = str(date)[:10]
        if lo <= d <= hi:
            out.append({"date": d, "kind": kind, "title": title, "symbol": symbol,
                        "detail": detail, "held": symbol in held if symbol else False})

    for sym, f in db.all_fundamentals().items():
        ne = (f or {}).get("nextEarnings")
        if ne and sym in watch:
            add(ne, "results", watch[sym], sym, "Quarterly results")
    with db.get_conn() as conn:
        cached = conn.execute("SELECT symbol, payload FROM events_cache").fetchall()
    for sym, payload in cached:
        if sym not in watch:
            continue
        try:
            p = json.loads(payload)
        except ValueError:
            continue
        for d in p.get("dividends") or []:
            add(d.get("date"), "dividend", watch[sym], sym,
                f"Dividend of {d.get('amount')} per share")
        for s in p.get("splits") or []:
            add(s.get("date"), "split", watch[sym], sym,
                f"Split or bonus, {s.get('ratio')}:1")
    for i in ipos.all_rows():
        label = "New fund offer" if i["kind"] == "nfo" else "IPO"
        if i.get("open_date"):
            add(i["open_date"], "ipo", i["name"], None, f"{label} opens")
        if i.get("close_date"):
            add(i["close_date"], "ipo", i["name"], None, f"{label} closes")
        if i.get("listing_date"):
            add(i["listing_date"], "ipo", i["name"], None, "Lists on the exchange")
    out.sort(key=lambda e: (e["date"], e["kind"]))
    return {"start": lo, "end": hi, "events": out}
