"""SQLite storage: prices, NAVs, journal, and the editable watchlist."""

import functools
import json
import sqlite3
from contextlib import contextmanager

from app.core import config


# ---------------------------------------------------------- request scope
# Set by the auth middleware for the duration of one HTTP request. Helpers
# for per-user tables default to it, so route code needs no plumbing and
# cannot forget to filter. Background threads start with an empty context
# and therefore see every user's rows (what data jobs need).
import contextvars as _cv
current_user = _cv.ContextVar("current_user", default=None)


def scope_user(explicit=None, all_users=False):
    """Resolve the owner to filter by: an explicit username wins; else the
    request's user; None means unscoped (jobs, admin tooling)."""
    if explicit:
        return explicit
    if all_users:
        return None
    return current_user.get()


# One connection per thread, reused. Opening the 100+ MB file and closing
# it again on every query was the app's main cost: closing the last WAL
# connection checkpoints the log, so a page that ran 15 queries paid for
# 15 open/checkpoint/close cycles (tens of ms each on phone storage).
# Server threads (anyio's pool, the schedulers) are long-lived, so each
# keeps its connection. Nested get_conn() blocks share the outer one's
# transaction; only the outermost block commits or rolls back.
import threading as _threading
_local = _threading.local()


def _open():
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")   # safe under WAL, far fewer fsyncs
    return conn


# ----------------------------------------------------------- data version
# Bumped by every function below that writes data the analyses read
# (prices, NAVs, fundamentals, watchlists, holdings, sells, dividends,
# SIPs, fund holdings, delivery, shareholding, statements). app.core.memo
# keys its cache on it, so a cached checklist / verdict / chart is reused
# until the data actually changes and recomputed right after.
_version = [0]


def data_version():
    return _version[0]


def data_changed():
    _version[0] += 1


def _changes_data(fn):
    """Mark a writer: bump the data version once it has run."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            data_changed()
    return wrapper


def close_conn():
    """Close this thread's reused connection, e.g. before a script moves
    or deletes the database file (Windows refuses while it is open)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


@contextmanager
def get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != config.DB_PATH:
        if conn is not None:                     # DB_PATH changed (tests)
            conn.close()
        conn = _local.conn = _open()
        _local.path = config.DB_PATH
        _local.depth = 0
    _local.depth += 1
    try:
        yield conn
        if _local.depth == 1:
            conn.commit()
    except BaseException:
        if _local.depth == 1:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        _local.depth -= 1


