"""HTTP-level tests through FastAPI's TestClient against a temp database
seeded with synthetic prices (see conftest.py)."""
import datetime as dt
import logging
import threading

import pytest

from tests.conftest import PASSWORD


@pytest.fixture
def holding(login):
    """Add a TEST.NS lot for a user and return its id."""
    def _add(user, qty=10, price=100.0, buy_date="2024-01-10",
             symbol="TEST.NS"):
        c = login(user)
        r = c.post("/api/portfolio", json={"symbol": symbol, "qty": qty,
                                           "buy_price": price,
                                           "buy_date": buy_date})
        assert r.status_code == 200, r.text
        lots = c.get(f"/api/detail/{symbol}").json()["position"]["lots"]
        return max(l["id"] for l in lots)
    return _add


# ------------------------------------------------------------- startup
def test_import_starts_no_background_workers(app):
    names = {t.name for t in threading.enumerate()}
    assert "telegram-poll" not in names
    assert "ipo-subscription" not in names


def test_server_lifespan_starts_background_workers(app):
    """Run last-ish: entering the lifespan starts the (sleeping) loops.
    Telegram stays off because conftest removed its token."""
    from fastapi.testclient import TestClient
    with TestClient(app):
        names = {t.name for t in threading.enumerate()}
    assert "ipo-subscription" in names
    assert "telegram-poll" not in names


