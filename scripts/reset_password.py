#!/usr/bin/env python3
"""
reset_password.py — recover access when you've forgotten your login.

    python scripts/reset_password.py            # interactive
    python scripts/reset_password.py --list     # just show the usernames
    python scripts/reset_password.py --user yourname --password 'NewPass123'

Works from ANY directory (it locates the project itself). What it does:

  1. Lists every account in data/market_data.db — so a forgotten
     USERNAME is solved too.
  2. Copies the database to data/backups/market_data.<timestamp>.db
     BEFORE writing anything.
  3. Rewrites ONLY the pw_hash + salt of the account you pick, using the
     app's own auth._hash(), so the new password is stored exactly the way
     the login route expects. Holdings, watchlist, prices, journal, notes,
     sessions of other users — nothing else is touched.
  4. Ends that user's existing sessions so a stale cookie can't linger.

Stop the server first if it's running (uvicorn holds the DB open in WAL
mode; the write still works, but a clean stop avoids any surprise).
"""

import argparse
import datetime as dt
import getpass
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core import auth, config           # noqa: E402
from app.core import database as db         # noqa: E402


def list_users(conn):
    return conn.execute(
        "SELECT username, created FROM users ORDER BY created").fetchall()


def backup_db():
    src = pathlib.Path(config.DB_PATH)
    if not src.exists():
        return None
    dst_dir = src.parent / "backups"
    dst_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = dst_dir / f"market_data.{stamp}.db"
    shutil.copy2(src, dst)
    # WAL sidecar may hold un-checkpointed rows; copy it too if present
    wal = src.with_name(src.name + "-wal")
    if wal.exists():
        shutil.copy2(wal, dst.with_name(dst.name + "-wal"))
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true",
                    help="show the accounts and exit")
    ap.add_argument("--user", help="account to reset (else asked)")
    ap.add_argument("--password", help="new password (else asked, hidden)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the automatic DB backup")
    args = ap.parse_args()

    print(f"Database: {config.DB_PATH}")
    if not pathlib.Path(config.DB_PATH).exists():
        print("That file doesn't exist — the app has never been started "
              "here, or data/ was moved. Nothing to reset; start the app "
              "and the login page will offer to create the first account.")
        return 1

    auth._ensure_tables()                       # no-op if present
    with db.get_conn() as conn:
        users = list_users(conn)

    if not users:
        print("No accounts exist yet. Start the app — the login page will "
              "offer to create the first (admin) account.")
        return 0

    print("Accounts:")
    for u, created in users:
        print(f"  {u:<24} created {created}")
    if args.list:
        return 0

    names = [u for u, _ in users]
    username = (args.user or input("\nUsername to reset: ")).strip().lower()
    if username not in names:
        print(f"No account named {username!r}. Nothing was changed.")
        return 1

    if args.password:
        new_password = args.password
    else:
        new_password = getpass.getpass("New password (min 8 chars): ")
        if new_password != getpass.getpass("Confirm new password: "):
            print("Passwords didn't match. Nothing was changed.")
            return 1
    if len(new_password) < 8:
        print("Password must be at least 8 characters. Nothing was changed.")
        return 1

    if not args.no_backup:
        dst = backup_db()
        if dst:
            print(f"Backup written: {dst}")

    salt = os.urandom(16)
    pw_hash = auth._hash(new_password, salt)
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE username=?",
                     (pw_hash, salt, username))
        conn.execute("DELETE FROM sessions WHERE username=?", (username,))

    print(f"Done. Password for {username!r} has been reset — start the app "
          "and sign in with it. Everything else in the database is exactly "
          "as it was.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