def _heals_user_columns(fn):
    """Self-healing wrapper for per-user portfolio queries.

    If the username migration hasn't reached the DB file this connection
    opened (server started before the file was swapped in, or init_db ran
    against a different file), the first per-user query raises
    OperationalError('no such column: username'). Instead of 500-ing,
    apply the migration on the spot and retry once."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "username" not in str(e):
                raise
            ensure_portfolio_user_columns()
            return fn(*args, **kwargs)
    return wrapper


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol      TEXT NOT NULL,
            date        TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume      INTEGER,
            asset_type  TEXT NOT NULL,
            PRIMARY KEY (symbol, date)
        );

        CREATE TABLE IF NOT EXISTS nav (
            scheme_code INTEGER NOT NULL,
            date        TEXT NOT NULL,
            nav         REAL NOT NULL,
            PRIMARY KEY (scheme_code, date)
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type  TEXT NOT NULL,            -- 'stock' | 'etf' | 'mf'
            symbol      TEXT,                     -- for stocks/ETFs
            scheme_code INTEGER,                  -- for MFs
            label       TEXT,
            added_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(asset_type, symbol, scheme_code)
        );

        CREATE TABLE IF NOT EXISTS delivery (
            symbol      TEXT NOT NULL,     -- base symbol, no suffix
            date        TEXT NOT NULL,
            delivery_pct REAL,
            PRIMARY KEY (symbol, date)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            kind        TEXT NOT NULL,     -- price_above|price_below|day_move
            value       REAL NOT NULL,
            active      INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sips (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_code INTEGER NOT NULL,
            amount      REAL NOT NULL,
            day_of_month INTEGER NOT NULL,
            start_date  TEXT NOT NULL      -- YYYY-MM-DD
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            qty         REAL NOT NULL,
            buy_price   REAL NOT NULL,
            buy_date    TEXT,
            added_at    TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol      TEXT PRIMARY KEY,
            data        TEXT,                     -- JSON blob
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            symbol      TEXT,
            signal      TEXT,
            price       REAL,
            action      TEXT DEFAULT 'NONE',
            reason      TEXT
        );
        """)
    # migration: tag column on watchlist (older DBs lack it)
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(watchlist)").fetchall()]
        if "tag" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN tag TEXT")
    # dividends received, entered manually per symbol. Symbol-level (not
    # per lot) — a dividend lands on however many shares you held on the
    # record date, which the lot rows can't know. Counted into P&L totals.
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS dividends (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol  TEXT NOT NULL,
            amount  REAL NOT NULL,
            date    TEXT,
            note    TEXT
        )""")
    # cached financial statements (research.py) and realized sells
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS statements (
            symbol  TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shareholding (
            symbol   TEXT NOT NULL,
            quarter  TEXT NOT NULL,
            promoter REAL, pledged REAL, fii REAL, dii REAL,
            PRIMARY KEY (symbol, quarter)
        );
        CREATE TABLE IF NOT EXISTS sells (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT NOT NULL,
            qty        REAL NOT NULL,
            buy_price  REAL NOT NULL,
            buy_date   TEXT,
            sell_price REAL NOT NULL,
            sell_date  TEXT NOT NULL
        );
        """)
    # migration: source column on prices — records which vendor a row came
    # from (yahoo = split/dividend-adjusted, smartapi = raw exchange
    # prices). A symbol's history must stay single-source: mixing the two
    # conventions creates fake price cliffs at splits/bonuses. Existing
    # rows are labelled 'yahoo' since that was the only source until now.
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(prices)").fetchall()]
        if "source" not in cols:
            conn.execute(
                "ALTER TABLE prices ADD COLUMN source TEXT DEFAULT 'yahoo'")
    # migration: per-user portfolios. holdings / sells / dividends gain a
    # username column so each account keeps its own portfolio (watchlist,
    # prices, alerts etc. stay shared). Pre-migration rows are assigned to
    # the earliest-created account, which is the original owner; if no
    # account exists yet, auth.create_user() claims them at first setup.
    ensure_portfolio_user_columns()
    # migration: manual watchlist ordering (drag-to-reorder in the UI).
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(watchlist)").fetchall()]
        if "sort_order" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN sort_order INTEGER")
    # migrations: tier history (checklist tier per symbol per day, powers
    # the "tier changes" feed) and per-stock thesis notes.
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tier_history (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            tier   TEXT NOT NULL,
            PRIMARY KEY (symbol, date)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol   TEXT NOT NULL,
            text     TEXT NOT NULL,
            created  TEXT DEFAULT (datetime('now','localtime')),
            username TEXT
        );
        """)
    seed_watchlist_if_empty()


def _ensure_column(conn, table, col, decl):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except Exception:
        pass                       # already there


def ensure_portfolio_user_columns():
    """Idempotent username migration for holdings / sells / dividends.
    Called from init_db() at startup AND lazily by _heals_user_columns
    when a query finds the column missing (e.g. the DB file was replaced
    while the server was running)."""
    with get_conn() as conn:
        for table in ("holdings", "sells", "dividends"):
            cols = [r[1] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()]
            if "username" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN username TEXT")
        has_users = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='users'").fetchone()
        if has_users:
            first = conn.execute(
                "SELECT username FROM users ORDER BY created LIMIT 1"
            ).fetchone()
            if first:
                for table in ("holdings", "sells", "dividends"):
                    conn.execute(
                        f"UPDATE {table} SET username=? "
                        "WHERE username IS NULL", (first[0],))


@_heals_user_columns
@_changes_data
def claim_orphan_owned_rows(username):
    """First account: everything created before accounts existed
    (watchlist, alerts, SIPs, Scorecard calls and tracking, manual document
    uploads) becomes theirs."""
    with get_conn() as conn:
        for table in ("watchlist", "alerts", "sips", "predictions",
                      "scorecard_track"):
            try:
                conn.execute(f"UPDATE {table} SET username=? "
                             "WHERE username IS NULL", (username,))
            except Exception:
                pass
        try:
            conn.execute("UPDATE documents SET username=? WHERE username "
                         "IS NULL AND source='manual upload'", (username,))
        except Exception:
            pass


@_changes_data
def claim_orphan_portfolio_rows(username):
    """Assign any portfolio rows without an owner to `username`. Called
    when the very first account is created, so a pre-auth portfolio ends
    up belonging to the admin rather than to nobody."""
    with get_conn() as conn:
        for table in ("holdings", "sells", "dividends"):
            conn.execute(
                f"UPDATE {table} SET username=? WHERE username IS NULL",
                (username,))


def ensure_v2_columns():
    """2026-08 additions: buy thesis on holdings, last-visit marker on
    users (powers the what-changed card)."""
    with get_conn() as conn:
        _ensure_column(conn, "holdings", "thesis", "TEXT")
        _ensure_column(conn, "users", "last_seen", "TEXT")
        # 2026-10: MAX(date) over all prices was a full scan of the
        # biggest table on every watchlist/home load. One-time build.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_date "
                     "ON prices(date)")
        # bad vendor rows saved before save_navs filtered them
        conn.execute("DELETE FROM nav WHERE nav IS NULL OR nav <= 0")


@_changes_data
def seed_watchlist_if_empty():
    """First run: copy the default watchlist from config.py into the DB.
    After that, the DB (edited via the UI) is the single source of truth."""
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if n:
            return
        for s in config.STOCKS:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (asset_type, symbol, label) VALUES ('stock',?,?)",
                (s, s.split(".")[0]),
            )
        for s in config.ETFS:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (asset_type, symbol, label) VALUES ('etf',?,?)",
                (s, s.split(".")[0]),
            )
        for mf in config.MUTUAL_FUNDS:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (asset_type, scheme_code, label) VALUES ('mf',?,?)",
                (mf["scheme_code"], mf["label"]),
            )


def stored_listing(base):
    """Which listing of a company (RELIANCE.NS / RELIANCE.BO) already has
    price rows. Prefer NSE; return None when neither has any."""
    with get_conn() as conn:
        for cand in (f"{base}.NS", f"{base}.BO"):
            n = conn.execute("SELECT COUNT(*) FROM prices WHERE symbol=?",
                             (cand,)).fetchone()[0]
            if n:
                return cand
    return None


@_changes_data
def seed_user_watchlist(username):
    """Give a new account its starter stocks (config.STARTER_STOCKS).
    Returns the symbols that have no price history yet, so the caller can
    fetch them in the background. Funds are added separately because
    they need a network lookup."""
    if not username:
        return []
    missing = []
    for pos, base in enumerate(config.STARTER_STOCKS):
        symbol = stored_listing(base) or f"{base}.NS"
        add_ticker(symbol, "stock", username=username)
        if not stored_listing(base):
            missing.append(symbol)
        with get_conn() as conn:               # keep the list in this order
            conn.execute("UPDATE watchlist SET sort_order=? WHERE symbol=? "
                         "AND username=? AND sort_order IS NULL",
                         (pos, symbol, username))
    return missing


# ---------------------------------------------------------- watchlist CRUD
def get_watchlist(asset_type=None, username=None, distinct=None,
                  all_users=False):
    """Rows (id, asset_type, symbol, scheme_code, label, added_at).
    Inside a request this is the signed-in user's list; in a background
    thread (or with all_users=True) it is EVERY user's rows, collapsed to
    one per symbol so data jobs fetch each once."""
    username = scope_user(username, all_users)
    if distinct is None:
        distinct = username is None
    q = "SELECT id, asset_type, symbol, scheme_code, label, added_at FROM watchlist"
    where, args = [], []
    if asset_type:
        where.append("asset_type=?")
        args.append(asset_type)
    if username:
        where.append("username=?")
        args.append(username)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY COALESCE(sort_order, 999999), asset_type, label"
    with get_conn() as conn:
        rows = conn.execute(q, tuple(args)).fetchall()
    if distinct and not username:
        seen, out = set(), []
        for r in rows:
            key = (r[1], r[2], r[3])
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out
    return rows


def set_watchlist_order(ids, username=None):
    """Persist a manual ordering: ids in display order (own rows only)."""
    username = scope_user(username)
    with get_conn() as conn:
        for pos, item_id in enumerate(ids):
            if username:
                conn.execute("UPDATE watchlist SET sort_order=? WHERE id=? "
                             "AND username=?", (pos, item_id, username))
            else:
                conn.execute("UPDATE watchlist SET sort_order=? WHERE id=?",
                             (pos, item_id))


@_changes_data
def add_ticker(symbol, asset_type, label=None, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        # scheme_code is NULL for tickers and SQLite treats NULLs as
        # distinct in UNIQUE, so check explicitly (per owner).
        if conn.execute("SELECT 1 FROM watchlist WHERE symbol=? AND "
                        "COALESCE(username,'')=COALESCE(?,'')",
                        (symbol.upper(), username)).fetchone():
            return
        conn.execute(
            "INSERT INTO watchlist (asset_type, symbol, label, username) "
            "VALUES (?,?,?,?)",
            (asset_type, symbol.upper(),
             label or symbol.split(".")[0].upper(), username),
        )


@_changes_data
def add_mf(scheme_code, label, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (asset_type, scheme_code, label, "
            "username) VALUES ('mf',?,?,?)",
            (int(scheme_code), label, username),
        )


@_changes_data
def remove_watchlist_item(item_id, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        if username:
            conn.execute("DELETE FROM watchlist WHERE id=? AND username=?",
                         (item_id, username))
        else:
            conn.execute("DELETE FROM watchlist WHERE id=?", (item_id,))


def watchlist_symbols(username):
    """Just the stock/ETF symbols one user tracks (for scoping shared
    feeds like the journal and news)."""
    with get_conn() as conn:
        return [r[0] for r in conn.execute(
            "SELECT symbol FROM watchlist WHERE username=? AND symbol IS NOT "
            "NULL", (username,)).fetchall()]


# --------------------------------------------------------------- data I/O
def stored_rows(symbol):
    """How many price rows exist for a symbol."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM prices WHERE symbol=?", (symbol,)
        ).fetchone()[0]


