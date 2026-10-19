"""
Prediction ledger — the app grades its own calls.

Every time the app shows an opinion about a stock, a row is written here
with the price on that day. Later, once enough trading days have passed,
the row is resolved against the actual close (and NIFTYBEES over the same
window) and marked right / wrong. Nothing is ever edited or deleted by
the app, so the scorecard can't be flattered after the fact.

What counts as a "call" (kind -> what it said -> when it is graded):

  verdict      strong / mixed / weak      1 month and 3 months
               (the synthesis card in the stock drawer)
  checklist    strong / mixed / weak      1 month and 3 months
               (the research-checklist tier, e.g. "5/7 passed")
  ml_nextday   up / down                  the next trading day
               (the AI Lab next-day model, prob_up >= 0.5 -> up)
  rule_<key>   in / out                   the tracking period the user
               (a backtest rule's state   picked (default 90 days)
               today, e.g. rule_golden_cross: "in" = the rule holds the
               stock, "out" = the rule would be in cash)

Grading rules, deliberately simple so anyone can check them:
  strong / up / in  -> right if the stock's return over the horizon is > 0
  weak / down / out -> right if the return is < 0
  mixed        -> no directional claim -> tracked, not scored ("no_call")
  beat_index   -> additionally, did the call beat NIFTYBEES the same way
                  (strong: return > index return; weak: return < index)

A snapshot is idempotent per (user, symbol, kind, date, horizon): opening
the same stock ten times in a day writes one row, not ten.

Per user: every call and every tracked stock belongs to one account (the
`username` column), so each person's Scorecard holds only what they looked
at and chose to track. Grading is shared: it is one pass over all rows,
since the outcome of a call depends only on prices.
"""

import datetime as _dt
import json

from app.core import database as db

BENCHMARK = "NIFTYBEES.NS"
HORIZONS = {"verdict": (30, 90), "checklist": (30, 90), "ml_nextday": (1,)}
CALL_DIR = {"strong": 1, "up": 1, "in": 1, "weak": -1, "down": -1,
            "out": -1, "mixed": 0}
RULE_PREFIX = "rule_"          # rule_<backtest strategy key>
DEFAULT_RULE_HORIZON = 90


def _known_kind(kind):
    return kind in HORIZONS or kind.startswith(RULE_PREFIX)


_PRED_SQL = """
        CREATE TABLE IF NOT EXISTS predictions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT,               -- owner of the call
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            date         TEXT NOT NULL,      -- price date the call is on
            symbol       TEXT NOT NULL,
            kind         TEXT NOT NULL,      -- verdict|checklist|ml_nextday
            call         TEXT NOT NULL,      -- strong|mixed|weak|up|down
            score        REAL,               -- verdict score / prob_up / passed
            detail       TEXT,               -- JSON: the reasons shown
            price_at     REAL NOT NULL,
            horizon_days INTEGER NOT NULL,
            date_after   TEXT,
            price_after  REAL,
            ret_pct      REAL,
            bm_ret_pct   REAL,
            outcome      TEXT,               -- right|wrong|no_call|NULL
            beat_index   INTEGER,            -- 1|0|NULL
            resolved_at  TEXT,
            UNIQUE(username, symbol, kind, date, horizon_days)
        );"""
_TRACK_SQL = """
        CREATE TABLE IF NOT EXISTS scorecard_track (
            username TEXT,                      -- who is tracking it
            symbol   TEXT NOT NULL,
            source   TEXT,           -- manual|watchlist|portfolio|backtest|...
            added_at TEXT DEFAULT (datetime('now','localtime')),
            days     INTEGER,        -- tracking period; NULL = until stopped
            until    TEXT,           -- last day the daily snapshot covers it
            UNIQUE(username, symbol)
        );"""
_PRED_COLS = "id, created_at, date, symbol, kind, call, score, detail, price_at, horizon_days, date_after, price_after, ret_pct, bm_ret_pct, outcome, beat_index, resolved_at"


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _first_user(conn):
    """The earliest account: the install's original owner, who inherits
    calls recorded before the Scorecard was per user. None if no account
    exists yet (auth claims the rows at first setup then)."""
    try:
        row = conn.execute("SELECT username FROM users ORDER BY created "
                           "LIMIT 1").fetchone()
    except Exception:
        return None
    return row[0] if row else None


