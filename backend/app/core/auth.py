"""
Authentication for the web UI — cookie sessions, PBKDF2 passwords.

Scope, honestly stated:
  - Named accounts with PER-USER PORTFOLIOS: each account has its own
    holdings, sells, and dividends — a new account starts with a fresh,
    empty portfolio. The rest (watchlist, prices, alerts, journal,
    research caches) is still shared, which suits "my family/friends
    each track their own portfolio on the same home-network install".
  - Any portfolio data that existed before accounts were introduced is
    assigned to the first (admin) account when it is created.

Mechanics:
  - Passwords: PBKDF2-HMAC-SHA256, 200k iterations, 16-byte per-user
    salt. Never stored or logged in plain text.
  - Sessions: 32-byte random tokens, HttpOnly cookie, 30-day expiry,
    deleted on logout. Only a SHA-256 of each token is stored, so a copy
    of the database (a backup, the PC dev copy) cannot be used to sign
    in as anyone.
  - First run: no users exist -> the login page offers "create the
    first account", which becomes the admin. After that, new accounts
    can only be created by a logged-in user (Settings on the login
    card), so a LAN stranger can't self-register.
  - Cookies are not marked Secure because the app serves plain HTTP on
    localhost/LAN. Do not expose this to the internet as-is; see the
    security section of the documentation.
"""

import datetime as dt
import hashlib
import os

from app.core import database as db

PBKDF2_ITERS = 200_000
SESSION_DAYS = 30


_ensured_for = set()      # DB paths already checked; this ran on every request


def _ensure_tables():
    from app.core import config
    if config.DB_PATH in _ensured_for:
        return
    _ensured_for.add(config.DB_PATH)
    with db.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            pw_hash  BLOB NOT NULL,
            salt     BLOB NOT NULL,
            created  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token    TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires  TEXT NOT NULL
        );
        """)
        # 2026-10: `token` now holds sha256(cookie). Raw tokens and their
        # hashes are both 64 hex chars, so a flag column marks converted
        # rows; existing sessions are hashed in place (nobody signed out).
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        if "hashed" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN hashed INTEGER "
                         "NOT NULL DEFAULT 0")
        for (raw,) in conn.execute(
                "SELECT token FROM sessions WHERE hashed=0").fetchall():
            conn.execute("UPDATE sessions SET token=?, hashed=1 "
                         "WHERE token=? AND hashed=0", (_tok(raw), raw))


def _tok(raw):
    """What the sessions table stores for a cookie value."""
    return hashlib.sha256(str(raw).encode()).hexdigest()


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt,
                               PBKDF2_ITERS)


def any_users():
    _ensure_tables()
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def create_user(username, password):
    _ensure_tables()
    username = username.strip().lower()
    if not username or len(username) > 40:
        raise ValueError("Username must be 1-40 characters.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = os.urandom(16)
    with db.get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username=?",
                              (username,)).fetchone()
        if exists:
            raise ValueError("That username already exists.")
        first_user = conn.execute(
            "SELECT COUNT(*) FROM users").fetchone()[0] == 0
        conn.execute("INSERT INTO users (username, pw_hash, salt, created) "
                     "VALUES (?,?,?,?)",
                     (username, _hash(password, salt), salt,
                      dt.datetime.now().isoformat(timespec="seconds")))
    if first_user:
        # a portfolio may predate accounts entirely — it belongs to the
        # person setting up the first (admin) account, not to nobody.
        db.claim_orphan_portfolio_rows(username)
    return username


def verify(username, password):
    _ensure_tables()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT pw_hash, salt FROM users WHERE username=?",
            (username.strip().lower(),)).fetchone()
    if not row:
        # constant-ish time: still do the work
        _hash(password, os.urandom(16))
        return False
    pw_hash, salt = row
    import hmac as _hmac
    return _hmac.compare_digest(pw_hash, _hash(password, salt))


def start_session(username):
    _ensure_tables()
    token = os.urandom(32).hex()
    expires = (dt.datetime.now()
               + dt.timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO sessions (token, username, expires, hashed) "
                     "VALUES (?,?,?,1)",
                     (_tok(token), username.strip().lower(), expires))
        # opportunistic cleanup of expired sessions
        conn.execute("DELETE FROM sessions WHERE expires < ?",
                     (dt.datetime.now().isoformat(timespec="seconds"),))
    return token


def session_user(token):
    if not token:
        return None
    _ensure_tables()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT username, expires FROM sessions WHERE token=?",
            (_tok(token),)).fetchone()
    if not row:
        return None
    username, expires = row
    if expires < dt.datetime.now().isoformat(timespec="seconds"):
        end_session(token)
        return None
    return username


def end_session(token):
    if not token:
        return
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (_tok(token),))


def end_all_sessions(username, except_token=None):
    """Sign `username` out everywhere (but this device, if given).
    Returns how many sessions ended."""
    with db.get_conn() as conn:
        if except_token:
            return conn.execute(
                "DELETE FROM sessions WHERE username=? AND token<>?",
                (username, _tok(except_token))).rowcount
        return conn.execute("DELETE FROM sessions WHERE username=?",
                            (username,)).rowcount


def session_count(username):
    """Live (unexpired) sessions, i.e. signed-in browsers/devices."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE username=? AND expires>=?",
            (username, now)).fetchone()[0]