def last_stored_date(symbol):
    """Date of the newest price row for a symbol, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) FROM prices WHERE symbol=?",
                           (symbol,)).fetchone()
    return row[0] if row else None


@_changes_data
def dedupe_watchlist(username):
    """Delete repeated rows of the same stock/ETF symbol (or the same fund)
    on one user's watchlist, keeping the oldest row. Returns how many rows
    were removed."""
    with get_conn() as conn:
        n = conn.execute(
            "DELETE FROM watchlist WHERE username=? AND symbol IS NOT NULL "
            "AND id NOT IN (SELECT MIN(id) FROM watchlist WHERE username=? "
            "AND symbol IS NOT NULL GROUP BY symbol)",
            (username, username)).rowcount
        n += conn.execute(
            "DELETE FROM watchlist WHERE username=? AND symbol IS NULL "
            "AND scheme_code IS NOT NULL AND id NOT IN (SELECT MIN(id) FROM "
            "watchlist WHERE username=? AND symbol IS NULL AND scheme_code "
            "IS NOT NULL GROUP BY scheme_code)",
            (username, username)).rowcount
    return n


@_changes_data
def repoint_watchlist_symbol(old_symbol, new_symbol):
    """Swap a watchlist entry to a different listing of the same company
    (e.g. .BO -> .NS when the NSE listing has real history). No-op if the
    target symbol is already on the watchlist."""
    with get_conn() as conn:
        clash = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol=?", (new_symbol,)
        ).fetchone()
        if clash:
            return False
        conn.execute(
            "UPDATE watchlist SET symbol=?, label=? WHERE symbol=?",
            (new_symbol, new_symbol.split(".")[0], old_symbol))
        return True


@_changes_data
def save_prices(df, symbol, asset_type, source="yahoo"):
    rows = [
        (
            symbol,
            idx.strftime("%Y-%m-%d"),
            float(r["Open"]), float(r["High"]),
            float(r["Low"]), float(r["Close"]),
            int(r["Volume"]) if r["Volume"] == r["Volume"] else 0,
            asset_type,
            source,
        )
        for idx, r in df.iterrows()
        # NaN != NaN — skip rows with any missing price (SQLite stores
        # NaN as NULL, which then crashes arithmetic downstream)
        if r["Close"] == r["Close"] and r["Open"] == r["Open"]
        and r["High"] == r["High"] and r["Low"] == r["Low"]
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(symbol, date, open, high, low, close, volume, asset_type, "
            " source) VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
    return len(rows)


@_heals_user_columns
@_changes_data
def add_dividend(symbol, amount, date=None, note=None, username=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO dividends (symbol, amount, date, note, username) "
            "VALUES (?,?,?,?,?)", (symbol, amount, date, note, username))


@_heals_user_columns
def get_dividends(username=None):
    with get_conn() as conn:
        if username is None:
            return conn.execute(
                "SELECT id, symbol, amount, date, note FROM dividends "
                "ORDER BY date DESC, id DESC").fetchall()
        return conn.execute(
            "SELECT id, symbol, amount, date, note FROM dividends "
            "WHERE username=? ORDER BY date DESC, id DESC",
            (username,)).fetchall()


@_heals_user_columns
@_changes_data
def remove_dividend(div_id, username=None):
    with get_conn() as conn:
        if username is None:
            conn.execute("DELETE FROM dividends WHERE id=?", (div_id,))
        else:
            conn.execute("DELETE FROM dividends WHERE id=? AND username=?",
                         (div_id, username))


@_heals_user_columns
def dividend_total(username=None):
    with get_conn() as conn:
        if username is None:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM dividends").fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM dividends "
                "WHERE username=?", (username,)).fetchone()
    return float(row[0])


@_changes_data
def purge_prices(symbol):
    """Delete a symbol's whole price history. Used when its data source
    changes — adjusted (Yahoo) and raw (SmartAPI) rows must never mix."""
    with get_conn() as conn:
        conn.execute("DELETE FROM prices WHERE symbol=?", (symbol,))


def symbol_source(symbol):
    """Vendor of this symbol's most recent stored row, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT source FROM prices WHERE symbol=? "
            "ORDER BY date DESC LIMIT 1", (symbol,),
        ).fetchone()
    return row[0] if row else None


