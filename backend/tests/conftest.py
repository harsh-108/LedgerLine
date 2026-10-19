"""Test isolation. Everything here runs BEFORE any test imports app.main.

- The real .env is never read (it holds live Telegram/SmartAPI/mail keys).
- The database, LLM usage file, universe cache and scrip-master cache all
  live in a throwaway temp directory, never in data/.
- Outbound network is blocked at the socket level; a test that needs a
  remote payload must stub the function that fetches it.
- The app is used through TestClient WITHOUT entering its lifespan, so the
  background workers (auto-refresh, digest, Telegram poller) never start.
"""
import datetime as dt
import os
import shutil
import socket
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TMP = Path(tempfile.mkdtemp(prefix="ledgerline-tests-"))

from app.core import envutil  # noqa: E402

envutil._loaded = True                  # skip the real .env entirely
for _k in list(os.environ):
    if _k.startswith(("TELEGRAM", "SMARTAPI", "RESEND", "GROQ", "OPENROUTER",
                      "GEMINI", "GOOGLE_", "TAVILY", "APP_BASE_URL",
                      "SIGNUP_", "AUTH_DEV")):
        del os.environ[_k]

from app.core import config  # noqa: E402

config.DB_PATH = str(TMP / "test.db")
config.AUTO_REFRESH = False
config.AUTO_DIGEST = False

from app.core import llm  # noqa: E402
from app.data_sources import smartapi_source, universe  # noqa: E402

llm.USAGE_FILE = TMP / "llm_usage.json"
universe.CACHE_FILE = str(TMP / "universe_cache.json")
smartapi_source._SCRIPS_CACHE = str(TMP / "scrips_cache.json")


# ------------------------------------------------------------ no network
_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host in ("127.0.0.1", "::1", "localhost"):
        return _real_connect(self, address)
    raise RuntimeError(f"network disabled in tests (tried {address!r})")


socket.socket.connect = _guarded_connect


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)


# ------------------------------------------------------------ fixtures
BENCH = "NIFTYBEES.NS"


def _ohlc(closes, start):
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": c * 0.995, "High": c * 1.01,
                         "Low": c * 0.99, "Close": c,
                         "Volume": np.full(len(c), 100_000)}, index=idx)


def seed_prices():
    """Deterministic synthetic history: TEST.NS and PEER.NS over ~2 years
    up to a fixed date, the benchmark, and STALE.NS whose data stopped in
    2023 (so it shares no window with the others)."""
    from app.core import database as db
    rng = np.random.default_rng(7)
    n = 520
    t = np.arange(n)
    test = 100 * np.exp(0.0008 * t + 0.01 * rng.standard_normal(n).cumsum())
    peer = 50 * np.exp(0.0004 * t + 0.01 * rng.standard_normal(n).cumsum())
    bench = 200 * np.exp(0.0005 * t + 0.005 * rng.standard_normal(n).cumsum())
    start = "2023-01-02"
    db.save_prices(_ohlc(test, start), "TEST.NS", "stock")
    db.save_prices(_ohlc(peer, start), "PEER.NS", "stock")
    db.save_prices(_ohlc(bench, start), BENCH, "etf")
    db.save_prices(_ohlc(np.linspace(10, 12, 80), "2021-01-04"),
                   "STALE.NS", "stock")


@pytest.fixture(scope="session")
def app():
    from app.core import accounts
    # sign-up seeding would download starter funds/prices in a thread
    accounts._seed_starter_background = lambda *a, **k: None
    # every TestClient login comes from one "IP"; the per-user limit is
    # left alone and has its own test
    accounts.LIMITS["login_ip"] = (10_000, 900)
    from app.main import app as fastapi_app
    seed_prices()
    return fastapi_app


PASSWORD = "correct-horse-battery-1"
_clients = {}


@pytest.fixture
def login(app):
    """login("alice") -> a TestClient signed in as alice (account created
    on first use, client reused after; "admin*" names get the admin
    role)."""
    from fastapi.testclient import TestClient
    from app.core import accounts

    def _login(name):
        if name not in _clients:
            role = (accounts.ROLE_ADMIN if name.startswith("admin")
                    else accounts.ROLE_USER)
            accounts.register(name, PASSWORD, role=role, verified=True)
            c = TestClient(app)
            r = c.post("/api/auth/login", json={"username": name,
                                                "password": PASSWORD})
            assert r.status_code == 200, r.text
            _clients[name] = c
        return _clients[name]
    return _login


@pytest.fixture
def anon(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def today():
    return dt.date.today()


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Tests insert rows with raw SQL, which the data version (bumped only by
    the app's own writers) cannot see; start every test with empty caches."""
    from app.core import memo
    from app.analysis import ledger
    memo.clear()
    ledger._recorded.clear()
    yield