def _migrate_per_user(conn):
    """One-off: rebuild both tables with an owner column (SQLite cannot
    change a UNIQUE constraint in place). Existing rows go to the first
    account."""
    pc = _cols(conn, "predictions")
    if pc and "username" not in pc:
        owner = _first_user(conn)
        conn.execute("DROP INDEX IF EXISTS idx_pred_pending")
        conn.execute("ALTER TABLE predictions RENAME TO predictions_old")
        conn.execute(_PRED_SQL)
        conn.execute(f"INSERT INTO predictions (username, {_PRED_COLS}) "
                     f"SELECT ?, {_PRED_COLS} FROM predictions_old", (owner,))
        conn.execute("DROP TABLE predictions_old")
    tc = _cols(conn, "scorecard_track")
    if tc and "username" not in tc:
        owner = _first_user(conn)
        keep = [c for c in ("symbol", "source", "added_at", "days", "until")
                if c in tc]
        conn.execute("ALTER TABLE scorecard_track RENAME TO track_old")
        conn.execute(_TRACK_SQL)
        conn.execute(f"INSERT INTO scorecard_track (username, "
                     f"{', '.join(keep)}) SELECT ?, {', '.join(keep)} "
                     "FROM track_old", (owner,))
        conn.execute("DROP TABLE track_old")


def ensure_table():
    with db.get_conn() as conn:
        _migrate_per_user(conn)
        conn.execute(_PRED_SQL)
        conn.execute(_TRACK_SQL)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_pending "
                     "ON predictions(outcome) WHERE outcome IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_user "
                     "ON predictions(username, symbol)")


# -------------------------------------------------------------- tracking
def _today():
    return _dt.date.today()


def tracked(username=None):
    """The signed-in user's tracked stocks (or `username`'s)."""
    ensure_table()
    u = db.scope_user(username)
    today = _today()
    out = []
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, source, added_at, days, until FROM "
            "scorecard_track WHERE username IS ? ORDER BY symbol",
            (u,)).fetchall()
        counts = dict(conn.execute(
            "SELECT symbol, COUNT(*) FROM predictions WHERE username IS ? "
            "GROUP BY symbol", (u,)))
    for (s, src, a, days, until) in rows:
        left = ((_dt.date.fromisoformat(until) - today).days
                if until else None)
        out.append({"symbol": s, "source": src, "added_at": a,
                    "days": days, "until": until,
                    "active": until is None or left >= 0,
                    "days_left": None if left is None else max(left, 0),
                    "calls": counts.get(s, 0)})
    return out


def tracked_symbols(active_only=False, username=None):
    return [t["symbol"] for t in tracked(username)
            if t["active"] or not active_only]


def active_trackers():
    """{symbol: [usernames]} for every tracking period still running, across
    all accounts. Background jobs use it to record each user's calls."""
    ensure_table()
    today = _today().isoformat()
    out = {}
    with db.get_conn() as conn:
        for sym, u in conn.execute(
                "SELECT symbol, username FROM scorecard_track WHERE username "
                "IS NOT NULL AND (until IS NULL OR until >= ?) "
                "ORDER BY symbol, username", (today,)):
            out.setdefault(sym, []).append(u)
    return out


def _until(start, days):
    return (None if not days
            else (start + _dt.timedelta(days=int(days))).isoformat())