def source_map():
    """{symbol: source-of-latest-row} for every stored symbol.
    (SQLite's bare-column-with-MAX picks values from the max-date row.)"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, source, MAX(date) FROM prices GROUP BY symbol"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def sources_for(symbols):
    """{symbol: source-of-latest-row} for just these symbols. One indexed
    lookup each, instead of source_map()'s scan of the whole prices table."""
    out = {}
    with get_conn() as conn:
        for sym in set(symbols):
            row = conn.execute(
                "SELECT source FROM prices WHERE symbol=? "
                "ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
            if row:
                out[sym] = row[0]
    return out


@_changes_data
def save_navs(scheme_code, nav_rows):
    # mfapi.in occasionally reports a NAV of 0 (e.g. Axis ELSS on
    # 2013-04-07); one such row made rolling returns infinite and the
    # fund page fail to serialise. A NAV is never <= 0, so drop them.
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO nav VALUES (?,?,?)",
            [(scheme_code, d, v) for d, v in nav_rows if v and v > 0],
        )
    return len(nav_rows)


@_changes_data
def update_mf_label(scheme_code, official_name):
    """Store the official AMFI name alongside the user's label."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET label = ? WHERE asset_type='mf' AND scheme_code=? AND (label LIKE 'VERIFY-ME%' OR label IS NULL)",
            (official_name[:60], scheme_code),
        )


def log_signal(symbol, signal, price, reason=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO journal (symbol, signal, price, reason) VALUES (?,?,?,?)",
            (symbol, signal, price, reason),
        )


def get_journal(limit=200, symbols=None):
    """symbols=None: everything (admin/jobs); else only those symbols —
    the journal is app-generated per symbol, so a user sees the entries
    for what they track."""
    with get_conn() as conn:
        if symbols is None:
            return conn.execute(
                "SELECT created_at, symbol, signal, price, action, reason "
                "FROM journal ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        if not symbols:
            return []
        marks = ",".join("?" * len(symbols))
        return conn.execute(
            f"SELECT created_at, symbol, signal, price, action, reason "
            f"FROM journal WHERE symbol IN ({marks}) ORDER BY id DESC "
            f"LIMIT ?", (*symbols, limit)
        ).fetchall()


def load_closes(symbol):
    with get_conn() as conn:
        return conn.execute(
            "SELECT date, close FROM prices WHERE symbol=? AND close IS NOT NULL "
            "ORDER BY date", (symbol,)
        ).fetchall()


def load_navs(scheme_code):
    with get_conn() as conn:
        return conn.execute(
            "SELECT date, nav FROM nav WHERE scheme_code=? AND nav > 0 "
            "ORDER BY date",
            (scheme_code,),
        ).fetchall()


def load_ohlc(symbol):
    """Full OHLCV history for one symbol as list of tuples."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE symbol=? AND close IS NOT NULL ORDER BY date", (symbol,)
        ).fetchall()


