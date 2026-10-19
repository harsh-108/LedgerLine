"""
Accounts beyond "username + password on a LAN": roles, email
verification, password reset, invite codes, Google sign-in identities,
Telegram links and the per-user analyst quota.

Everything here is additive to auth.py (which keeps hashing and sessions)
and idempotent: ensure_schema() can run on every startup.

Security notes:
  - Verify/reset tokens are random 32 bytes; only their SHA-256 is stored,
    so a database read does not yield usable links. Single use, expiring.
  - Invite codes are random, single-use by default, tied to the admin who
    made them.
  - Rate limits are in-memory sliding windows keyed by IP and by account
    name. Good enough for one process; move to the DB or Redis when there
    is more than one.
  - The first account ever created is the admin. Everything that existed
    before multi-user (watchlist, alerts, documents, SIPs) is assigned to
    that account by the migration so nothing disappears.
"""
import datetime as dt
import hashlib
import os
import re
import secrets
import threading
import time

from app.core import config
from app.core import database as db

ROLE_ADMIN = "admin"
ROLE_USER = "user"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,29}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VERIFY_TTL_H = 24
RESET_TTL_H = 1
TG_CODE_TTL_MIN = 30
ANALYST_DAILY_FREE = 15          # questions/day for role=user (admin: none)

# tables that become per-user, and the column they need
OWNED_TABLES = ("watchlist", "alerts", "sips", "documents")