# ------------------------------------------------------------- auth
def test_anonymous_requests_are_rejected(anon):
    assert anon.get("/api/portfolio").status_code == 401
    r = anon.get("/portfolio", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"
    assert anon.get("/api/auth/status").status_code == 200    # public


def test_wrong_password(login, anon):
    login("erin")
    r = anon.post("/api/auth/login", json={"username": "erin",
                                           "password": "nope-nope-nope"})
    assert r.status_code == 401


def test_login_is_rate_limited_per_user(login, anon):
    login("frank")
    codes = [anon.post("/api/auth/login",
                       json={"username": "frank", "password": "bad"}
                       ).status_code for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429
    # even the right password is refused while limited
    r = anon.post("/api/auth/login", json={"username": "frank",
                                           "password": PASSWORD})
    assert r.status_code == 429


def test_me(login):
    me = login("alice").get("/api/auth/me").json()
    assert me["user"] == "alice" and me["role"] == "user"
    assert login("admin1").get("/api/auth/me").json()["role"] == "admin"


@pytest.mark.parametrize("method, path, admin_only", [
    ("POST", "/api/refresh", False),            # open to every user
    ("GET", "/api/refresh/status", False),
    ("POST", "/api/news/refresh", False),       # open to every user
    ("POST", "/api/news/feeds", True),          # managing feeds is not
    ("POST", "/api/nse/sync", True),
    ("GET", "/api/doctor/report", True),
    ("POST", "/api/digest/send", True),
    ("POST", "/api/digest/send-mine", False),   # prefix must not swallow it
    ("GET", "/api/admin/users", True),
    ("POST", "/api/universe/nifty50/prepare", True),
    ("GET", "/api/universe/status", False),
    ("DELETE", "/api/news/feeds/3", True),
    ("GET", "/api/news/feeds", False),
])
def test_admin_path_rules(app, method, path, admin_only):
    from app.main import _is_admin_path
    assert _is_admin_path(method, path) is admin_only


def test_admin_routes_enforced(login):
    user, admin = login("alice"), login("admin1")
    for method, path in (("POST", "/api/nse/sync"),
                         ("GET", "/api/doctor/report"),
                         ("GET", "/api/admin/users")):
        assert user.request(method, path).status_code == 403
    assert admin.get("/api/doctor/report").status_code == 200


def test_user_can_refresh_market_data_and_news(login, monkeypatch):
    """Both refreshes are open to normal users; the jobs themselves are
    stubbed so nothing is downloaded."""
    import app.main as main
    from app.feeds import news
    started = []
    monkeypatch.setattr(main, "_do_refresh", lambda: started.append("data"))
    monkeypatch.setattr(main, "REFRESH", {"running": False, "log": [],
                                          "done": False})
    monkeypatch.setattr(news, "refresh_in_background",
                        lambda: started.append("news") or True)
    user = login("alice")
    assert user.post("/api/refresh").json() == {"status": "started"}
    assert user.post("/api/news/refresh").json() == {"status": "started"}
    main.REFRESH["running"] = True                 # a run is in progress
    assert user.post("/api/refresh").json() == {"status": "already_running"}
    import time
    for _ in range(50):                            # thread start is async
        if "data" in started:
            break
        time.sleep(0.02)
    assert sorted(started) == ["data", "news"]


# ------------------------------------------------------- isolation
def test_holdings_are_private(login, holding):
    lot = holding("alice")
    bob = login("bob")
    assert bob.get("/api/portfolio").json()["holdings"] == []
    bob.delete(f"/api/portfolio/{lot}")                 # not his: no-op
    r = bob.post("/api/sell", json={"lot_id": lot, "qty": 1, "price": 120,
                                    "date": "2025-02-01"})
    assert r.status_code == 404
    alice_lots = login("alice").get("/api/detail/TEST.NS").json()
    assert lot in [l["id"] for l in alice_lots["position"]["lots"]]


def test_notes_are_private(login):
    alice, bob = login("alice"), login("bob")
    alice.post("/api/notes", json={"symbol": "test.ns", "text": "thesis"})
    note = alice.get("/api/notes/TEST.NS").json()["notes"][-1]
    assert note["text"] == "thesis"
    assert bob.get("/api/notes/TEST.NS").json()["notes"] == []
    bob.delete(f"/api/notes/{note['id']}")
    assert note["id"] in [n["id"] for n in
                          alice.get("/api/notes/TEST.NS").json()["notes"]]
    assert alice.post("/api/notes", json={"symbol": "X", "text": "  "}
                      ).status_code == 400


def test_alerts_are_private(login):
    alice, bob = login("alice"), login("bob")
    kind = alice.get("/api/alerts").json()["kinds"]
    kind = next(iter(kind))
    assert alice.post("/api/alerts", json={"symbol": "TEST.NS",
                                           "kind": kind, "value": 150}
                      ).status_code == 200
    mine = alice.get("/api/alerts").json()["alerts"]
    assert bob.get("/api/alerts").json()["alerts"] == []
    bob.delete(f"/api/alerts/{mine[-1]['id']}")
    assert len(alice.get("/api/alerts").json()["alerts"]) == len(mine)
    assert alice.post("/api/alerts", json={"symbol": "TEST.NS",
                                           "kind": "bogus"}).status_code == 400


# ------------------------------------------------------- sells and tax
def test_sell_flow_and_tax_split(login, holding):
    c = login("gita")
    lot = holding("gita", qty=10, price=100.0, buy_date="2024-01-10")
    # exactly 12 months later (366 days, leap year): still short-term
    r = c.post("/api/sell", json={"lot_id": lot, "qty": 4, "price": 150,
                                  "date": "2025-01-10"})
    assert r.json() == {"ok": True, "remaining": 6}
    # one day later: long-term
    r = c.post("/api/sell", json={"lot_id": lot, "qty": 6, "price": 150,
                                  "date": "2025-01-11"})
    assert r.json()["remaining"] == 0
    assert c.get("/api/portfolio").json()["holdings"] == []   # lot closed

    years = c.get("/api/taxreport").json()["years"]
    assert years == [{"fy": "FY2024-25", "stcg": 200.0, "ltcg": 300.0,
                      "trades": 2, "unknown_period": 0}]
    realized = c.get("/api/portfolio").json()["realized"]
    assert realized["short_term"] == 200.0
    assert realized["long_term"] == 300.0
    assert sorted(r["term"] for r in realized["rows"]) == ["LT", "ST"]


@pytest.mark.parametrize("body, msg", [
    ({"qty": 1, "price": 120, "date": "05/03/2025"}, "YYYY-MM-DD"),
    ({"qty": 1, "price": 120, "date": ""}, "YYYY-MM-DD"),
    ({"qty": 1, "price": 120, "date": "2023-12-31"}, "before the buy date"),
    ({"qty": 99, "price": 120, "date": "2025-01-01"}, "Quantity"),
    ({"qty": 1, "price": 0, "date": "2025-01-01"}, "positive"),
])
def test_sell_validation(login, holding, body, msg):
    c = login("hari")
    lot = holding("hari")
    r = c.post("/api/sell", json={"lot_id": lot, **body})
    assert r.status_code == 400 and msg in r.json()["detail"]
    assert c.get("/api/portfolio").status_code == 200


def test_bad_buy_date_rejected(login):
    c = login("hari")
    r = c.post("/api/portfolio", json={"symbol": "TEST.NS", "qty": 1,
                                       "buy_price": 10,
                                       "buy_date": "15/03/2024"})
    assert r.status_code == 400
    assert c.post("/api/portfolio", json={"symbol": "TEST.NS", "qty": 0,
                                          "buy_price": 10}
                  ).status_code == 400


def test_portfolio_survives_nan_correlation(login, holding):
    """STALE.NS shares no dates with TEST.NS, so their correlation is NaN;
    that used to make /api/portfolio a 500."""
    c = login("ivan")
    holding("ivan", symbol="TEST.NS")
    holding("ivan", symbol="STALE.NS", buy_date="2021-02-01", price=10)
    r = c.get("/api/portfolio")
    assert r.status_code == 200
    m = r.json()["correlation"]["matrix"]
    assert None in m[0] + m[1]


def test_detail_position_and_gzip(login, holding):
    c = login("jaya")
    holding("jaya", buy_date="2024-01-10")
    r = c.get("/api/detail/TEST.NS", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    pos = r.json()["position"]
    assert pos["qty"] == 10 and pos["first_buy"] == "2024-01-10"
    assert pos["ltcg_eligible"] is True
    assert c.get("/api/detail/NOPE.NS").status_code == 404


def test_position_size_route(login):
    c = login("alice")
    ok = c.get("/api/position-size", params={"capital": 100000,
                                              "risk_pct": 1, "entry": 500,
                                              "stop": 475})
    assert ok.json()["shares"] == 40
    bad = c.get("/api/position-size", params={"capital": 100000,
                                               "risk_pct": -1, "entry": 500,
                                               "stop": 475})
    assert bad.status_code == 400


# ------------------------------------------------------- home
def test_home_earnings_only_from_own_watchlist(login, today):
    from app.core import database as db
    soon = (today + dt.timedelta(days=2)).isoformat()
    for sym in ("TEST.NS", "PEER.NS"):
        db.save_fundamentals(sym, {"nextEarnings": soon})
    c = login("kiran")
    db.add_ticker("TEST.NS", "stock", username="kiran")
    other = login("leela")
    db.add_ticker("PEER.NS", "stock", username="leela")
    assert [e["symbol"] for e in c.get("/api/home").json()["earnings_week"]
            ] == ["TEST"]
    assert [e["symbol"] for e in
            other.get("/api/home").json()["earnings_week"]] == ["PEER"]


# ------------------------------------------------------- analysis
def test_verdict_uses_all_inputs(app, caplog):
    """Every input to the verdict used to fail silently (wrong function
    name, len() of an int, missing column), capping the tier at 'mixed'."""
    from app.analysis import verdict
    with caplog.at_level(logging.WARNING, logger="app.analysis.verdict"):
        v = verdict.compose("TEST.NS", record=False)
    assert not [r for r in caplog.records if "failed" in r.getMessage()]
    assert v["tier"] in ("strong", "mixed", "weak")
    assert any(p["source"] == "Technical" for p in v["for"] + v["against"])


def test_verdict_trend_reads_closes(app):
    from app.analysis import verdict
    tr = verdict._trend_state("TEST.NS")
    assert set(tr) == {"above_200", "golden", "last"}
    assert verdict._trend_state("STALE.NS") is None          # < 210 rows


def test_option_sentiment_route_reports_reason(login, monkeypatch):
    from app.analysis import extras

    def no_options(symbol):
        raise RuntimeError("No options are listed for TEST on NSE")
    monkeypatch.setattr(extras, "option_sentiment", no_options)
    r = login("alice").get("/api/option-sentiment/TEST.NS")
    assert r.status_code == 502 and "No options" in r.json()["detail"]


def test_symbol_search_route(login, monkeypatch):
    from app.data_sources import symbols
    monkeypatch.setattr(symbols, "search", lambda q, limit=10: {
        "items": [{"symbol": "SOUTHBANK.NS"}], "error": None})
    r = login("alice").get("/api/symbol-search", params={"q": "south"})
    assert r.status_code == 200 and r.json()["error"] is None


# ------------------------------------------------------- scorecard tracking
def test_tracking_period_never_shrinks_and_can_be_set(app, monkeypatch):
    from app.analysis import ledger
    import datetime as _dt
    from app.core import database as db
    monkeypatch.setattr(ledger, "_today", lambda: _dt.date(2026, 1, 1))
    tok = db.current_user.set("carol")
    assert ledger.track_add(["TRK.NS"], "manual", 90) == {"added": 1,
                                                          "extended": 0}
    # a shorter re-add keeps the longer period ...
    assert ledger.track_add(["TRK.NS"], "backtest", 30)["extended"] == 0
    t = next(x for x in ledger.tracked() if x["symbol"] == "TRK.NS")
    assert (t["until"], t["days"], t["active"]) == ("2026-04-01", 90, True)
    # ... "until stopped" beats any end date
    assert ledger.track_add(["TRK.NS"], "ai_lab", None)["extended"] == 1
    assert next(x for x in ledger.tracked()
                if x["symbol"] == "TRK.NS")["until"] is None
    # setting it explicitly counts from the day it was added
    ledger.track_set_days("TRK.NS", 7)
    monkeypatch.setattr(ledger, "_today", lambda: _dt.date(2030, 1, 1))
    t = next(x for x in ledger.tracked() if x["symbol"] == "TRK.NS")
    assert t["days"] == 7 and t["active"] is False
    assert "TRK.NS" not in ledger.tracked_symbols(active_only=True)
    ledger.track_remove("TRK.NS")
    db.current_user.reset(tok)


def test_backtest_rule_goes_on_the_scorecard(login):
    c = login("alice")
    r = c.post("/api/scorecard/rule", json={"symbol": "TEST.NS",
                                            "strategy": "golden_cross",
                                            "days": 30})
    assert r.status_code == 200, r.text
    assert r.json()["recorded"] == 1
    rows = c.get("/api/scorecard?kind=rule").json()["rows"]
    row = next(x for x in rows if x["symbol"] == "TEST.NS")
    assert row["kind"] == "rule_golden_cross"
    assert row["call"] in ("in", "out") and row["horizon_days"] == 30
    assert any(t["symbol"] == "TEST.NS" and t["source"] == "backtest"
               for t in c.get("/api/scorecard/track").json()["tracked"])
    assert c.patch("/api/scorecard/track/TEST.NS",
                   json={"days": 0}).status_code == 200
    assert c.post("/api/scorecard/rule", json={
        "symbol": "TEST.NS", "strategy": "nope"}).status_code == 400
    c.delete("/api/scorecard/track/TEST.NS")


def test_backtest_now_says_why(app):
    from app.analysis import backtest
    now = backtest.run("TEST.NS")["now"]
    assert now["why"] and now["date"] and now["price"] > 0


def test_doctor_reports_duplicates_and_dedupes(login):
    from app.core import database as db
    c = login("admin_doc")
    for _ in range(2):          # the add route refuses repeats, so insert raw
        with db.get_conn() as conn:
            conn.execute("INSERT INTO watchlist (asset_type, symbol, label, "
                         "username) VALUES ('stock','TEST.NS','TEST',?)",
                         ("admin_doc",))
    rep = c.get("/api/doctor/report").json()
    assert {"symbol": "TEST.NS", "copies": 2} in rep["duplicates"]
    assert rep["checked"] == len(rep["symbols"])
    assert c.post("/api/doctor/dedupe").json()["removed"] == 1
    assert c.get("/api/doctor/report").json()["duplicates"] == []
    assert login("bob").post("/api/doctor/dedupe").status_code == 403


def test_scorecard_is_per_user(login):
    a, b = login("alice"), login("bob")
    assert a.post("/api/scorecard/rule", json={
        "symbol": "TEST.NS", "strategy": "price_above_200",
        "days": 60}).json()["recorded"] == 1
    a.post("/api/scorecard/track", json={"symbols": ["PEER.NS"],
                                         "source": "manual", "days": 30})
    # bob sees none of alice's calls or tracked stocks ...
    assert b.get("/api/scorecard/track").json()["tracked"] == []
    assert not any(r["kind"] == "rule_price_above_200"
                   for r in b.get("/api/scorecard").json()["rows"])
    # ... and can make the same call himself without clashing with hers
    assert b.post("/api/scorecard/rule", json={
        "symbol": "TEST.NS", "strategy": "price_above_200",
        "days": 60}).json()["recorded"] == 1
    # stopping is per user too
    b.delete("/api/scorecard/track/TEST.NS")
    assert {t["symbol"] for t in a.get("/api/scorecard/track")
            .json()["tracked"]} >= {"TEST.NS", "PEER.NS"}
    # the daily snapshot writes one row per tracker
    from app.analysis import ledger
    assert ledger.active_trackers()["PEER.NS"] == ["alice"]
    import time
    assert a.post("/api/scorecard/snapshot").json()["started"] is True
    assert b.get("/api/scorecard/snapshot/status").json()["running"] is False
    for _ in range(300):                 # let it finish before moving on
        st = a.get("/api/scorecard/snapshot/status").json()
        if not st["running"]:
            break
        time.sleep(0.1)
    assert st["done"] and st["log"][-1].startswith("Done:"), st
    rows = a.get("/api/scorecard").json()["rows"]
    assert any(r["symbol"] == "PEER.NS" and r["kind"] == "checklist"
               for r in rows)
    assert not any(r["symbol"] == "PEER.NS"
                   for r in b.get("/api/scorecard").json()["rows"])
    for s in ("TEST.NS", "PEER.NS"):
        a.delete(f"/api/scorecard/track/{s}")


def test_legacy_scorecard_rows_go_to_first_account(tmp_path, monkeypatch):
    import sqlite3
    from app.core import config
    from app.analysis import ledger
    dbp = tmp_path / "legacy.db"
    c = sqlite3.connect(dbp)
    c.executescript("""
        CREATE TABLE users (username TEXT PRIMARY KEY, created TEXT);
        INSERT INTO users VALUES ('second', '2026-02-01'), ('owner', '2026-01-01');
        CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, date TEXT NOT NULL, symbol TEXT NOT NULL,
            kind TEXT NOT NULL, call TEXT NOT NULL, score REAL, detail TEXT,
            price_at REAL NOT NULL, horizon_days INTEGER NOT NULL,
            date_after TEXT, price_after REAL, ret_pct REAL, bm_ret_pct REAL,
            outcome TEXT, beat_index INTEGER, resolved_at TEXT,
            UNIQUE(symbol, kind, date, horizon_days));
        INSERT INTO predictions (date, symbol, kind, call, price_at,
            horizon_days) VALUES ('2026-01-05', 'X.NS', 'verdict', 'strong',
            10, 30);
        CREATE TABLE scorecard_track (symbol TEXT PRIMARY KEY, source TEXT,
            added_at TEXT, days INTEGER, until TEXT);
        INSERT INTO scorecard_track VALUES ('X.NS', 'manual', '2026-01-05',
            NULL, NULL);
    """)
    c.commit(); c.close()
    monkeypatch.setattr(config, "DB_PATH", str(dbp))
    ledger.ensure_table()
    ledger.ensure_table()                       # idempotent
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT username, symbol FROM predictions").fetchall()         == [("owner", "X.NS")]
    assert c.execute("SELECT username, symbol FROM scorecard_track")        .fetchall() == [("owner", "X.NS")]


# ------------------------------------------------------- security
def test_security_headers_on_pages_and_401s(anon):
    for path in ("/login", "/api/watchlist"):        # served, and refused
        h = anon.get(path, follow_redirects=False).headers
        assert h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"


def test_client_ip_trusts_forwarding_only_from_the_local_tunnel():
    from types import SimpleNamespace as NS
    from app.core.auth_api import _ip

    def req(peer, **headers):
        return NS(client=NS(host=peer), headers=headers)
    # through ngrok (peer is loopback): the LAST hop is the real visitor,
    # the first is whatever the visitor typed
    assert _ip(req("127.0.0.1", **{"x-forwarded-for": "6.6.6.6, 1.2.3.4"})) \
        == "1.2.3.4"
    # straight from the network: a forwarded header is just a lie
    assert _ip(req("192.168.1.9", **{"x-forwarded-for": "6.6.6.6"})) \
        == "192.168.1.9"


def test_sessions_are_stored_hashed_and_old_ones_keep_working(app):
    import hashlib
    from app.core import auth, accounts, config, database as db
    accounts.register("hashme", "correct-horse-battery-1", verified=True)
    tok = auth.start_session("hashme")
    with db.get_conn() as conn:
        stored = [r[0] for r in conn.execute(
            "SELECT token FROM sessions WHERE username='hashme'")]
    assert tok not in stored                      # the cookie value is not in the DB
    assert hashlib.sha256(tok.encode()).hexdigest() in stored
    # a session written by the old code (raw token, hashed=0) survives the
    # one-time conversion: nobody is signed out by the update
    legacy = "ab" * 32
    with db.get_conn() as conn:
        conn.execute("INSERT INTO sessions (token, username, expires, hashed) "
                     "VALUES (?, 'hashme', '2999-01-01T00:00:00', 0)", (legacy,))
    auth._ensured_for.discard(config.DB_PATH)
    assert auth.session_user(legacy) == "hashme"
    with db.get_conn() as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE token=?",
                                (legacy,)).fetchone()


def test_logout_others_keeps_only_this_device(app):
    from fastapi.testclient import TestClient
    from app.core import accounts
    accounts.register("twodevices", "correct-horse-battery-1", verified=True)
    phone, laptop = TestClient(app), TestClient(app)
    for c in (phone, laptop):
        assert c.post("/api/auth/login", json={
            "username": "twodevices",
            "password": "correct-horse-battery-1"}).status_code == 200
    assert laptop.get("/api/auth/me").json()["sessions"] == 2
    r = laptop.post("/api/auth/logout-others")
    assert r.json()["ended"] == 1
    assert laptop.get("/api/auth/me").json()["user"] == "twodevices"
    assert phone.get("/api/watchlist").status_code == 401


def test_signin_sends_a_telegram_alert(app, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from app.alerts import notify
    from app.core import accounts
    sent = []
    monkeypatch.setattr(notify, "send_to_user",
                        lambda user, text: sent.append((user, text)))
    accounts.register("alerted", "correct-horse-battery-1", verified=True)
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "alerted",
                                    "password": "correct-horse-battery-1"},
           headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) "
                                  "Chrome/126.0 Mobile Safari/537.36"})
    for _ in range(50):
        if sent:
            break
        time.sleep(0.02)
    assert sent and sent[0][0] == "alerted"
    assert "Chrome on Android" in sent[0][1]
    assert "Sign out other devices" in sent[0][1]


def test_internal_errors_are_hidden_from_users_not_admins(app, login):
    from fastapi import HTTPException

    def boom():
        raise HTTPException(500, "sqlite3.OperationalError at /data/x.db")

    def crash():
        raise RuntimeError("secret internals")
    app.add_api_route("/api/test-boom", boom, methods=["POST"])
    app.add_api_route("/api/test-crash", crash, methods=["POST"])
    from fastapi.testclient import TestClient

    def client(name):
        # a crash is re-raised after the response is sent (so the server
        # logs it); the test only cares what the browser receives
        c = TestClient(app, raise_server_exceptions=False)
        c.cookies = login(name).cookies
        return c
    user = client("erroruser")
    for path in ("/api/test-boom", "/api/test-crash"):
        r = user.post(path)
        assert r.status_code == 500
        assert "reference" in r.json()["detail"]
        assert "sqlite3" not in r.text and "secret" not in r.text
    admin = client("admin_errors")
    assert "sqlite3.OperationalError" in admin.post("/api/test-boom").text
    assert "secret internals" in admin.post("/api/test-crash").text
    # deliberate messages still reach users unchanged
    assert user.get("/api/detail/NOPE.NS").json()["detail"] == \
        "No stored data for this symbol yet."