def latest_moves(username=None, all_users=True):
    """(symbol, label, last_close, pct_change) per stock/ETF symbol in the
    watchlist, using the last two stored closes. One row per symbol even
    when several users keep it. Default is every user's list (tape,
    lookups); pass all_users=False inside a request for the signed-in
    user's list only."""
    username = scope_user(username, all_users)
    out = []
    with get_conn() as conn:
        q = ("SELECT symbol, MIN(label) FROM watchlist "
             "WHERE asset_type IN ('stock','etf') AND symbol IS NOT NULL")
        args = ()
        if username:
            q += " AND username=?"
            args = (username,)
        wl = conn.execute(q + " GROUP BY symbol", args).fetchall()
        for symbol, label in wl:
            rows = conn.execute(
                "SELECT close FROM prices WHERE symbol=? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 2", (symbol,),
            ).fetchall()
            if len(rows) == 2 and rows[0][0] and rows[1][0]:
                last, prev = rows[0][0], rows[1][0]
                out.append((symbol, label, last, (last / prev - 1) * 100))
    return out


@_changes_data
def save_fundamentals(symbol, data: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (symbol, data, updated_at) "
            "VALUES (?,?,datetime('now','localtime'))",
            (symbol, json.dumps(data)),
        )


def get_fundamentals(symbol):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM fundamentals WHERE symbol=?", (symbol,)
        ).fetchone()
    if not row:
        return None, None
    return json.loads(row[0]), row[1]