def track_add(symbols, source="manual", days=None, username=None):
    """Start tracking, or extend it. `days` = how long the daily snapshot
    keeps covering the stock (None/0 = until the user stops it). Adding a
    stock that is already tracked never shortens its period: the later
    end date wins, and "until stopped" beats any end date."""
    ensure_table()
    u = db.scope_user(username)
    today = _today()
    new_until = _until(today, days)
    added = extended = 0
    with db.get_conn() as conn:
        for sym in symbols:
            sym = (sym or "").strip().upper()
            if not sym:
                continue
            row = conn.execute(
                "SELECT added_at, until FROM scorecard_track WHERE "
                "username IS ? AND symbol=?", (u, sym)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO scorecard_track (username, symbol, source, "
                    "days, until) VALUES (?,?,?,?,?)",
                    (u, sym, source, int(days) if days else None, new_until))
                added += 1
                continue
            added_at, until = row
            if until is None:
                continue                          # already open-ended
            best = None if new_until is None else max(until, new_until)
            if best == until:
                continue
            start = _dt.date.fromisoformat(added_at[:10])
            span = (None if best is None else
                    (_dt.date.fromisoformat(best) - start).days)
            conn.execute("UPDATE scorecard_track SET days=?, until=? "
                         "WHERE username IS ? AND symbol=?",
                         (span, best, u, sym))
            extended += 1
    return {"added": added, "extended": extended}


def track_set_days(symbol, days, username=None):
    """Set the tracking period explicitly, counted from the day the stock
    was added (None/0 = until stopped). A period that has already run out
    simply ends the daily snapshots; recorded calls are kept."""
    ensure_table()
    u = db.scope_user(username)
    with db.get_conn() as conn:
        row = conn.execute("SELECT added_at FROM scorecard_track WHERE "
                           "username IS ? AND symbol=?",
                           (u, symbol.upper())).fetchone()
        if not row:
            return False
        start = _dt.date.fromisoformat(row[0][:10])
        conn.execute("UPDATE scorecard_track SET days=?, until=? WHERE "
                     "username IS ? AND symbol=?",
                     (int(days) if days else None, _until(start, days), u,
                      symbol.upper()))
    return True


def track_remove(symbol, username=None):
    ensure_table()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM scorecard_track WHERE username IS ? AND "
                     "symbol=?", (db.scope_user(username), symbol.upper()))


def _last_close(symbol):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT date, close FROM prices WHERE symbol=? AND close IS NOT "
            "NULL ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
    return row if row else (None, None)


_recorded = set()      # (user, date, symbol, kind, horizons) written already


def record(symbol, kind, call, score=None, detail=None, horizons=None,
           username=None):
    """Write one row per horizon for this call, keyed on the latest stored
    price date (not the wall clock — a call made on Sunday is graded from
    Friday's close, which is the price the user actually saw). `horizons`
    overrides the kind's fixed horizons (backtest rules use the tracking
    period the user picked). The row belongs to `username`, or to the
    signed-in user; a call with no owner (a background job that did not say
    whose it is) is not recorded."""
    u = db.scope_user(username)
    if not u or not _known_kind(kind) or call not in CALL_DIR:
        return 0
    horizons = horizons or HORIZONS.get(kind) or (DEFAULT_RULE_HORIZON,)
    date, px = _last_close(symbol)
    if not date or not px:
        return 0
    # Every stock / portfolio view records its calls. The INSERT OR IGNORE
    # below keeps only the first per day anyway, so a repeat in this process
    # skips the database write (a commit and a disk sync on the phone).
    seen_key = (u, date, symbol, kind, tuple(horizons))
    if seen_key in _recorded:
        return 0
    ensure_table()
    detail_json = json.dumps(detail)[:2000] if detail is not None else None
    n = 0
    with db.get_conn() as conn:
        for h in horizons:
            cur = conn.execute(
                "INSERT OR IGNORE INTO predictions (username, date, symbol, "
                "kind, call, score, detail, price_at, horizon_days) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (u, date, symbol, kind, call, score, detail_json, px, h))
            n += cur.rowcount
    if len(_recorded) > 20000:            # one day of a full universe
        _recorded.clear()
    _recorded.add(seen_key)
    return n


# --------------------------------------------------------------- grading
def _close_on_or_after(closes, when):
    """closes: sorted [(date, close)]. First close with date >= when."""
    for d, c in closes:
        if d >= when and c:
            return d, c
    return None, None


def _close_after(closes, when):
    for d, c in closes:
        if d > when and c:
            return d, c
    return None, None


def resolve_pending():
    """Grade every row whose horizon has passed. Safe to call often."""
    ensure_table()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, date, symbol, kind, call, price_at, horizon_days "
            "FROM predictions WHERE outcome IS NULL").fetchall()
    if not rows:
        return 0
    closes_cache, bm = {}, db.load_closes(BENCHMARK)
    today = _dt.date.today().isoformat()
    done = 0
    for (pid, date, symbol, kind, call, px, h) in rows:
        if symbol not in closes_cache:
            closes_cache[symbol] = db.load_closes(symbol)
        closes = closes_cache[symbol]
        if h == 1:
            d_after, p_after = _close_after(closes, date)
        else:
            target = (_dt.date.fromisoformat(date)
                      + _dt.timedelta(days=h)).isoformat()
            if target > today:
                continue
            d_after, p_after = _close_on_or_after(closes, target)
        if not p_after:
            continue                              # data not there yet
        ret = (p_after / px - 1) * 100
        bm_ret = None
        b0 = _close_on_or_after(bm, date)[1]
        b1 = _close_on_or_after(bm, d_after)[1]
        if b0 and b1:
            bm_ret = (b1 / b0 - 1) * 100
        direction = CALL_DIR.get(call, 0)
        if direction == 0:
            outcome, beat = "no_call", None
        else:
            outcome = "right" if ret * direction > 0 else "wrong"
            beat = (None if bm_ret is None
                    else int((ret - bm_ret) * direction > 0))
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE predictions SET date_after=?, price_after=?, "
                "ret_pct=?, bm_ret_pct=?, outcome=?, beat_index=?, "
                "resolved_at=datetime('now','localtime') WHERE id=?",
                (d_after, round(p_after, 2), round(ret, 2),
                 round(bm_ret, 2) if bm_ret is not None else None,
                 outcome, beat, pid))
        done += 1
    return done