# ------------------------------------------------------------- schema
def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _has_table(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name=?", (table,)).fetchone() is not None


def ensure_schema():
    """Add account columns/tables and migrate shared rows to the admin."""
    with db.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            pw_hash  BLOB NOT NULL,
            salt     BLOB NOT NULL,
            created  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token_hash TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            kind       TEXT NOT NULL,          -- verify | reset
            expires    TEXT NOT NULL,
            used       INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS invite_codes (
            code       TEXT PRIMARY KEY,
            created_by TEXT,
            created_at TEXT,
            max_uses   INTEGER DEFAULT 1,
            uses       INTEGER DEFAULT 0,
            note       TEXT
        );
        CREATE TABLE IF NOT EXISTS invite_redemptions (
            code TEXT, username TEXT, redeemed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS telegram_links (
            username    TEXT PRIMARY KEY,
            chat_id     TEXT NOT NULL,
            tg_username TEXT,
            linked_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS telegram_link_codes (
            code       TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS analyst_usage (
            username TEXT, day TEXT, count INTEGER DEFAULT 0,
            PRIMARY KEY (username, day)
        );
        """)
        for col, decl in (("email", "TEXT"), ("email_verified", "INTEGER DEFAULT 0"),
                          ("google_sub", "TEXT"), ("role", "TEXT"),
                          ("display_name", "TEXT"),
                          ("starter_seeded", "INTEGER DEFAULT 0")):
            if col not in _cols(conn, "users"):
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        # legacy accounts predate email; treat them as verified
        conn.execute("UPDATE users SET email_verified=1 "
                     "WHERE email IS NULL AND email_verified=0")
        # exactly one admin if none yet: the earliest account
        if not conn.execute("SELECT 1 FROM users WHERE role=?",
                            (ROLE_ADMIN,)).fetchone():
            first = conn.execute("SELECT username FROM users "
                                 "ORDER BY created LIMIT 1").fetchone()
            if first:
                conn.execute("UPDATE users SET role=? WHERE username=?",
                             (ROLE_ADMIN, first[0]))
        conn.execute("UPDATE users SET role=? WHERE role IS NULL",
                     (ROLE_USER,))
        admin = conn.execute("SELECT username FROM users WHERE role=? "
                             "ORDER BY created LIMIT 1",
                             (ROLE_ADMIN,)).fetchone()
        admin = admin[0] if admin else None

        # owner column on formerly-shared tables, backfilled to the admin
        for table in OWNED_TABLES:
            if not _has_table(conn, table):
                continue
            if "username" not in _cols(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN username TEXT")
            if admin and table != "documents":
                conn.execute(f"UPDATE {table} SET username=? "
                             "WHERE username IS NULL", (admin,))
            elif admin:
                # only manual uploads become private; exchange-fetched
                # filings stay shared (username NULL = visible to all)
                conn.execute("UPDATE documents SET username=? WHERE "
                             "username IS NULL AND source='manual upload'",
                             (admin,))
        # watchlist uniqueness must include the owner
        _rebuild_watchlist_unique(conn)


def _rebuild_watchlist_unique(conn):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                       "AND name='watchlist'").fetchone()
    if not sql or "username, asset_type" in sql[0]:
        return
    cols = _cols(conn, "watchlist")
    keep = [c for c in ("id", "asset_type", "symbol", "scheme_code", "label",
                        "added_at", "tag", "sort_order", "username")
            if c in cols]
    conn.executescript(f"""
    CREATE TABLE watchlist_new (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_type  TEXT NOT NULL,
        symbol      TEXT,
        scheme_code INTEGER,
        label       TEXT,
        added_at    TEXT DEFAULT (datetime('now','localtime')),
        tag         TEXT,
        sort_order  INTEGER,
        username    TEXT,
        UNIQUE(username, asset_type, symbol, scheme_code)
    );
    INSERT INTO watchlist_new ({", ".join(keep)})
        SELECT {", ".join(keep)} FROM watchlist;
    DROP TABLE watchlist;
    ALTER TABLE watchlist_new RENAME TO watchlist;
    """)


# ------------------------------------------------------------- users
def get_user(username):
    if not username:
        return None
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT username, email, email_verified, google_sub, role, "
            "created, display_name FROM users WHERE username=?",
            (username.strip().lower(),)).fetchone()
    if not row:
        return None
    return {"username": row[0], "email": row[1], "email_verified": bool(row[2]),
            "has_google": bool(row[3]), "role": row[4] or ROLE_USER,
            "created": row[5], "display_name": row[6]}


def is_admin(username):
    u = get_user(username)
    return bool(u and u["role"] == ROLE_ADMIN)


def find_by_email(email):
    with db.get_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE email=?",
                           (email.strip().lower(),)).fetchone()
    return row[0] if row else None


def find_by_google_sub(sub):
    with db.get_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE google_sub=?",
                           (sub,)).fetchone()
    return row[0] if row else None


def list_users():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT u.username, u.email, u.email_verified, u.role, u.created, "
            "t.tg_username FROM users u LEFT JOIN telegram_links t "
            "ON t.username = u.username ORDER BY u.created").fetchall()
    return [{"username": r[0], "email": r[1], "email_verified": bool(r[2]),
             "role": r[3], "created": r[4], "telegram": r[5]} for r in rows]


def set_role(username, role):
    if role not in (ROLE_ADMIN, ROLE_USER):
        raise ValueError("role must be admin or user")
    with db.get_conn() as conn:
        if role == ROLE_USER:
            admins = conn.execute("SELECT COUNT(*) FROM users WHERE role=?",
                                  (ROLE_ADMIN,)).fetchone()[0]
            cur = conn.execute("SELECT role FROM users WHERE username=?",
                               (username,)).fetchone()
            if cur and cur[0] == ROLE_ADMIN and admins <= 1:
                raise ValueError("cannot demote the last admin")
        conn.execute("UPDATE users SET role=? WHERE username=?",
                     (role, username))


def delete_user(username, acting_admin=None):
    """Remove an account and everything it owns. Refuses to delete the
    account making the request and the last remaining admin, so the
    install can never lock itself out. Returns {table: rows} removed."""
    username = (username or "").strip().lower()
    u = get_user(username)
    if not u:
        raise LookupError("No such user.")
    if acting_admin and username == acting_admin.strip().lower():
        raise ValueError("You cannot delete the account you are signed in "
                         "with. Ask another admin, or make someone else "
                         "admin first.")
    if u["role"] == ROLE_ADMIN:
        with db.get_conn() as conn:
            admins = conn.execute("SELECT COUNT(*) FROM users WHERE role=?",
                                  (ROLE_ADMIN,)).fetchone()[0]
        if admins <= 1:
            raise ValueError("cannot delete the last admin")
    return db.delete_user_rows(username)


def validate_username(username):
    u = (username or "").strip().lower()
    if not USERNAME_RE.match(u):
        raise ValueError("Username: 3-30 characters, letters, digits, "
                         "dot, dash or underscore, starting with a letter "
                         "or digit.")
    return u


def validate_email(email):
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 254:
        raise ValueError("That doesn't look like an email address.")
    return e


def username_from_email(email):
    """Derive a free username for a Google sign-up."""
    base = re.sub(r"[^a-z0-9_.-]", "", email.split("@")[0].lower())[:24]
    if len(base) < 3:
        base = "user" + base
    with db.get_conn() as conn:
        cand, n = base, 1
        while conn.execute("SELECT 1 FROM users WHERE username=?",
                           (cand,)).fetchone():
            n += 1
            cand = f"{base}{n}"
    return cand


def register(username, password, email=None, role=None, verified=False,
             google_sub=None, display_name=None):
    """Create an account. `password` may be None for Google-only accounts
    (a random one is set so the row is valid; they can reset it later)."""
    from app.core import auth
    username = validate_username(username)
    email = validate_email(email) if email else None
    if email and find_by_email(email):
        raise ValueError("An account with that email already exists.")
    if google_sub and find_by_google_sub(google_sub):
        raise ValueError("That Google account is already linked.")
    if password is None:
        password = secrets.token_urlsafe(24)
    if role is None:
        # very first account is the admin, later ones are users
        with db.get_conn() as conn:
            role = ROLE_ADMIN if conn.execute(
                "SELECT COUNT(*) FROM users").fetchone()[0] == 0 else ROLE_USER
    with db.get_conn() as conn:
        first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    auth.create_user(username, password)          # hashing lives there
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET email=?, email_verified=?, "
                     "google_sub=?, role=?, display_name=? WHERE username=?",
                     (email, 1 if (verified or not email) else 0, google_sub,
                      role, display_name, username))
    # The first account inherits the pre-account watchlist (claimed by the
    # setup route); everyone after it gets the starter list so their
    # ribbon and Home are not empty on the first visit.
    if not first:
        seed_starter_watchlist(username)
    return username


# ------------------------------------------------------------- starter list
_starter_checked = set()
_starter_lock = threading.Lock()


def ensure_starter(username):
    """Accounts created before the starter list existed (or whose sign-up
    seeding failed) get it on their next request, if their watchlist is
    empty. Checked once per account per process; the starter_seeded flag
    makes it once ever, so a list someone emptied on purpose stays empty."""
    if not username or username in _starter_checked:
        return
    with _starter_lock:
        if username in _starter_checked:
            return
        _starter_checked.add(username)
    try:
        with db.get_conn() as conn:
            row = conn.execute("SELECT starter_seeded FROM users WHERE "
                               "username=?", (username,)).fetchone()
            if not row or row[0]:
                return
            n = conn.execute("SELECT COUNT(*) FROM watchlist WHERE username=?",
                             (username,)).fetchone()[0]
            conn.execute("UPDATE users SET starter_seeded=1 WHERE username=?",
                         (username,))
    except Exception:
        return
    if n == 0:
        seed_starter_watchlist(username)


def _pick_scheme(hits, spec):
    """First mfapi search hit whose name has every `must` word and none
    of the avoid words. hits: [(scheme_code, scheme_name), ...]."""
    must = [w.lower() for w in spec.get("must", [])]
    for code, name in hits:
        low = (name or "").lower()
        if all(w in low for w in must) and not any(
                a in low for a in config.STARTER_FUND_AVOID):
            return int(code), name
    return None, None


def _seed_starter_background(username, missing_symbols):
    """Runs in a thread after sign-up: resolve the starter funds on
    mfapi.in and pull price/NAV history the new user does not have yet.
    Everything here is best-effort; the account works without it."""
    from app.data_sources import downloader
    quiet = lambda m: None                                    # noqa: E731
    for spec in config.STARTER_FUNDS:
        code, name = None, None
        try:
            code, name = _pick_scheme(downloader.search_schemes(
                spec["query"]), spec)
        except Exception:
            pass
        if code is None:
            code, name = spec.get("scheme_code"), spec["label"]
        if code is None:
            continue
        db.add_mf(code, (name or spec["label"])[:60], username=username)
        if not db.recent_navs(code, 1):
            downloader.download_mf(code, name or spec["label"], quiet)
    for symbol in missing_symbols:
        if db.stored_rows(symbol):
            continue                       # another sign-up got there first
        try:
            downloader.download_one(symbol=symbol, asset_type="stock",
                                    progress=quiet)
        except Exception:
            pass


def seed_starter_watchlist(username):
    """Ten large-caps now (DB only), five funds and any missing history
    in the background, so sign-up stays fast even when the market data
    sources are slow or unreachable."""
    try:
        missing = db.seed_user_watchlist(username)
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET starter_seeded=1 WHERE username=?",
                         (username,))
    except Exception:
        return
    t = threading.Thread(target=_seed_starter_background,
                         args=(username, missing), daemon=True,
                         name=f"starter-{username}")
    t.start()


def link_google(username, sub):
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET google_sub=?, email_verified=1 "
                     "WHERE username=?", (sub, username))


def mark_verified(username):
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET email_verified=1 WHERE username=?",
                     (username,))


def set_email(username, email):
    email = validate_email(email)
    other = find_by_email(email)
    if other and other != username:
        raise ValueError("That email is already used by another account.")
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET email=?, email_verified=0 "
                     "WHERE username=?", (email, username))


def change_password(username, new_password, keep_session_token=None):
    from app.core import auth
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = os.urandom(16)
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE username=?",
                     (auth._hash(new_password, salt), salt, username))
    # sign out every other device
    auth.end_all_sessions(username, except_token=keep_session_token)


# ------------------------------------------------------------- tokens
def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def issue_token(username, kind):
    ttl = VERIFY_TTL_H if kind == "verify" else RESET_TTL_H
    raw = secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode()).hexdigest()
    exp = (dt.datetime.now() + dt.timedelta(hours=ttl)).isoformat(
        timespec="seconds")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE username=? AND kind=?",
                     (username, kind))          # one live token per kind
        conn.execute("INSERT INTO auth_tokens VALUES (?,?,?,?,0)",
                     (h, username, kind, exp))
        conn.execute("DELETE FROM auth_tokens WHERE expires < ?", (_now(),))
    return raw


def consume_token(raw, kind):
    """Return the username for a valid unused token and burn it, else None."""
    if not raw:
        return None
    h = hashlib.sha256(raw.encode()).hexdigest()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT username, expires, used FROM auth_tokens "
            "WHERE token_hash=? AND kind=?", (h, kind)).fetchone()
        if not row or row[2] or row[1] < _now():
            return None
        conn.execute("UPDATE auth_tokens SET used=1 WHERE token_hash=?", (h,))
    return row[0]


# ------------------------------------------------------------- invites
def create_invite(created_by, max_uses=1, note=None):
    code = secrets.token_urlsafe(8).replace("-", "x").replace("_", "y")[:10]
    with db.get_conn() as conn:
        conn.execute("INSERT INTO invite_codes VALUES (?,?,?,?,0,?)",
                     (code, created_by, _now(), int(max_uses), note))
    return code


def list_invites():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT code, created_by, created_at, max_uses, uses, note "
            "FROM invite_codes ORDER BY created_at DESC").fetchall()
    return [{"code": r[0], "created_by": r[1], "created_at": r[2],
             "max_uses": r[3], "uses": r[4], "note": r[5],
             "exhausted": r[4] >= r[3]} for r in rows]


def delete_invite(code):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM invite_codes WHERE code=?", (code,))


def invite_valid(code):
    if not code:
        return False
    with db.get_conn() as conn:
        row = conn.execute("SELECT max_uses, uses FROM invite_codes "
                           "WHERE code=?", (code.strip(),)).fetchone()
    return bool(row and row[1] < row[0])


def redeem_invite(code, username):
    with db.get_conn() as conn:
        row = conn.execute("SELECT max_uses, uses FROM invite_codes "
                           "WHERE code=?", (code.strip(),)).fetchone()
        if not row or row[1] >= row[0]:
            raise ValueError("That invite code is not valid.")
        conn.execute("UPDATE invite_codes SET uses=uses+1 WHERE code=?",
                     (code.strip(),))
        conn.execute("INSERT INTO invite_redemptions VALUES (?,?,?)",
                     (code.strip(), username, _now()))


# ------------------------------------------------------------- telegram
def telegram_link_code(username):
    code = secrets.token_urlsafe(9)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM telegram_link_codes WHERE username=?",
                     (username,))
        conn.execute("INSERT INTO telegram_link_codes VALUES (?,?,?)",
                     (code, username, _now()))
    return code


def telegram_redeem(code, chat_id, tg_username=None):
    """Called by the bot on /start <code>. Returns username or None."""
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=TG_CODE_TTL_MIN)
              ).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        row = conn.execute("SELECT username, created_at FROM "
                           "telegram_link_codes WHERE code=?",
                           (code,)).fetchone()
        if not row or row[1] < cutoff:
            return None
        conn.execute("DELETE FROM telegram_link_codes WHERE code=?", (code,))
        conn.execute("INSERT OR REPLACE INTO telegram_links VALUES (?,?,?,?)",
                     (row[0], str(chat_id), tg_username, _now()))
    return row[0]


def telegram_unlink(username=None, chat_id=None):
    with db.get_conn() as conn:
        if username:
            conn.execute("DELETE FROM telegram_links WHERE username=?",
                         (username,))
        if chat_id:
            conn.execute("DELETE FROM telegram_links WHERE chat_id=?",
                         (str(chat_id),))


def telegram_chat_for(username):
    with db.get_conn() as conn:
        row = conn.execute("SELECT chat_id, tg_username, linked_at FROM "
                           "telegram_links WHERE username=?",
                           (username,)).fetchone()
    return ({"chat_id": row[0], "tg_username": row[1], "linked_at": row[2]}
            if row else None)


def telegram_linked_users():
    with db.get_conn() as conn:
        return conn.execute("SELECT username, chat_id FROM telegram_links"
                            ).fetchall()


# ------------------------------------------------------------- analyst quota
def analyst_quota(username):
    """(used_today, limit) — limit None means unlimited (admin)."""
    if is_admin(username):
        return 0, None
    day = dt.date.today().isoformat()
    with db.get_conn() as conn:
        row = conn.execute("SELECT count FROM analyst_usage WHERE username=? "
                           "AND day=?", (username, day)).fetchone()
    return (row[0] if row else 0), ANALYST_DAILY_FREE


def analyst_consume(username):
    """Increment today's count; return False if over the limit."""
    used, limit = analyst_quota(username)
    if limit is not None and used >= limit:
        return False
    day = dt.date.today().isoformat()
    with db.get_conn() as conn:
        conn.execute("INSERT INTO analyst_usage (username, day, count) "
                     "VALUES (?,?,1) ON CONFLICT(username, day) "
                     "DO UPDATE SET count=count+1", (username, day))
    return True


# ------------------------------------------------------------- rate limits
_hits = {}
_hits_lock = threading.Lock()

LIMITS = {                       # scope -> (max hits, window seconds)
    "login_ip": (20, 900),
    "login_user": (8, 900),
    "signup_ip": (5, 3600),
    "forgot_ip": (5, 3600),
    "google_ip": (20, 900),
}


def rate_limited(scope, key):
    """True if (scope, key) has exceeded its window. Records the hit."""
    limit, window = LIMITS[scope]
    now = time.time()
    k = (scope, key)
    with _hits_lock:
        q = [t for t in _hits.get(k, []) if now - t < window]
        if len(q) >= limit:
            _hits[k] = q
            return True
        q.append(now)
        _hits[k] = q
        if len(_hits) > 5000:            # crude memory bound
            for kk in list(_hits)[:1000]:
                _hits.pop(kk, None)
    return False


def rate_clear(scope, key):
    with _hits_lock:
        _hits.pop((scope, key), None)