def all_fundamentals():
    """{symbol: dict} for every stored symbol. Parsing ~600 JSON blobs took
    25+ ms and ran once per checklist (so ten times for one portfolio
    view); it is kept until the data changes. The inner dicts are shared:
    callers only read them (checked 2026-10-19)."""
    from app.core import memo

    def load():
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT symbol, data FROM fundamentals").fetchall()
        return {s: json.loads(d) for s, d in rows}
    return dict(memo.cached(("all_fundamentals",), load, share=True))


def signal_logged_today(symbol, signal):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM journal WHERE symbol=? AND signal=? "
            "AND date(created_at)=date('now','localtime') LIMIT 1",
            (symbol, signal),
        ).fetchone()
    return row is not None


def price_counts():
    """{symbol: number_of_stored_rows} for all symbols in prices."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, COUNT(*) FROM prices GROUP BY symbol"
        ).fetchall()
    return dict(rows)


def recent_closes(symbol, n=30):
    """Last n closes ascending, for sparklines."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT close FROM prices WHERE symbol=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT ?", (symbol, n),
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def recent_navs(scheme_code, n=30):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT nav FROM nav WHERE scheme_code=? AND nav > 0 "
            "ORDER BY date DESC LIMIT ?",
            (scheme_code, n),
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def last_price_date():
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) FROM prices").fetchone()
    return row[0] if row and row[0] else None


def today_signal_count(symbols=None):
    """symbols=None: every signal fired today (admin/jobs); else only the
    ones on the given symbols, so a user's count matches their journal."""
    if symbols is not None and not symbols:
        return 0
    q = ("SELECT COUNT(*) FROM journal "
         "WHERE date(created_at)=date('now','localtime')")
    args = ()
    if symbols:
        q += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args = tuple(symbols)
    with get_conn() as conn:
        row = conn.execute(q, args).fetchone()
    return row[0] or 0


@_heals_user_columns
@_changes_data
def add_holding(symbol, qty, buy_price, buy_date=None, username=None,
                thesis=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO holdings (symbol, qty, buy_price, buy_date, "
            "username, thesis) VALUES (?,?,?,?,?,?)",
            (symbol.upper(), qty, buy_price, buy_date, username, thesis),
        )


@_heals_user_columns
@_changes_data
def remove_holding(holding_id, username=None):
    with get_conn() as conn:
        if username is None:
            conn.execute("DELETE FROM holdings WHERE id=?", (holding_id,))
        else:
            conn.execute("DELETE FROM holdings WHERE id=? AND username=?",
                         (holding_id, username))


@_heals_user_columns
def get_holdings(username=None):
    """Holdings rows. username=None returns ALL rows (legacy combined
    view used by the Streamlit app and CLI digests); the web API always
    passes the signed-in user so each account sees only its own."""
    with get_conn() as conn:
        if username is None:
            return conn.execute(
                "SELECT id, symbol, qty, buy_price, buy_date, thesis FROM holdings "
                "ORDER BY symbol"
            ).fetchall()
        return conn.execute(
            "SELECT id, symbol, qty, buy_price, buy_date, thesis FROM holdings "
            "WHERE username=? ORDER BY symbol", (username,)
        ).fetchall()


@_changes_data
def repoint_holding_symbol(old_symbol, new_symbol, username=None):
    """Move a symbol's holdings, sells and dividends to another listing
    (a bare ticker to LICI.NS, or a priceless .BO to its .NS sister), so
    lots of the same company merge and get valued. username=None: every
    account (a symbol with no prices is wrong for all of them)."""
    n = 0
    with get_conn() as conn:
        for table in ("holdings", "sells", "dividends"):
            q = f"UPDATE {table} SET symbol=? WHERE symbol=?"
            args = [new_symbol, old_symbol]
            if username:
                q += " AND username=?"
                args.append(username)
            n += conn.execute(q, args).rowcount
    return n


def last_close(symbol):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT close FROM prices WHERE symbol=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (symbol,),
        ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------- tags
def set_tag(item_id, tag, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        if username:
            conn.execute("UPDATE watchlist SET tag=? WHERE id=? AND username=?",
                         (tag or None, item_id, username))
        else:
            conn.execute("UPDATE watchlist SET tag=? WHERE id=?",
                         (tag or None, item_id))


def get_tag_map():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, tag FROM watchlist WHERE tag IS NOT NULL").fetchall()
    return dict(rows)


def all_tags():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT tag FROM watchlist "
            "WHERE tag IS NOT NULL ORDER BY tag").fetchall()
    return [r[0] for r in rows]


# -------------------------------------------------------------------- alerts
def add_alert(symbol, kind, value, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (symbol, kind, value, username) "
            "VALUES (?,?,?,?)", (symbol.upper(), kind, value, username),
        )


def get_alerts(active_only=True, username=None, with_owner=False,
               all_users=False):
    """Rows (id, symbol, kind, value, active[, username])."""
    username = scope_user(username, all_users)
    cols = "id, symbol, kind, value, active" + (", username" if with_owner
                                                 else "")
    q = f"SELECT {cols} FROM alerts"
    where, args = [], []
    if active_only:
        where.append("active=1")
    if username:
        where.append("username=?")
        args.append(username)
    if where:
        q += " WHERE " + " AND ".join(where)
    with get_conn() as conn:
        return conn.execute(q + " ORDER BY symbol", tuple(args)).fetchall()


def remove_alert(alert_id, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        if username:
            conn.execute("DELETE FROM alerts WHERE id=? AND username=?",
                         (alert_id, username))
        else:
            conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))