# ------------------------------------------------------------- reporting
def summary(symbols=None, username=None):
    """Accuracy per (kind, horizon) plus per-call breakdown, for one user's
    calls. `symbols` restricts to a whitelist (the tracked list)."""
    ensure_table()
    q = ("SELECT kind, horizon_days, call, outcome, ret_pct, beat_index "
         "FROM predictions WHERE username IS ?")
    args = (db.scope_user(username),)
    if symbols:
        q += " AND symbol IN (%s)" % ",".join("?" * len(symbols))
        args += tuple(symbols)
    with db.get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    groups = {}
    for kind, h, call, outcome, ret, beat in rows:
        g = groups.setdefault((kind, h), {
            "kind": kind, "horizon_days": h, "total": 0, "pending": 0,
            "right": 0, "wrong": 0, "no_call": 0, "beat_index": 0,
            "beat_index_n": 0, "ret_sum": 0.0, "ret_n": 0, "by_call": {}})
        g["total"] += 1
        if outcome is None:
            g["pending"] += 1
            continue
        g[outcome] = g.get(outcome, 0) + 1
        bc = g["by_call"].setdefault(call, {"right": 0, "wrong": 0,
                                            "no_call": 0, "ret_sum": 0.0,
                                            "n": 0})
        bc[outcome] += 1
        if ret is not None:
            g["ret_sum"] += ret
            g["ret_n"] += 1
            bc["ret_sum"] += ret
            bc["n"] += 1
        if beat is not None:
            g["beat_index_n"] += 1
            g["beat_index"] += beat
    out = []
    for g in groups.values():
        scored = g["right"] + g["wrong"]
        g["accuracy"] = round(g["right"] / scored * 100, 1) if scored else None
        g["scored"] = scored
        g["avg_ret"] = (round(g["ret_sum"] / g["ret_n"], 2)
                        if g["ret_n"] else None)
        g["beat_index_pct"] = (round(g["beat_index"] / g["beat_index_n"]
                                     * 100, 1) if g["beat_index_n"] else None)
        for bc in g["by_call"].values():
            s = bc["right"] + bc["wrong"]
            bc["accuracy"] = round(bc["right"] / s * 100, 1) if s else None
            bc["avg_ret"] = round(bc["ret_sum"] / bc["n"], 2) if bc["n"] else None
            bc.pop("ret_sum")
        g.pop("ret_sum"); g.pop("ret_n"); g.pop("beat_index")
        g.pop("beat_index_n")
        out.append(g)
    order = {"verdict": 0, "checklist": 1, "ml_nextday": 2}
    out.sort(key=lambda g: (order.get(g["kind"], 9), g["kind"],
                            g["horizon_days"]))
    return out


