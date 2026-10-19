"""
Make a development copy of the database with nobody else's data in it.

The PC is for development; real accounts live on the phone. A full copy
of the production database on a laptop is everyone's portfolio, email
address and Telegram link sitting somewhere it doesn't need to be. This
writes data/market_data.dev.db from data/market_data.db and keeps:

  - all market data (prices, NAVs, fundamentals, filings fetched from BSE)
  - ONE account, yours, with its watchlist, holdings and notes

and removes every other account with everything it owns (the same
deletion the admin "delete user" button runs), plus every login session,
email/reset token, invite code and Telegram link, including yours. Free
pages are then wiped (VACUUM) so deleted rows cannot be recovered from
the file.

    python scripts/make_dev_db.py              keeps the first admin
    python scripts/make_dev_db.py --keep yourname

run.bat then uses the copy automatically (LEDGERLINE_DB=market_data.dev.db).
The original data/market_data.db is not touched; delete it yourself once
you are sure the phone holds everything you need.
"""

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from app.core import paths  # noqa: E402

SRC = paths.DATA_DIR / "market_data.db"
DST = paths.DATA_DIR / "market_data.dev.db"
# credential and contact tables: emptied for everyone, the kept account too
WIPE_ALL = ("sessions", "auth_tokens", "invite_codes", "invite_redemptions",
            "telegram_links", "telegram_link_codes", "digest_sends")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", help="account to keep (default: first admin)")
    args = ap.parse_args()
    if not SRC.exists():
        sys.exit(f"no database at {SRC}")

    # sqlite's backup API: a consistent copy even while the server runs
    tmp = DST.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    src, dst = sqlite3.connect(SRC), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:                        # `with` would commit but not close
        src.close()
        dst.close()

    from app.core import config
    config.DB_PATH = str(tmp)
    from app.core import database as db

    with db.get_conn() as conn:
        users = conn.execute("SELECT username, role FROM users "
                             "ORDER BY created").fetchall()
    if not users:
        sys.exit("the database has no accounts")
    keep = args.keep or next((u for u, r in users if r == "admin"), users[0][0])
    if keep not in [u for u, _ in users]:
        sys.exit(f"no account named {keep!r}; accounts: "
                 + ", ".join(u for u, _ in users))

    for user, _role in users:
        if user != keep:
            removed = db.delete_user_rows(user)
            n = sum(removed.values())
            print(f"removed account {user!r} and {n} rows it owned")
    with db.get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in WIPE_ALL:
            if t in tables:
                n = conn.execute(f"DELETE FROM {t}").rowcount
                print(f"emptied {t} ({n} rows)")
    db.close_conn()                 # the file must be closed to be renamed
    conn = sqlite3.connect(tmp)
    conn.execute("VACUUM")          # deleted rows must not linger in free pages
    conn.close()

    os.replace(tmp, DST)
    for side in ("-wal", "-shm"):
        p = str(DST) + side
        if os.path.exists(p):
            os.remove(p)
    print(f"\nwrote {DST} keeping only {keep!r}. Sign in again on the PC.")
    print("run.bat uses it from now on. The original market_data.db is "
          "unchanged; delete it once the phone has everything you need.")


if __name__ == "__main__":
    main()