def deactivate_alert(alert_id):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET active=0 WHERE id=?", (alert_id,))


# ---------------------------------------------------------------------- SIPs
@_changes_data
def add_sip(scheme_code, amount, day_of_month, start_date, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sips (scheme_code, amount, day_of_month, start_date, "
            "username) VALUES (?,?,?,?,?)",
            (scheme_code, amount, day_of_month, start_date, username),
        )


def get_sips(username=None, all_users=False):
    username = scope_user(username, all_users)
    q = ("SELECT s.id, s.scheme_code, s.amount, s.day_of_month, "
         "s.start_date, (SELECT label FROM watchlist w WHERE "
         "w.scheme_code = s.scheme_code AND w.asset_type='mf' LIMIT 1) "
         "FROM sips s")
    args = ()
    if username:
        q += " WHERE s.username=?"
        args = (username,)
    with get_conn() as conn:
        return conn.execute(q + " ORDER BY s.id", args).fetchall()


@_changes_data
def remove_sip(sip_id, username=None):
    username = scope_user(username)
    with get_conn() as conn:
        if username:
            conn.execute("DELETE FROM sips WHERE id=? AND username=?",
                         (sip_id, username))
        else:
            conn.execute("DELETE FROM sips WHERE id=?", (sip_id,))


def last_two_closes(symbol):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT close FROM prices WHERE symbol=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 2",
            (symbol,),
        ).fetchall()
    return [r[0] for r in rows]


@_changes_data
def save_delivery(symbol_base, date_str, pct):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO delivery VALUES (?,?,?)",
                     (symbol_base.upper(), date_str, pct))


def latest_delivery(symbol_base):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date, delivery_pct FROM delivery WHERE symbol=? "
            "ORDER BY date DESC LIMIT 1", (symbol_base.upper(),)
        ).fetchone()
    return row  # (date, pct) or None

@_changes_data
def save_statements(symbol, payload):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO statements VALUES (?,?,?)",
            (symbol, payload, __import__("datetime").date.today().isoformat()))


def get_statements(symbol):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload, updated FROM statements WHERE symbol=?",
            (symbol,)).fetchone()
    return row


@_heals_user_columns
@_changes_data
def add_sell(symbol, qty, buy_price, buy_date, sell_price, sell_date,
             username=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sells (symbol, qty, buy_price, buy_date, "
            "sell_price, sell_date, username) VALUES (?,?,?,?,?,?,?)",
            (symbol, qty, buy_price, buy_date, sell_price, sell_date,
             username))


@_heals_user_columns
def get_sells(username=None):
    with get_conn() as conn:
        if username is None:
            return conn.execute(
                "SELECT id, symbol, qty, buy_price, buy_date, sell_price, "
                "sell_date FROM sells ORDER BY sell_date DESC, id DESC"
            ).fetchall()
        return conn.execute(
            "SELECT id, symbol, qty, buy_price, buy_date, sell_price, "
            "sell_date FROM sells WHERE username=? "
            "ORDER BY sell_date DESC, id DESC", (username,)
        ).fetchall()


@_heals_user_columns
def get_holding(hid, username=None):
    with get_conn() as conn:
        if username is None:
            return conn.execute(
                "SELECT id, symbol, qty, buy_price, buy_date, thesis FROM holdings "
                "WHERE id=?", (hid,)).fetchone()
        return conn.execute(
            "SELECT id, symbol, qty, buy_price, buy_date, thesis FROM holdings "
            "WHERE id=? AND username=?", (hid, username)).fetchone()


@_changes_data
def update_holding_qty(hid, qty):
    with get_conn() as conn:
        conn.execute("UPDATE holdings SET qty=? WHERE id=?", (qty, hid))


def recent_volumes(symbol, n=30):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT volume FROM prices WHERE symbol=? AND volume IS NOT NULL "
            "ORDER BY date DESC LIMIT ?", (symbol, n)).fetchall()
    return [r[0] for r in rows][::-1]