def rows(symbol=None, kind=None, status=None, limit=300, symbols=None,
         username=None):
    ensure_table()
    q, args = "SELECT id, date, symbol, kind, call, score, price_at, " \
              "horizon_days, date_after, price_after, ret_pct, bm_ret_pct, " \
              "outcome, beat_index, detail FROM predictions " \
              "WHERE username IS ?", [db.scope_user(username)]
    if symbol:
        q += " AND symbol=?"; args.append(symbol)
    if symbols:
        q += " AND symbol IN (%s)" % ",".join("?" * len(symbols))
        args.extend(symbols)
    if kind == "rule":
        q += " AND kind LIKE ?"; args.append(RULE_PREFIX + "%")
    elif kind:
        q += " AND kind=?"; args.append(kind)
    if status == "pending":
        q += " AND outcome IS NULL"
    elif status == "resolved":
        q += " AND outcome IS NOT NULL"
    q += " ORDER BY date DESC, id DESC LIMIT ?"; args.append(limit)
    with db.get_conn() as conn:
        rs = conn.execute(q, args).fetchall()
    keys = ["id", "date", "symbol", "kind", "call", "score", "price_at",
            "horizon_days", "date_after", "price_after", "ret_pct",
            "bm_ret_pct", "outcome", "beat_index", "detail"]
    out = []
    for r in rs:
        d = dict(zip(keys, r))
        try:
            d["detail"] = json.loads(d["detail"]) if d["detail"] else None
        except Exception:
            pass
        out.append(d)
    return out


def track_record(symbol, username=None):
    """Tiny per-stock line for the drawer: this user's resolved verdict
    calls."""
    ensure_table()
    with db.get_conn() as conn:
        rs = conn.execute(
            "SELECT horizon_days, outcome FROM predictions WHERE symbol=? "
            "AND username IS ? AND kind='verdict' AND outcome IN "
            "('right','wrong')", (symbol, db.scope_user(username))).fetchall()
    out = {}
    for h, o in rs:
        g = out.setdefault(h, {"right": 0, "wrong": 0})
        g[o] += 1
    return out


def _count():
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]


def snapshot_all(progress=lambda m: None, users=None):
    """Record today's verdict + checklist for every stock whose tracking
    period is running, once for each user tracking it, so the ledger fills
    up daily even for stocks nobody opens. `users` limits it to those
    accounts (the "Snapshot all now" button passes just the caller). Each
    stock is analysed once, however many people track it."""
    from app.analysis import analysis, verdict as verdict_mod
    trackers = active_trackers()
    if users is not None:
        trackers = {s: [u for u in us if u in users]
                    for s, us in trackers.items()}
        trackers = {s: us for s, us in trackers.items() if us}
    if not trackers:
        progress("Nothing to snapshot: no stock is being tracked right now. "
                 "Add stocks under \"Stocks being tracked\" below.")
        return 0
    n = 0
    owners = {u for us in trackers.values() for u in us}
    text = lambda xs: [x["text"] if isinstance(x, dict) else x for x in xs]
    for sym, us in trackers.items():
        try:
            v = verdict_mod.compose(sym, record=False)
            for u in us:
                n += record(sym, "verdict", v["tier"], v["score"],
                            {"for": text(v["for"]),
                             "against": text(v["against"])}, username=u)
        except Exception as e:
            progress(f"[ledger] verdict {sym}: {e}")
        try:
            ck = analysis.checklist(sym)
            if ck:
                for u in us:
                    n += record(sym, "checklist", ck["tier"], ck["passed"],
                                {"passed": ck["passed"],
                                 "applicable": ck["applicable"]},
                                username=u)
        except Exception as e:
            progress(f"[ledger] checklist {sym}: {e}")
    progress(f"Done: {n} new call{'' if n == 1 else 's'} recorded for "
             f"{len(trackers)} stock{'' if len(trackers) == 1 else 's'}"
             + (f" across {len(owners)} accounts" if len(owners) > 1 else "")
             + (" (calls already recorded today are not repeated)"
                if n == 0 else ""))
    return n
