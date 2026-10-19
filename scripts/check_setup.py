#!/usr/bin/env python3
"""Check a copied install: which database the server will open, which
accounts and holdings are in it, and whether each portfolio can be built.
Run it on the PC that has the problem, from anywhere:

    python scripts/check_setup.py
    python scripts/check_setup.py --login yourname      (asks for the password)

Use the same Python and the same LEDGERLINE_DB as the server does (run.bat
sets LEDGERLINE_DB=market_data.dev.db whenever data\\market_data.dev.db
exists). It only reads: nothing in the database is changed. The password
for --login is typed here, checked here, and never printed or stored.
"""
import datetime as dt
import getpass
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

OK, FAIL, WARN = "[ok]  ", "[FAIL]", "[warn]"


def _when(p):
    return dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def main():
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    print(f"LEDGERLINE_DB = {os.environ.get('LEDGERLINE_DB')!r}")
    try:
        from app.core import config, database as db, auth, accounts
    except Exception as e:
        print(f"{FAIL} the app cannot be imported: {e!r}")
        print("       run setup_venv.bat on this PC and start with run.bat")
        return 1
    path = Path(config.DB_PATH)
    print(f"database the server opens: {path}")
    if not path.exists():
        print(f"{FAIL} that file does not exist: the server would start EMPTY")
        return 1
    print(f"       size {path.stat().st_size // 1_000_000} MB, "
          f"last changed {_when(path)}")
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        print(f"       {wal.name}: {wal.stat().st_size // 1_000_000} MB "
              "(recent changes; it must travel with the .db file)")
    for other in sorted(path.parent.glob("market_data*.db")):
        if other != path:
            print(f"{WARN} another database is next to it: {other.name} "
                  f"(last changed {_when(other)}); the server does NOT use it")

    users = accounts.list_users()
    if not users:
        print(f"{FAIL} no accounts in this database")
        return 1
    from types import SimpleNamespace
    from app import main as app_main
    for u in users:
        name = u["username"]
        lots = db.get_holdings(name)
        print(f"account {name!r} ({u['role']}): {len(lots)} holding lots")
        token = db.current_user.set(name)
        try:
            req = SimpleNamespace(state=SimpleNamespace(user=name, role=u["role"]),
                                  cookies={})
            out = app_main.get_portfolio(req)
            shown = len(out.get("holdings") or []) if isinstance(out, dict) else "?"
            mark = OK if (shown or not lots) else FAIL
            print(f"{mark} portfolio page builds: {shown} rows")
        except Exception as e:
            print(f"{FAIL} portfolio page fails: {e!r}")
            traceback.print_exc(limit=3)
        finally:
            db.current_user.reset(token)

    if "--login" in sys.argv:
        i = sys.argv.index("--login")
        who = sys.argv[i + 1] if i + 1 < len(sys.argv) else input("username: ")
        pw = getpass.getpass(f"password for {who} (not shown): ")
        if auth.verify(who, pw):
            print(f"{OK} {who!r} and that password match this database")
        else:
            print(f"{FAIL} {who!r} and that password do NOT match this database")
    return 0


if __name__ == "__main__":
    sys.exit(main())