def delivery_series(symbol_base, n=90):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, delivery_pct FROM delivery WHERE symbol=? "
            "ORDER BY date DESC LIMIT ?", (symbol_base, n)).fetchall()
    return rows[::-1]


@_changes_data
def save_shareholding(symbol, quarter, promoter, pledged, fii, dii):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO shareholding VALUES (?,?,?,?,?,?)",
            (symbol, quarter, promoter, pledged, fii, dii))


def get_shareholding(symbol):
    with get_conn() as conn:
        return conn.execute(
            "SELECT quarter, promoter, pledged, fii, dii FROM shareholding "
            "WHERE symbol=? ORDER BY quarter", (symbol,)).fetchall()


@_changes_data
def delete_shareholding(symbol, quarter):
    with get_conn() as conn:
        conn.execute("DELETE FROM shareholding WHERE symbol=? AND quarter=?",
                     (symbol, quarter))


# ------------------------------------------------ tier history / notes
def record_tiers(tier_map, date=None):
    """Store today's checklist tier per symbol (idempotent per day)."""
    import datetime as _dt
    date = date or _dt.date.today().isoformat()
    with get_conn() as conn:
        for sym, tier in tier_map.items():
            if tier:
                conn.execute(
                    "INSERT OR REPLACE INTO tier_history VALUES (?,?,?)",
                    (sym, date, tier))


def tier_changes(days=21):
    """Symbols whose most recent recorded tier differs from the one
    before it, within the window. Returns [(symbol, old, new, date)]."""
    import datetime as _dt
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    out = []
    with get_conn() as conn:
        syms = [r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM tier_history WHERE date>=?",
            (since,))]
        for sym in syms:
            rows = conn.execute(
                "SELECT date, tier FROM tier_history WHERE symbol=? "
                "ORDER BY date DESC LIMIT 8", (sym,)).fetchall()
            for i in range(len(rows) - 1):
                if rows[i][1] != rows[i + 1][1]:
                    out.append((sym, rows[i + 1][1], rows[i][1], rows[i][0]))
                    break
    return out


def add_note(symbol, text, username=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO notes (symbol, text, username) VALUES (?,?,?)",
            (symbol, text, username))


def get_notes(symbol, username=None):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, text, created FROM notes WHERE symbol=? "
            "AND (username=? OR username IS NULL) ORDER BY id DESC",
            (symbol, username)).fetchall()


def remove_note(note_id, username=None):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM notes WHERE id=? AND (username=? OR username IS NULL)",
            (note_id, username))


# ---------------------------------------------------------- account removal
@_changes_data
def delete_user_rows(username):
    """Remove everything one account owns: every table with a `username`
    column loses that user's rows (watchlist, alerts, holdings, sells,
    dividends, SIPs, fund holdings, notes, manual document uploads,
    sessions, tokens, Telegram links, analyst usage), then the account
    itself. Shared rows (username NULL) are untouched. Returns
    {table: rows_deleted}."""
    if not username:
        return {}
    removed = {}
    with get_conn() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in tables:
            if table == "users":
                continue
            cols = [r[1] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()]
            if "username" not in cols:
                continue
            cur = conn.execute(f"DELETE FROM {table} WHERE username=?",
                               (username,))
            if cur.rowcount:
                removed[table] = cur.rowcount
        # the text of their uploaded documents lives in doc_chunks, which
        # has no username column: without this it outlived the account
        if "doc_chunks" in tables and "documents" in tables:
            cur = conn.execute("DELETE FROM doc_chunks WHERE doc_id NOT IN "
                               "(SELECT id FROM documents)")
            if cur.rowcount:
                removed["doc_chunks"] = cur.rowcount
        cur = conn.execute("DELETE FROM users WHERE username=?", (username,))
        removed["users"] = cur.rowcount
    return removed
