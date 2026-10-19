"""
Weekly Telegram digest — run once a week (Sunday evening works well).

    python digest.py            # send to Telegram (or print if not configured)
    python digest.py --print    # always just print, never send

What it reports:
  - portfolio: current value, week's change, total P&L (incl. dividends)
  - vs benchmark: where the same money in NIFTYBEES would stand
  - signals journaled in the last 7 days (deduped by the scanner already)
  - stocks currently within 1% of their 52-week high or low

Scheduling on Windows (Task Scheduler):
  Program:   python
  Arguments: digest.py
  Start in:  <project folder>
  Trigger:   Weekly, Sunday 18:00
Linux/macOS cron:
  0 18 * * 0  cd /path/to/project && python digest.py

Depends only on data already in market_data.db — run downloader.py +
scanner.py on your normal schedule and this just summarizes the week.
"""

import datetime as dt
import sys

from app.core import database as db
from app.alerts import notify
from app.portfolio import portfolio


def _fmt(n):
    return f"{n:,.0f}"


def build_digest(username=None):
    """username=None builds the combined/legacy digest; with a username,
    portfolio, journal and watchlist are that user's own."""
    lines = [f"📒 Weekly digest — {dt.date.today().strftime('%d %b %Y')}"]
    token = db.current_user.set(username) if username else None
    try:
        return _build(lines, username)
    finally:
        if token is not None:
            db.current_user.reset(token)


def _build(lines, username):
    # ---- portfolio ----
    val, totals = portfolio.valuation(username)
    if val.empty:
        lines.append("\nPortfolio: no holdings recorded.")
    else:
        hist = portfolio.value_history(username=username)
        week_txt = ""
        bench_txt = ""
        if hist is not None and len(hist) > 5:
            now, ago = hist["value"].iloc[-1], hist["value"].iloc[-6]
            # money added this week is not a gain
            wk = (now - ago) - (hist["invested"].iloc[-1]
                                - hist["invested"].iloc[-6])
            wk_pct = wk / ago * 100 if ago else 0
            week_txt = (f"\nThis week: {'▲' if wk >= 0 else '▼'} "
                        f"₹{_fmt(abs(wk))} ({wk_pct:+.2f}%)")
            if "benchmark" in hist.columns:
                bm = hist["benchmark"].iloc[-1]
                gap = hist["value"].iloc[-1] - bm
                bench_txt = (
                    f"\nSame money in NIFTYBEES: ₹{_fmt(bm)} — you are "
                    f"{'ahead' if gap >= 0 else 'behind'} by ₹{_fmt(abs(gap))}")
        sign = "+" if totals["pnl_incl_div"] >= 0 else ""
        lines.append(
            f"\n💼 Portfolio: ₹{_fmt(totals['current'])} "
            f"(invested ₹{_fmt(totals['invested'])})"
            f"{week_txt}"
            f"\nTotal P&L incl. dividends: {sign}₹{_fmt(totals['pnl_incl_div'])} "
            f"({totals['pnl_incl_div_pct']:+.2f}%)"
            f"{bench_txt}")

    # ---- signals of the week ----
    cutoff = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    week = [(c, s, sig, p) for (c, s, sig, p, _a, _r) in db.get_journal(
        400, symbols=(db.watchlist_symbols(username) if username else None))
            if c and c >= cutoff]
    if week:
        lines.append(f"\n🔔 Signals this week ({len(week)}):")
        for created, sym, sig, price in week[:15]:
            px = f" @ {price:,.2f}" if price else ""
            lines.append(f"  • {sym.split('.')[0]}: {sig}{px}")
        if len(week) > 15:
            lines.append(f"  … and {len(week) - 15} more in the Journal tab")
    else:
        lines.append("\n🔔 No signals journaled this week.")

    # ---- 52-week extremes right now ----
    highs, lows = [], []
    for (_i, atype, symbol, _s, label, _a) in db.get_watchlist():
        if atype == "mf" or not symbol:
            continue
        closes = [c[1] for c in db.load_closes(symbol)][-252:]
        if len(closes) < 252 or not closes[-1]:
            continue
        last, hi, lo = closes[-1], max(closes), min(closes)
        if last >= hi * 0.99:
            highs.append(symbol.split(".")[0])
        elif last <= lo * 1.01:
            lows.append(symbol.split(".")[0])
    if highs:
        lines.append(f"\n📈 Near 52-week HIGH: {', '.join(highs)}")
    if lows:
        lines.append(f"📉 Near 52-week LOW: {', '.join(lows)}")

    lines.append("\nBuy / hold / sell calls come from the app's own checks on "
                 "stored data. Not investment advice.")
    return "\n".join(lines)


TELEGRAM_MAX = 4000      # Telegram caps a message at 4096 chars


def _ensure_log():
    with db.get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS digest_sends (
            sent_at TEXT PRIMARY KEY, ok INTEGER, error TEXT)""")


def last_sent():
    """ISO timestamp of the last successful send, or None."""
    _ensure_log()
    with db.get_conn() as conn:
        row = conn.execute("SELECT MAX(sent_at) FROM digest_sends "
                           "WHERE ok = 1").fetchone()
    return row[0] if row and row[0] else None


def _split(text):
    """Split on line boundaries so no part exceeds Telegram's limit."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TELEGRAM_MAX and cur:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts


def _deliver(text, chat_id=None):
    ok, err = True, None
    for part in _split(text):
        ok, err = notify.send(part, chat_id=chat_id)
        if not ok:
            break
    return ok, err


def send_digest(username=None):
    """Send the digest. With a username: that user's digest to their
    linked Telegram chat. Without: one per linked user, plus the legacy
    TELEGRAM_CHAT_ID (the admin's) when nobody has linked yet. Returns
    {'ok','error','text','sent_at','recipients'}. Never raises."""
    from app.core import accounts
    _ensure_log()
    if not notify.bot_configured():
        return {"ok": False, "text": build_digest(username), "sent_at": None,
                "recipients": 0,
                "error": "Telegram not configured — set TELEGRAM_BOT_TOKEN "
                         "in .env and restart."}
    targets = []
    if username:
        link = accounts.telegram_chat_for(username)
        if link:
            targets.append((username, link["chat_id"]))
        elif accounts.is_admin(username) and notify.configured():
            targets.append((username, None))          # legacy env chat id
    else:
        targets = [(u, c) for (u, c) in accounts.telegram_linked_users()]
        if not targets and notify.configured():
            targets = [(None, None)]                  # single-user install
    if not targets:
        return {"ok": False, "text": build_digest(username), "sent_at": None,
                "recipients": 0,
                "error": "No Telegram linked — connect it from Settings."}
    ok_all, errs, last_text = True, [], ""
    for user, chat in targets:
        last_text = build_digest(user)
        ok, err = _deliver(last_text, chat_id=chat)
        if not ok:
            ok_all = False
            errs.append(f"{user or 'default'}: {err}")
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with db.get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO digest_sends VALUES (?,?,?)",
                     (stamp, 1 if ok_all else 0, "; ".join(errs) or None))
    return {"ok": ok_all, "error": "; ".join(errs) or None,
            "text": last_text, "sent_at": stamp if ok_all else None,
            "recipients": len(targets)}


if __name__ == "__main__":
    db.init_db()
    if "--print" in sys.argv or not notify.configured():
        print(build_digest())
        if not notify.configured():
            print("\n(Telegram not configured — printed instead.)")
    else:
        res = send_digest()
        print("sent" if res["ok"]
              else f"send failed: {res['error']}\n\n{res['text']}")
