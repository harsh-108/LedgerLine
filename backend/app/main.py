"""
FastAPI backend for the custom web UI.

Run (from backend/):  uvicorn app.main:app --reload --port 8000
Then open http://localhost:8000

All business logic lives in the existing modules; this file only
exposes it as JSON and serves the static frontend.
"""

import datetime
import threading
import time
from typing import Optional


from app.core import config
from app.core import paths  # noqa: F401  (re-exported settings)

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.alerts import alerts as alerts_mod
from app.analysis import analysis
from app.analysis import backtest
from app.core import database as db
from app.data_sources import downloader, symbols
from app.analysis import ml
from app.analysis import nlp
from app.data_sources import nse_source
from app.portfolio import portfolio
from app.analysis import query_engine as qe
import requests
from app.analysis import scanner
from app.data_sources import smartapi_source
from app.data_sources import universe as universe_mod
from app.analysis import research
from app.analysis import extras
from app.analysis import patterns
from app.core import auth
from app.core import llm
from app.core import memo
from app.analysis import ledger
from app.portfolio import funds

from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _lifespan(_app):
    # Background workers start with the server, not on import, so tests
    # (and scripts) can import the app without polling Telegram or
    # downloading market data. _start_background is defined at the end.
    _start_background()
    yield


app = FastAPI(title="Watchlist Tracker API", lifespan=_lifespan)
# /api/detail alone is ~1 MB of candle + indicator JSON; it compresses ~6x.
# Starlette skips text/event-stream, so streamed replies are unaffected.
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
# compresslevel 5, not Starlette's default 9: level 9 spent 102 ms on the
# ~1 MB stock payload (twice the time to build it) for a 7% smaller result;
# level 5 takes ~10 ms. On the phone that is most of a second per page.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
db.init_db()
db.ensure_v2_columns()
from app.core import accounts, auth_api          # noqa: E402
accounts.ensure_schema()
ledger.ensure_table()
funds.ensure_tables()
# pre-warm Angel One's scrip master (~10 MB) in the background so the
# add-ticker search is instant instead of stalling on first keystroke
from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

PUBLIC_PATHS = ("/login", "/signup", "/verify", "/forgot", "/reset",
                "/api/auth/login", "/api/auth/setup", "/api/auth/status",
                "/api/auth/config", "/api/auth/signup", "/api/auth/verify",
                "/api/auth/resend", "/api/auth/forgot", "/api/auth/reset",
                "/api/auth/google",
                "/static/", "/assets/", "/favicon")

# (method-or-*, path prefix) pairs only an admin may call. Enforced here,
# in one place, rather than per route. Hiding a button is not security.
# Market-data refresh (/api/refresh) and news refresh (/api/news/refresh)
# are deliberately open to every signed-in user; both refuse to start a
# second run while one is going.
ADMIN_PATHS = (
    ("*", "/api/admin/"),
    ("POST", "/api/auth/add-user"),
    ("POST", "/api/nse/sync"),
    ("POST", "/api/universe/"),
    ("*", "/api/doctor/"),
    ("POST", "/api/digest/send"),
    ("POST", "/api/news/feeds"),
    ("DELETE", "/api/news/feeds/"),
    ("POST", "/api/ipos"),
    ("DELETE", "/api/ipos/"),
)


def _is_admin_path(method, path):
    """Entries ending in "/" are prefixes; others match exactly or as a
    path segment (so /api/digest/send does not swallow .../send-mine)."""
    for m, prefix in ADMIN_PATHS:
        if m != "*" and m != method:
            continue
        if prefix.endswith("/"):
            if path.startswith(prefix) or path == prefix.rstrip("/"):
                return True
        elif path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _auth_lookup(token):
    """(username, role) for a session cookie, or (None, None)."""
    user = auth.session_user(token)
    if not user:
        return None, None
    role = (accounts.get_user(user) or {}).get("role", accounts.ROLE_USER)
    accounts.ensure_starter(user)          # first-ever watchlist, if needed
    return user, role


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if any(path == p or path.startswith(p) for p in PUBLIC_PATHS):
        return await call_next(request)
    # sqlite calls block; run them on the threadpool, not the event loop,
    # so one slow lookup does not stall every other in-flight request.
    user, role = await run_in_threadpool(_auth_lookup,
                                         request.cookies.get("session"))
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not signed in."}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = user
    request.state.role = role
    if _is_admin_path(request.method, path) and role != accounts.ROLE_ADMIN:
        return JSONResponse({"detail": "Admin only."}, status_code=403)
    token = db.current_user.set(user)          # scopes per-user tables
    try:
        return await call_next(request)
    finally:
        db.current_user.reset(token)


_SECURITY_HEADERS = {
    # no other site may frame the app (clickjacking: a hidden Ledgerline
    # under a fake button on someone else's page)
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",       # no MIME sniffing of uploads
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


# Registered after require_login, so it wraps it and also stamps the
# 401s and redirects that require_login returns itself.
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


# ---------------------------------------------------------- error hiding
# A 500 means the code broke. Its text (exception messages, file paths,
# library names) helps an attacker map the server and means nothing to a
# user, so non-admins get a short message with a reference; the details
# go to the server log under that reference. Admins still see them, so
# they can debug from the browser. Deliberate 4xx/502/503 messages
# ("No stored data for this symbol yet") are untouched.
import logging as _logging
import secrets as _secrets
from starlette.exceptions import HTTPException as _StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler as _default_http

_err_log = _logging.getLogger("ledgerline.errors")


def _is_admin_request(request):
    return getattr(request.state, "role", None) == accounts.ROLE_ADMIN


def _hidden_error(request, detail):
    ref = _secrets.token_hex(3).upper()
    _err_log.error("[ref %s] %s %s -> %s", ref, request.method,
                   request.url.path, detail)
    print(f"[error ref {ref}] {request.method} {request.url.path}: {detail}",
          flush=True)
    return JSONResponse(
        {"detail": "Something went wrong on the server. If it keeps "
                   f"happening, tell the admin the reference {ref}."},
        status_code=500)


@app.exception_handler(_StarletteHTTPException)
async def _http_errors(request: Request, exc: _StarletteHTTPException):
    if exc.status_code >= 500 and exc.status_code not in (502, 503) \
            and not _is_admin_request(request):
        return _hidden_error(request, exc.detail)
    return await _default_http(request, exc)


@app.exception_handler(Exception)
async def _crashes(request: Request, exc: Exception):
    import traceback
    detail = "".join(traceback.format_exception(exc))
    if _is_admin_request(request):
        print(detail, flush=True)
        return JSONResponse({"detail": f"{exc.__class__.__name__}: {exc}"},
                            status_code=500)
    return _hidden_error(request, detail)


def _react_index():
    """The built React app, if `npm run build` has been run."""
    index = paths.REACT_DIST / "index.html"
    return index if index.exists() else None


@app.get("/login")
@app.get("/signup")
@app.get("/verify")
@app.get("/forgot")
@app.get("/reset")
def login_page():
    # React owns these once it is built; the old page is the fallback.
    return FileResponse(_react_index() or paths.FRONTEND_DIR / "login.html",
                        headers={"Cache-Control": "no-cache"})


class CredsIn(BaseModel):
    username: str
    password: str


@app.get("/api/auth/status")
def auth_status():
    from app.core import google_auth, mailer
    return {"has_users": auth.any_users(),
            "google_client_id": google_auth.client_id(),
            "email_configured": mailer.configured(),
            "invite_required": auth_api.signup_requires_invite(),
            "google_invite_required": auth_api.google_requires_invite()}


def _session_response(username, request=None):
    return auth_api._session_response(username, request=request)


@app.post("/api/auth/setup")
def auth_setup(c: CredsIn):
    if auth.any_users():
        raise HTTPException(403, "Accounts already exist — sign in instead.")
    try:
        user = accounts.register(c.username, c.password,
                                 role=accounts.ROLE_ADMIN, verified=True)
        accounts.ensure_schema()            # assigns pre-existing rows
        db.claim_orphan_owned_rows(user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _session_response(user)


@app.post("/api/auth/login")
def auth_login(c: CredsIn, request: Request):
    ip = auth_api._ip(request)
    uname = c.username.strip().lower()
    if accounts.rate_limited("login_ip", ip) or \
            accounts.rate_limited("login_user", uname):
        raise HTTPException(429, "Too many attempts. Wait a few minutes "
                                 "and try again.")
    if not auth.verify(uname, c.password):
        raise HTTPException(401, "Wrong username or password.")
    u = accounts.get_user(uname) or {}
    if u.get("email") and not u.get("email_verified"):
        raise HTTPException(403, "Confirm your email first — check your "
                                 "inbox, or request a new link.")
    accounts.rate_clear("login_user", uname)
    return _session_response(uname, request)


@app.post("/api/auth/add-user")
def auth_add_user(c: CredsIn, request: Request):
    # admin only (enforced by ADMIN_PATHS); no email needed, verified
    try:
        user = accounts.register(c.username, c.password,
                                 role=accounts.ROLE_USER, verified=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "user": user}


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    auth.end_session(request.cookies.get("session"))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.post("/api/auth/logout-others")
def auth_logout_others(request: Request):
    """Sign this account out of every other browser and device (a lost
    phone, a shared computer); this one stays signed in."""
    n = auth.end_all_sessions(request.state.user,
                              except_token=request.cookies.get("session"))
    return {"ok": True, "ended": n}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = getattr(request.state, "user", None)
    u = accounts.get_user(user) or {}
    used, limit = accounts.analyst_quota(user) if user else (0, None)
    tg = accounts.telegram_chat_for(user) if user else None
    return {"user": user, "role": u.get("role", "user"),
            "email": u.get("email"), "email_verified": u.get("email_verified"),
            "has_google": u.get("has_google"),
            "analyst": {"used": used, "limit": limit},
            "telegram_linked": bool(tg),
            "sessions": auth.session_count(user) if user else 0}


def _warm_scrips():
    try:
        smartapi_source.search_names("warmup")
    except Exception:
        pass   # search endpoint reports its own errors when used



def to_records(df):
    """DataFrame -> JSON-safe records (NaN/inf -> null)."""
    import numpy as np
    clean = df.replace([np.inf, -np.inf], np.nan)
    clean = clean.astype(object).where(clean.notna(), None)
    return clean.to_dict(orient="records")

# ---------------------------------------------------------------- refresh
REFRESH = {"running": False, "log": [], "done": False}


def _do_refresh():
    REFRESH.update(running=True, done=False, log=[])
    try:
        downloader.run_all(progress=lambda m: REFRESH["log"].append(str(m)),
                           sleep=0.4)
        # held stocks are not always on a watchlist: price them too
        try:
            portfolio.repair_holding_prices(
                progress=lambda m: REFRESH["log"].append(str(m)))
        except Exception as e:
            REFRESH["log"].append(f"[repair] skipped: {e}")
        scanner.scan_all(log_to_journal=True)
        fired = alerts_mod.check_all()
        REFRESH["log"].extend(fired)
        # scorecard: grade calls whose horizon has passed, then record
        # today's verdict + checklist for every stock (idempotent per day)
        try:
            n = ledger.resolve_pending()
            REFRESH["log"].append(f"[ledger] {n} predictions graded")
            ledger.snapshot_all(progress=lambda m: REFRESH["log"].append(m))
        except Exception as e:
            REFRESH["log"].append(f"[ledger] skipped: {e}")
        # news + calendar ride along with every refresh; failures are logged,
        # never fatal (free sources come and go)
        try:
            from app.feeds import news as _news, events_calendar as _cal
            _news.refresh(progress=lambda m: REFRESH["log"].append(str(m)))
            _cal.refresh_events(progress=lambda m: REFRESH["log"].append(str(m)))
        except Exception as e:
            REFRESH["log"].append(f"[feeds] skipped: {e}")
    except Exception as e:
        REFRESH["log"].append(f"[FATAL] {e}")
    REFRESH.update(running=False, done=True)
    # fresh prices just invalidated every cached page: rebuild the common
    # ones now, in this background thread, rather than on the next click
    try:
        _warm_caches()
    except Exception:
        pass


@app.post("/api/refresh")
def start_refresh():
    if REFRESH["running"]:
        return {"status": "already_running"}
    threading.Thread(target=_do_refresh, daemon=True).start()
    return {"status": "started"}


@app.get("/api/refresh/status")
def refresh_status():
    return {"running": REFRESH["running"], "done": REFRESH["done"],
            "log": REFRESH["log"][-12:]}


NSE_SYNC = {"running": False, "log": [], "result": None}


def _do_nse_sync():
    NSE_SYNC.update(running=True, log=[], result=None)
    res = nse_source.sync(progress=lambda m: NSE_SYNC["log"].append(str(m)))
    NSE_SYNC.update(running=False, result=res)


@app.post("/api/nse/sync")
def nse_sync():
    if not nse_source.available():
        raise HTTPException(400, "nsepython not installed — "
                                 "pip install nsepython, then restart.")
    if NSE_SYNC["running"]:
        return {"status": "already_running"}
    threading.Thread(target=_do_nse_sync, daemon=True).start()
    return {"status": "started"}


@app.get("/api/nse/status")
def nse_status():
    return {"running": NSE_SYNC["running"], "log": NSE_SYNC["log"][-10:],
            "result": NSE_SYNC["result"],
            "available": nse_source.available()}


# --------------------------------------------------------------- watchlist
@app.get("/api/symbol-search")
def symbol_search(q: str):
    """Autocomplete for the add-ticker box. Shared resolver in
    data_sources/symbols.py (also used by the analyst's find_symbol tool)."""
    return symbols.search(q)


@app.get("/api/financials/{symbol}")
def financials(symbol: str, force: bool = False):
    try:
        data = research.statements(symbol, force=force)
    except Exception as e:
        raise HTTPException(502, f"Statement fetch failed: {e}")
    if not data:
        raise HTTPException(404, "Yahoo has no financial statements for "
                                 "this listing (common for small caps and "
                                 "BSE-only scrips).")
    return data


@app.get("/api/patterns/{symbol}")
def stock_patterns(symbol: str):
    from app.analysis import charts as ch
    df = ch.load_stock_df(symbol)
    r = patterns.detect(df)
    if not r:
        raise HTTPException(404, "Not enough history for pattern analysis.")
    return r


@app.get("/api/peers/{symbol}")
def peers(symbol: str):
    p = research.peers(symbol)
    if not p:
        raise HTTPException(404, "No sector peers with stored fundamentals "
                                 "yet — a wider screener universe adds more.")
    return p


_events_cache = {}           # symbol -> (fetched_at, data)
_EVENTS_TTL = 6 * 3600      # earnings dates / dividends move slowly


@app.get("/api/events/{symbol}")
def stock_events(symbol: str):
    """Three live Yahoo calls; cached so reopening a stock is instant."""
    hit = _events_cache.get(symbol)
    if hit and time.time() - hit[0] < _EVENTS_TTL:
        return hit[1]
    try:
        data = research.events(symbol)
    except Exception as e:
        raise HTTPException(502, f"Events fetch failed: {e}")
    _events_cache[symbol] = (time.time(), data)
    return data


@app.get("/api/delivery/{symbol}")
def delivery(symbol: str):
    base = symbol.split(".")[0]
    rows = db.delivery_series(base)
    if not rows:
        raise HTTPException(404, "No delivery data stored — run NSE sync "
                                 "first (needs nsepython).")
    return {"symbol": symbol,
            "series": [{"time": d, "value": p} for d, p in rows if p]}


@app.get("/api/depth/{symbol}")
def depth(symbol: str):
    if not smartapi_source.configured():
        raise HTTPException(400, "SmartAPI credentials not configured.")
    try:
        d = smartapi_source.quote_depth(symbol)
    except Exception as e:
        raise HTTPException(502, f"Depth fetch failed: {e}")
    if not d:
        raise HTTPException(404, "No depth returned for this symbol.")
    return d


class AlertIn(BaseModel):
    symbol: str
    kind: str
    value: float = 0


@app.get("/api/alerts")
def alerts_list():
    return {"kinds": alerts_mod.ALERT_KINDS,
            "alerts": [{"id": a, "symbol": s, "kind": k, "value": v,
                        "active": bool(act)}
                       for (a, s, k, v, act) in db.get_alerts(False)]}


@app.post("/api/alerts")
def alerts_add(a: AlertIn):
    if a.kind not in alerts_mod.ALERT_KINDS:
        raise HTTPException(400, "Unknown alert kind.")
    db.add_alert(a.symbol, a.kind, a.value)
    return {"ok": True}


@app.delete("/api/alerts/{alert_id}")
def alerts_delete(alert_id: int):
    db.remove_alert(alert_id)
    return {"ok": True}


def _require_iso_date(value, what):
    """Dates are stored as text and parsed later by P&L and tax code, so a
    malformed one would break those pages for good. Reject it up front."""
    import datetime as _dt
    try:
        _dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what} must be YYYY-MM-DD.")


class SellIn(BaseModel):
    lot_id: int
    qty: float
    price: float
    date: str


@app.post("/api/sell")
def sell(s: SellIn, request: Request):
    user = request.state.user
    lot = db.get_holding(s.lot_id, user)
    if not lot:
        raise HTTPException(404, "Lot not found.")
    _id, symbol, qty, buy_price, buy_date, _thesis = lot
    if s.qty <= 0 or s.qty > qty + 1e-9:
        raise HTTPException(400, f"Quantity must be between 0 and {qty}.")
    if s.price <= 0:
        raise HTTPException(400, "Sell price must be positive.")
    _require_iso_date(s.date, "Sell date")
    if buy_date and s.date < buy_date[:10]:
        raise HTTPException(400, f"Sell date is before the buy date "
                                 f"({buy_date[:10]}).")
    db.add_sell(symbol, s.qty, buy_price, buy_date, s.price, s.date, user)
    remaining = qty - s.qty
    if remaining > 1e-9:
        db.update_holding_qty(s.lot_id, remaining)
    else:
        db.remove_holding(s.lot_id)
    return {"ok": True, "remaining": round(remaining, 4)}


class ShareholdingIn(BaseModel):
    symbol: str
    quarter: str
    promoter: float | None = None
    pledged: float | None = None
    fii: float | None = None
    dii: float | None = None


@app.get("/api/shareholding/{symbol}")
def shareholding(symbol: str):
    r = extras.shareholding_report(symbol)
    if not r:
        raise HTTPException(404, "No quarters recorded yet for this stock.")
    return r


@app.post("/api/shareholding")
def shareholding_add(x: ShareholdingIn):
    import re as _re
    if not _re.fullmatch(r"20\d\d-Q[1-4]", x.quarter):
        raise HTTPException(400, "Quarter must look like 2026-Q1.")
    db.save_shareholding(x.symbol, x.quarter, x.promoter, x.pledged,
                         x.fii, x.dii)
    return {"ok": True}


@app.delete("/api/shareholding/{symbol}/{quarter}")
def shareholding_del(symbol: str, quarter: str):
    db.delete_shareholding(symbol, quarter)
    return {"ok": True}


@app.get("/api/option-sentiment/{symbol}")
def option_sentiment(symbol: str):
    try:
        return extras.option_sentiment(symbol)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/home")
def home(request: Request):
    """Overview for the home screen: market pulse, portfolio snapshot,
    latest journal entries."""
    # This user's watchlist only, one row per company: the same stock
    # listed as .NS and .BO (or kept by several users) must not show up
    # twice or be counted twice.
    seen, moves = set(), []
    for m in sorted(db.latest_moves(all_users=False),
                    key=lambda m: -abs(m[3] or 0)):
        base = m[0].split(".")[0]
        if m[3] is None or base in seen:
            continue
        seen.add(base)
        moves.append(m)
    adv = sum(1 for m in moves if m[3] > 0)
    dec = sum(1 for m in moves if m[3] < 0)
    movers = moves[:6]
    _val, totals = portfolio.valuation(request.state.user)
    # Journal and signal count follow the same rule as /api/journal: an
    # admin sees everything, everyone else only their own stocks. A new
    # account must not open on other people's signals.
    syms = None
    if getattr(request.state, "role", "user") != accounts.ROLE_ADMIN:
        syms = db.watchlist_symbols(request.state.user)
    journal = [{"created": c, "symbol": sym, "signal": sig, "price": p}
               for (c, sym, sig, p, _a, _r) in db.get_journal(6, syms)]
    # earnings on THIS user's watchlist stocks within the next 7 days. The
    # fundamentals table is shared (every user's stocks plus prepared index
    # universes), so filter it, and list each company once.
    import datetime as _dt
    today = _dt.date.today()
    week = today + _dt.timedelta(days=7)
    mine = set(db.watchlist_symbols(request.state.user))
    earnings, listed = [], set()
    for sym, f in db.all_fundamentals().items():
        if sym not in mine or sym.split(".")[0] in listed:
            continue
        ne = (f or {}).get("nextEarnings")
        if not ne:
            continue
        try:
            nd = _dt.date.fromisoformat(str(ne)[:10])
        except ValueError:
            continue
        if today <= nd <= week:
            listed.add(sym.split(".")[0])
            earnings.append({"symbol": sym.split(".")[0],
                             "date": nd.isoformat()})
    earnings.sort(key=lambda e: e["date"])
    return {
        "earnings_week": earnings[:8],
        "data_through": db.last_price_date(),
        "advancing": adv, "declining": dec,
        "movers": [{"symbol": m[0].split(".")[0], "last": m[2], "pct": m[3]}
                   for m in movers],
        "signals_today": db.today_signal_count(syms),
        "portfolio": totals or None,
        "journal": journal,
    }


@app.get("/api/tape")
def tape(request: Request):
    """Ticker-tape items: portfolio holdings first (marked held),
    then remaining watchlist stocks/ETFs. MFs excluded — daily NAVs
    don't belong on an intraday-style tape."""
    moves = {m[0]: (m[2], m[3]) for m in db.latest_moves()}
    held, seen, items = [], set(), []
    for _hid, symbol, _q, _bp, _bd, _th in db.get_holdings(request.state.user):
        if symbol in seen:
            continue
        seen.add(symbol)
        last, pct = moves.get(symbol, (db.last_close(symbol), None))
        items.append({"label": symbol.split(".")[0], "symbol": symbol,
                      "last": last, "pct": pct, "held": True})
    for (_iid, atype, symbol, _s, _label, _a) in db.get_watchlist():
        if atype == "mf" or symbol in seen:
            continue
        seen.add(symbol)
        last, pct = moves.get(symbol, (None, None))
        items.append({"label": symbol.split(".")[0], "symbol": symbol,
                      "last": last, "pct": pct, "held": False})
    return {"items": [i for i in items if i["last"] is not None]}


@app.get("/api/watchlist")
def watchlist():
    moves = {m[0]: (m[2], m[3]) for m in db.latest_moves()}
    tags = db.get_tag_map()
    wl = db.get_watchlist()
    sources = db.sources_for(s for (_i, at, s, _sc, _l, _a) in wl
                             if at != "mf" and s)
    fund_map = db.all_fundamentals()
    out = []
    for (iid, atype, symbol, scheme, label, _a) in wl:
        if atype == "mf":
            spark = db.recent_navs(int(scheme))
            last = spark[-1] if spark else None
            pct = ((spark[-1] / spark[-2] - 1) * 100
                   if len(spark) > 1 else None)
        else:
            spark = db.recent_closes(symbol)
            last, pct = moves.get(symbol, (None, None))
            if last is None and spark:
                last = spark[-1]
        out.append({"id": iid, "type": atype, "symbol": symbol,
                    "scheme_code": scheme, "label": label,
                    "tag": tags.get(iid), "spark": spark,
                    "last": last, "pct": pct,
                    "mcap": (fund_map.get(symbol, {}) or {}).get("marketCap"),
                    "source": sources.get(symbol)})
    return {"items": out, "last_date": db.last_price_date(),
            "signals_today": db.today_signal_count()}


class AddTicker(BaseModel):
    symbol: str
    asset_type: str = "stock"


@app.post("/api/watchlist/add")
def add_ticker(body: AddTicker):
    ok, resolved, msg = downloader.resolve_and_validate(body.symbol.upper())
    if not ok:
        raise HTTPException(400, msg)
    db.add_ticker(resolved, body.asset_type)
    n = downloader.download_one(symbol=resolved, asset_type=body.asset_type,
                                progress=lambda m: None)
    return {"symbol": resolved, "rows": n, "message": msg}


@app.delete("/api/watchlist/{item_id}")
def remove_item(item_id: int):
    db.remove_watchlist_item(item_id)
    return {"ok": True}


@app.post("/api/download/{symbol}")
def download_symbol(symbol: str):
    """Fetch history for ONE symbol. If the stored listing comes back
    shallow (Yahoo's .BO coverage is patchy), automatically try the same
    company's other exchange (.BO <-> .NS) and keep whichever listing has
    real history — repointing the watchlist entry when the swap wins."""
    symbol = symbol.upper()
    asset_type = "stock"
    for (_id, at, sym, _sc, _label, _a) in db.get_watchlist():
        if sym == symbol:
            asset_type = at
            break

    downloader.download_one(symbol=symbol, asset_type=asset_type,
                            progress=lambda m: None)
    best_sym, best_rows = symbol, db.stored_rows(symbol)

    # Shallow? Try the sister listing on the other exchange.
    swapped = False
    if best_rows < 30 and (symbol.endswith(".NS") or symbol.endswith(".BO")):
        base, suf = symbol.rsplit(".", 1)
        alt = f"{base}.{'BO' if suf == 'NS' else 'NS'}"
        try:
            downloader.download_ticker(alt, asset_type,
                                       progress=lambda m: None)
        except Exception:
            pass
        alt_rows = db.stored_rows(alt)
        if alt_rows > best_rows:
            swapped = db.repoint_watchlist_symbol(symbol, alt)
            best_sym, best_rows = alt, alt_rows

    if best_rows == 0:
        from app.data_sources import smartapi_source
        extra = ("SmartAPI fallback also returned nothing."
                 if smartapi_source.configured() else
                 "SmartAPI fallback is NOT configured — adding the four "
                 "SMARTAPI_* keys to .env gives a second data source for "
                 "symbols Yahoo doesn't cover (run check_smartapi.py to "
                 "verify).")
        raise HTTPException(
            502, "Neither NSE nor BSE listing returned rows from Yahoo. "
                 + extra)

    shallow = best_rows < 30
    note = ""
    if shallow:
        from app.data_sources import smartapi_source
        note = (f"Yahoo only has {best_rows} rows for this listing "
                "(charts need 30+). "
                + ("SmartAPI also came up short."
                   if smartapi_source.configured() else
                   "Configure the four SMARTAPI_* keys in .env to pull "
                   "exchange history from Angel One instead — run "
                   "check_smartapi.py to verify the setup."))
    return {"rows": best_rows, "symbol": best_sym,
            "swapped": swapped, "shallow": shallow, "note": note}


class TagBody(BaseModel):
    tag: str = ""


@app.post("/api/watchlist/{item_id}/tag")
def set_tag(item_id: int, body: TagBody):
    db.set_tag(item_id, body.tag.strip() or None)
    return {"ok": True}


class ReorderBody(BaseModel):
    ids: list[int]


@app.post("/api/watchlist/reorder")
def reorder_watchlist(body: ReorderBody):
    db.set_watchlist_order(body.ids)
    return {"ok": True}


@app.get("/api/digest")
def digest_preview(request: Request):
    """The weekly Telegram digest, rendered in-app on demand. This only
    BUILDS the text; POST /api/digest/send delivers it."""
    try:
        from app.analysis import digest as dg
        from app.alerts import notify
        return {"text": dg.build_digest(request.state.user),
                "telegram_configured": notify.bot_configured(),
                "telegram_linked": bool(accounts.telegram_chat_for(
                    request.state.user)) or notify.configured(),
                "last_sent": dg.last_sent()}
    except Exception as e:
        raise HTTPException(500, f"Digest failed: {e}")


@app.post("/api/digest/send")
def digest_send():
    """Admin: send every linked user their digest now."""
    try:
        from app.analysis import digest as dg
        res = dg.send_digest()
    except Exception as e:
        raise HTTPException(500, f"Digest failed: {e}")
    if not res["ok"]:
        raise HTTPException(503, res["error"] or "send failed")
    return {"ok": True, "sent_at": res["sent_at"], "text": res["text"],
            "recipients": res.get("recipients")}


@app.post("/api/digest/send-mine")
def digest_send_mine(request: Request):
    """Any user: send my own digest to my linked Telegram."""
    from app.analysis import digest as dg
    res = dg.send_digest(request.state.user)
    if not res["ok"]:
        raise HTTPException(503, res["error"] or "send failed")
    return {"ok": True, "sent_at": res["sent_at"]}


# ------------------------------------------------------------------ detail
def _nullable(values):
    """floats with NaN -> None (JSON null), for columns that start late."""
    return [None if v != v else v for v in values]


@memo.memoize("detail_core", share=True, max_items=40)
def _detail_core(symbol):
    """Everything on the stock page that depends only on the stored prices:
    the chart series, stats and base rates. Kept until the data changes, so
    reopening a stock costs a lookup, not a rebuild.

    The series go out as COLUMNS: one date list plus one number list per
    line. The old shape repeated every date in every one of 13 series (~1 MB
    per stock, 80% of it lines that are hidden by default); this is about a
    quarter of that. frontend lib/detail.ts rebuilds the old shape."""
    from app.analysis import charts as ch
    from app.analysis import base_rates as br
    df = ch.load_stock_df(symbol)
    if df is None or len(df) < 30:
        return None
    close = df["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    mid = close.rolling(20).mean()
    sd = close.rolling(20).std()
    macd_line = (close.ewm(span=12, adjust=False).mean()
                 - close.ewm(span=26, adjust=False).mean())
    macd_sig = macd_line.ewm(span=9, adjust=False).mean()

    def col(sr, r=2):
        return _nullable(sr.astype(float).round(r).tolist())

    series = {
        "time": df.index.strftime("%Y-%m-%d").tolist(),
        "open": col(df["open"]), "high": col(df["high"]),
        "low": col(df["low"]), "close": col(close),
        "volume": [None if v != v else int(v) for v in df["volume"].tolist()],
        # green/red volume bars, from the exact prices: comparing the
        # rounded open and close flipped bars on near-flat days
        "up": [1 if c >= o else 0 for o, c in
               zip(df["open"].tolist(), close.tolist())],
        "sma_fast": col(df["sma_fast"]), "sma_slow": col(df["sma_slow"]),
        "rsi": col(df["rsi"]),
        "ema20": col(ema20), "bb_upper": col(mid + 2 * sd),
        "bb_lower": col(mid - 2 * sd),
        "macd": col(macd_line, 3), "macd_signal": col(macd_sig, 3),
    }
    stats = ch.stock_stats(df)
    if db.symbol_source(symbol) == "smartapi":
        stats["Data source"] = "SmartAPI (raw)"
    # kept as JSON text: ~0.3 MB instead of ~1.5 MB of Python objects per
    # stock (the phone has little memory), and each request only splices it
    import json as _json
    return {"series_json": _json.dumps(series, allow_nan=False),
            "stats": stats, "base_rates": br.base_rates(df)}


@app.get("/api/detail/{symbol}")
def detail(symbol: str, request: Request):
    core = _detail_core(symbol)
    if core is None:
        raise HTTPException(404, "No stored data for this symbol yet.")
    fund, updated = db.get_fundamentals(symbol)
    ck = analysis.checklist(symbol)
    if ck:
        ledger.record(symbol, "checklist", ck["tier"], ck["passed"],
                      {"passed": ck["passed"], "applicable": ck["applicable"]})
    # position: is this symbol held? give the facts a hold/sell decision
    # actually needs — cost basis, holding period, and what the index did
    # with the same money over the same time.
    position = None
    lots = [(hid, q, bp, bd)
            for (hid, sym_, q, bp, bd, _th) in db.get_holdings(request.state.user)
            if sym_ == symbol]
    if lots:
        qty = sum(q for _h, q, _b, _d in lots)
        invested = sum(q * bp for _h, q, bp, _d in lots)
        avg = invested / qty if qty else 0
        last = db.last_close(symbol) or 0
        first_buy = min((d for _h, _q, _b, d in lots if d), default=None)
        divs = sum(a for (_i, sym_, a, _d, _n)
                   in db.get_dividends(request.state.user)
                   if sym_ == symbol)
        position = {
            "lots": [{"id": hid_, "qty": q, "buy_price": bp,
                      "buy_date": bd}
                     for (hid_, q, bp, bd) in lots],
            "qty": qty, "avg_cost": round(avg, 2),
            "invested": round(invested, 2),
            "current": round(qty * last, 2),
            "pnl": round(qty * last - invested, 2),
            "pnl_pct": round((qty * last / invested - 1) * 100, 2)
            if invested else 0,
            "dividends": round(divs, 2),
        }
        if first_buy:
            import datetime as _dt
            days = (_dt.date.today()
                    - _dt.date.fromisoformat(first_buy)).days
            position["first_buy"] = first_buy
            position["holding_days"] = days
            position["ltcg_eligible"] = portfolio.is_long_term(
                _dt.date.fromisoformat(first_buy), _dt.date.today())
            # stock vs index since first buy
            closes = {c[0]: c[1] for c in db.load_closes(symbol)}
            bm = db.load_closes(portfolio.BENCHMARK)
            start_px = next((v for k, v in sorted(closes.items())
                             if k >= first_buy), None)
            bm_after = [(k, v) for k, v in bm if k >= first_buy]
            if start_px and bm_after and last:
                position["stock_ret_since"] = round(
                    (last / start_px - 1) * 100, 1)
                position["index_ret_since"] = round(
                    (bm_after[-1][1] / bm_after[0][1] - 1) * 100, 1)
    # The small parts are encoded here; the big cached series is already
    # JSON text and is spliced in as is (the cached core is shared and
    # read-only: nothing here modifies it).
    import json as _json
    from fastapi.responses import Response
    head = _json.dumps({
        "format": 2,
        "symbol": symbol,
        "stats": core["stats"],
        "base_rates": core["base_rates"],
        "position": position,
        "fundamentals": fund, "fundamentals_updated": updated,
        "checklist": ck,
        "delivery": db.latest_delivery(symbol.split(".")[0]),
    }, allow_nan=False, default=str)
    body = head[:-1] + ', "series": ' + core["series_json"] + "}"
    return Response(body, media_type="application/json")


# ------------------------------------------------------------- funds page
@app.get("/api/funds")
def funds_overview(request: Request):
    try:
        return funds.overview(request.state.user)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Funds page failed: {e.__class__.__name__}"
                                 f": {e} — full traceback is in the uvicorn "
                                 "terminal.")


@app.get("/api/mf/search")
def mf_search(q: str):
    try:
        return {"results": funds.search(q)}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class MfAdd(BaseModel):
    scheme_code: int
    label: str = ""


@app.post("/api/mf/add")
def mf_add(body: MfAdd):
    n, name = funds.add(body.scheme_code, body.label or None)
    if n == 0:
        return {"ok": True, "rows": 0, "name": name,
                "note": "Added, but mfapi.in returned no NAVs right now — "
                        "run Refresh data later to fill the history."}
    return {"ok": True, "rows": n, "name": name}


class MfHoldingIn(BaseModel):
    scheme_code: int
    units: float
    buy_nav: float
    buy_date: str = None


@app.get("/api/mf/holdings")
def mf_holdings(request: Request):
    return {"holdings": [
        {"id": hid, "scheme_code": code, "units": u, "buy_nav": bn,
         "buy_date": bd} for (hid, code, u, bn, bd)
        in funds.get_holdings(request.state.user)]}


@app.post("/api/mf/holdings")
def mf_holding_add(h: MfHoldingIn, request: Request):
    if h.units <= 0 or h.buy_nav <= 0:
        raise HTTPException(400, "Units and buy NAV must be positive.")
    funds.add_holding(h.scheme_code, h.units, h.buy_nav, h.buy_date,
                      request.state.user)
    return {"ok": True}


@app.delete("/api/mf/holdings/{hid}")
def mf_holding_del(hid: int, request: Request):
    funds.remove_holding(hid, request.state.user)
    return {"ok": True}


@app.get("/api/mf/{scheme_code}")
def mf_detail(scheme_code: int, request: Request):
    from app.analysis import charts as ch
    nav = ch.load_mf_series(scheme_code)
    if nav is None or len(nav) < 30:
        raise HTTPException(404, "No NAV history for this fund yet.")
    st = funds.fund_stats(scheme_code) or {}
    ov = next((f for f in funds.overview(request.state.user)["funds"]
               if f["scheme_code"] == scheme_code), {})
    return {
        "stats": ch.mf_stats(nav),
        "detail": st,
        "position": ov.get("position"),
        "holdings": ov.get("holdings", []),
        "sips": ov.get("sips", []),
        "vs_index_1y": ov.get("vs_index_1y"),
        "nav": [{"time": i.strftime("%Y-%m-%d"), "value": round(v, 2)}
                for i, v in nav.items()],
    }


# ---------------------------------------------------------------- screener
@app.get("/api/query")
def query(q: str, universe: str = "watchlist"):
    try:
        syms = universe_mod.symbols_for_query(universe)
        metrics = qe.build_metrics(syms)
        result, expl, diag = qe.run_query(q, metrics)
        return {"query": q, "explanation": expl, "universe": universe,
                "rows": to_records(result), "diagnostics": diag}
    except qe.QueryError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


UNIVERSE_JOB = {"running": False, "name": None, "log": []}


def _do_prepare(name):
    UNIVERSE_JOB.update(running=True, name=name, log=[])
    try:
        universe_mod.prepare(
            name, progress=lambda m: UNIVERSE_JOB["log"].append(str(m)))
    except Exception as e:
        UNIVERSE_JOB["log"].append(f"[ERROR] {e}")
    UNIVERSE_JOB["running"] = False


@app.get("/api/universes")
def universes():
    out = []
    for name in universe_mod.NAMES:
        try:
            out.append(universe_mod.status(name))
        except RuntimeError as e:
            out.append({"name": name, "error": str(e)})
    return {"universes": out, "preparing": UNIVERSE_JOB["running"]}


@app.post("/api/universe/{name}/prepare")
def universe_prepare(name: str):
    if name not in universe_mod.NAMES or name == "watchlist":
        raise HTTPException(400, "Unknown universe.")
    if UNIVERSE_JOB["running"]:
        return {"status": "already_running"}
    threading.Thread(target=_do_prepare, args=(name,), daemon=True).start()
    return {"status": "started"}


@app.get("/api/universe/status")
def universe_job_status():
    return {"running": UNIVERSE_JOB["running"], "name": UNIVERSE_JOB["name"],
            "log": UNIVERSE_JOB["log"][-10:]}


@app.get("/api/nlq")
def natural_query(text: str):
    """Translate English -> query language ONLY. The client then runs the
    generated query through /api/query, so the selected universe and the
    zero-result diagnostics apply to English queries too."""
    if not nlp.available():
        raise HTTPException(400, llm.setup_hint())
    gen_query, err = nlp.translate(text)
    if err:
        raise HTTPException(400, err)
    if not gen_query or gen_query == "NOT_A_QUERY":
        raise HTTPException(400, "That didn't parse as a screening request "
                                 "— try describing filters, e.g. "
                                 "'profitable stocks under book value'.")
    return {"generated_query": gen_query}


# ------------------------------------------------------------------ AI lab
@app.get("/api/rankings")
def rankings():
    ranks, weights = ml.rank_watchlist()
    return {"weights": weights, "rows": to_records(ranks)}


@app.get("/api/predict/{symbol}")
def predict(symbol: str):
    res = ml.predict(symbol)
    if res is None:
        raise HTTPException(400, "Not enough history for this stock.")
    kind, msg = ml.verdict(res)
    res.pop("importances_raw", None)
    ledger.record(symbol, "ml_nextday",
                  "up" if res["prob_up"] >= 0.5 else "down",
                  round(res["prob_up"], 4),
                  {"model_edge": round(res["edge"], 4), "verdict": kind})
    return {**res, "verdict": kind, "verdict_text": msg}


@app.get("/api/eligible")
def eligible():
    elig, excl = ml.eligible_stocks()
    return {"eligible": [{"symbol": r[2], "label": r[4]} for r in elig],
            "excluded": len(excl)}


# ---------------------------------------------------------------- backtest
@app.get("/api/strategies")
def strategies():
    return {"strategies": [
        {"key": k, "label": v["label"], "desc": v["desc"]}
        for k, v in backtest.STRATEGIES.items()]}


@app.get("/api/backtest-all/{symbol}")
def backtest_all(symbol: str, request: Request, cost: float = 0.20):
    rows = backtest.compare_all(symbol, cost_per_side_pct=cost)
    if not rows:
        raise HTTPException(400, "Not enough history to backtest.")
    held = any(h[1] == symbol for h in db.get_holdings(request.state.user))
    return {"symbol": symbol, "rows": rows, "held": held}


@app.get("/api/backtest/{symbol}")
def run_backtest(symbol: str, cost: float = 0.20,
                 strategy: str = "golden_cross"):
    payload = _backtest_payload(symbol, cost, strategy)
    if payload is None:
        raise HTTPException(400, "Not enough usable history.")
    # a 2,500-point curve: skip FastAPI's per-value jsonable_encoder walk
    return JSONResponse(payload)


@memo.memoize("backtest_payload", share=True, max_items=30)
def _backtest_payload(symbol, cost, strategy):
    """The response for one backtest, kept until the data changes. The
    curve is built column-wise (iterrows over every day was the cost)."""
    res = backtest.run(symbol, cost_per_side_pct=cost, strategy=strategy)
    if res is None:
        return None
    cv = res["curves"]
    curves = [{"time": t, "strategy": s, "hold": h} for t, s, h in zip(
        cv.index.strftime("%Y-%m-%d").tolist(),
        cv["strat_curve"].astype(float).round(4).tolist(),
        cv["hold_curve"].astype(float).round(4).tolist())]
    return {"symbol": res["symbol"], "years": res["years"],
            "now": res["now"],
            "strategy_key": res["strategy_key"],
            "strategy_label": res["strategy_label"],
            "strategy_desc": res["strategy_desc"],
            "strategy": res["strategy"], "buy_hold": res["buy_hold"],
            "n_trades": res["n_trades"], "win_rate": res["win_rate"],
            "summary": backtest.summary_text(res), "curves": curves,
            "trades": res["trades"].astype(str).to_dict(orient="records")}


# --------------------------------------------------------------- portfolio
@app.get("/api/verdict/{symbol}")
def verdict_route(symbol: str):
    from app.analysis import verdict
    out = verdict.compose(symbol.upper())
    out["track_record"] = ledger.track_record(symbol.upper())
    return out


# --------------------------------------------------------------- scorecard
@app.get("/api/scorecard")
def scorecard(symbol: str = None, kind: str = None, status: str = None,
              limit: int = 300, tracked_only: bool = True):
    """The app's own track record. Grades whatever is gradeable first,
    so the numbers are never staler than the price data."""
    try:
        # a call becomes gradeable only when new prices arrive, so grading
        # runs once per data change, not on every view (Home loads this too)
        memo.cached(("resolve_pending",), ledger.resolve_pending)
    except Exception:
        pass
    tracked = ledger.tracked()
    tsyms = [t["symbol"] for t in tracked]
    only = tsyms if (tracked_only and tsyms) else None
    return {"tracked": tracked,
            "summary": ledger.summary(symbols=only),
            "rows": ledger.rows(symbol=symbol.upper() if symbol else None,
                                kind=kind, status=status,
                                limit=max(1, min(limit, 1000)),
                                symbols=only),
            "rules": {
                "strong/up": "A strong, up or holding call is right if the "
                             "stock rose over its horizon.",
                "weak/down": "A weak, down or out-of-the-stock call is right "
                             "if it fell.",
                "mixed": "Mixed calls make no claim, so they are kept but "
                         "not scored.",
                "beat_index": "Against NIFTYBEES compares the stock's return "
                              "with the index over the same days.",
                "horizons": "Horizons: 1 = the next trading day, otherwise "
                            "calendar days."}}


SNAPSHOTS = {}          # username -> {"running", "log", "done"}


def _do_snapshot(user):
    st = SNAPSHOTS[user]
    try:
        ledger.resolve_pending()
        ledger.snapshot_all(progress=lambda m: st["log"].append(m),
                            users=[user])
    except Exception as e:
        st["log"].append(f"[ledger] {e}")
    st.update(running=False, done=True)


@app.post("/api/scorecard/snapshot")
def scorecard_snapshot(request: Request):
    """Record today's verdict + checklist now for the caller's tracked
    stocks (also happens automatically after each data refresh)."""
    user = request.state.user
    st = SNAPSHOTS.setdefault(user, {"running": False, "log": [],
                                     "done": False})
    if st["running"]:
        return {"started": False, "running": True}
    st.update(running=True, done=False, log=[])
    threading.Thread(target=_do_snapshot, args=(user,), daemon=True).start()
    return {"started": True}


@app.get("/api/scorecard/snapshot/status")
def scorecard_snapshot_status(request: Request):
    return SNAPSHOTS.get(request.state.user,
                         {"running": False, "log": [], "done": False})


class TrackIn(BaseModel):
    symbols: list = []
    # manual | watchlist | portfolio | backtest | ai_lab | analyst
    source: str = "manual"
    days: Optional[int] = None   # tracking period; None/0 = until stopped


class TrackDaysIn(BaseModel):
    days: Optional[int] = None


class RuleTrackIn(BaseModel):
    symbol: str
    strategy: str = "golden_cross"
    cost: float = 0.20
    days: Optional[int] = None


@app.get("/api/scorecard/track")
def scorecard_track_list():
    return {"tracked": ledger.tracked()}


@app.post("/api/scorecard/track")
def scorecard_track_add(t: TrackIn, request: Request):
    """Add stocks to the tracked list. source=watchlist adds every stock
    on the watchlist, source=portfolio every held stock; otherwise the
    given symbols (resolved to the watchlist's exact ticker when the
    user typed a bare name like RELIANCE)."""
    if t.source == "watchlist":
        syms = [sym for (_i, at, sym, _s, _l, _a) in db.get_watchlist()
                if at == "stock" and sym]
    elif t.source == "portfolio":
        syms = sorted({h[1] for h in db.get_holdings(request.state.user)})
    else:
        known = {sym.split(".")[0]: sym for (_i, at, sym, _s, _l, _a)
                 in db.get_watchlist() if sym}
        syms = []
        for raw in t.symbols:
            x = (raw or "").strip().upper()
            if not x:
                continue
            if "." not in x and x in known:
                x = known[x]
            elif "." not in x:
                # unknown bare name: prefer whichever listing has data
                x = next((c for c in (x + ".NS", x + ".BO")
                          if db.stored_rows(c) > 0), x + ".NS")
            syms.append(x)
    days = t.days if t.days and t.days > 0 else None
    res = ledger.track_add(syms, t.source, days)
    return {**res, "tracked": ledger.tracked()}


@app.patch("/api/scorecard/track/{symbol}")
def scorecard_track_days(symbol: str, b: TrackDaysIn):
    """Change how long a tracked stock keeps getting daily snapshots."""
    if not ledger.track_set_days(symbol, b.days if b.days and b.days > 0
                                 else None):
        raise HTTPException(404, "That stock is not being tracked.")
    return {"tracked": ledger.tracked()}


@app.post("/api/scorecard/rule")
def scorecard_rule(b: RuleTrackIn):
    """Put a backtest rule's call on the Scorecard: what the rule says
    today (holding the stock, or out of it) is recorded with today's price
    and graded once the tracking period has passed. The rule is re-run
    here so the recorded call is the server's, not whatever the page sent.
    The stock is tracked for the same period."""
    sym = b.symbol.strip().upper()
    if b.strategy not in backtest.STRATEGIES:
        raise HTTPException(400, "Unknown strategy.")
    res = backtest.run(sym, cost_per_side_pct=b.cost, strategy=b.strategy)
    if res is None:
        raise HTTPException(400, "Not enough usable history.")
    days = b.days if b.days and b.days > 0 else None
    now = res["now"]
    n = ledger.record(
        sym, ledger.RULE_PREFIX + b.strategy,
        "in" if now["invested"] else "out",
        float(res["strategy"]["cagr"]),
        {"strategy": res["strategy_label"], "since": now["since"],
         "why": now["why"], "cost": b.cost},
        horizons=(days or ledger.DEFAULT_RULE_HORIZON,))
    tr = ledger.track_add([sym], "backtest", days)
    return {"recorded": n, **tr, "tracked": ledger.tracked()}


@app.get("/api/changed")
def changed_route(request: Request):
    """Signals fired on this user's watchlist since their previous visit,
    then bump the marker. Decisiveness dies in re-reading unchanged data.

    A first visit has nothing to compare against, so it only sets the
    marker: a brand-new account must not be greeted with every signal the
    app ever logged for other people's stocks."""
    user = request.state.user
    syms = db.watchlist_symbols(user)
    with db.get_conn() as conn:
        row = conn.execute("SELECT last_seen FROM users WHERE username=?",
                           (user,)).fetchone()
        since = row[0] if row and row[0] else None
        rows = []
        if since and syms:
            marks = ",".join("?" * len(syms))
            rows = conn.execute(
                "SELECT symbol, signal, price, reason, created_at FROM "
                f"journal WHERE created_at > ? AND symbol IN ({marks}) "
                "ORDER BY created_at DESC LIMIT 30",
                (since, *syms)).fetchall()
        # journal.created_at is local time, so the marker must be too
        conn.execute("UPDATE users SET last_seen = datetime('now',"
                     "'localtime') WHERE username=?", (user,))
    return {"since": since,
            "signals": [{"symbol": r[0], "signal": r[1], "price": r[2],
                         "detail": r[3], "at": r[4]} for r in rows]}


@app.get("/api/portfolio")
def get_portfolio(request: Request):
    user = request.state.user
    val, totals = portfolio.valuation(user)
    corr, curve, allocation, sectors = None, [], [], []
    if not val.empty:
        c = portfolio.correlation_matrix(val["Symbol"].unique().tolist())
        if c is not None:
            # stocks with no overlapping history correlate to NaN, which
            # JSON can't carry — send null instead of failing the page
            corr = {"labels": [s.split(".")[0] for s in c.columns],
                    "matrix": c.astype(object).where(c.notna(), None)
                               .values.tolist()}
        # ONE row per symbol (lots collapsed) for the table; the dialog
        # shows and manages individual lots.
        val = portfolio.aggregated(val)
        cur_total = totals.get("current") or 0
        if cur_total:
            val["Weight %"] = (val["Current"] / cur_total * 100).round(1)
        # research-checklist tier per symbol, shown as BUY / HOLD / SELL
        # (analysis.ACTION)
        tiers = {}
        for sym in val["Symbol"]:
            try:
                ck = analysis.checklist(sym)
                tiers[sym] = ck["tier"] if ck else None
                if ck:
                    ledger.record(sym, "checklist", ck["tier"],
                                  ck["passed"], {"passed": ck["passed"],
                                                 "applicable": ck["applicable"]})
            except Exception:
                tiers[sym] = None
        val["tier"] = val["Symbol"].map(tiers)
        hist = portfolio.value_history(username=user)
        if hist is not None:
            has_bm = "benchmark" in hist.columns
            curve = [{"time": i.strftime("%Y-%m-%d"),
                      "value": round(r["value"], 2),
                      "invested": round(r["invested"], 2),
                      **({"benchmark": round(r["benchmark"], 2)}
                         if has_bm and r["benchmark"] == r["benchmark"]
                         else {})}
                     for i, r in hist.iterrows()]
        allocation = [
            {"label": r["Symbol"].split(".")[0], "value": r["Current"]}
            for _, r in val.dropna(subset=["Current"]).iterrows()
        ]
        sectors = [{"label": s, "value": round(v, 2)}
                   for s, v in portfolio.sector_allocation(user)]
    dividends = [{"id": i, "symbol": s, "amount": a, "date": d, "note": n}
                 for (i, s, a, d, n) in db.get_dividends(user)]
    realized = portfolio.realized_summary(user)
    return {"holdings": to_records(val), "totals": totals,
            "correlation": corr, "curve": curve,
            "allocation": allocation, "sectors": sectors,
            "dividends": dividends, "realized": realized}


class DividendIn(BaseModel):
    symbol: str
    amount: float
    date: str | None = None
    note: str | None = None


@app.post("/api/dividends")
def add_dividend(d: DividendIn, request: Request):
    if d.amount <= 0:
        raise HTTPException(400, "Dividend amount must be positive.")
    db.add_dividend(d.symbol, d.amount, d.date, d.note, request.state.user)
    return {"ok": True}


@app.delete("/api/dividends/{div_id}")
def delete_dividend(div_id: int, request: Request):
    db.remove_dividend(div_id, request.state.user)
    return {"ok": True}


class Holding(BaseModel):
    symbol: str
    qty: float
    buy_price: float
    buy_date: str | None = None
    thesis: str | None = None


def _holding_symbol(raw):
    """A bare ticker (LICI) is stored under its exchange listing
    (LICI.NS), otherwise valuation finds no prices for it. Prefer a
    listing we already hold prices for; else ask Yahoo / SmartAPI."""
    sym = raw.strip().upper()
    if not sym:
        raise HTTPException(400, "Enter a ticker.")
    if "." not in sym:
        known = [c for c in (f"{sym}.NS", f"{sym}.BO") if db.stored_rows(c)]
        if known:
            return known[0]
        ok, sym, msg = downloader.resolve_and_validate(sym)
        if not ok:
            raise HTTPException(400, msg)
    if not db.stored_rows(sym):
        try:
            downloader.download_one(symbol=sym, asset_type="stock",
                                    progress=lambda m: None)
        except Exception:
            pass  # still record the buy; prices can be fetched later
    return sym


@app.post("/api/portfolio")
def add_holding(h: Holding, request: Request):
    if h.qty <= 0 or h.buy_price <= 0:
        raise HTTPException(400, "Quantity and buy price must be positive.")
    if h.buy_date:
        _require_iso_date(h.buy_date, "Buy date")
    symbol = _holding_symbol(h.symbol)
    db.add_holding(symbol, h.qty, h.buy_price, h.buy_date,
                   request.state.user, thesis=h.thesis)
    return {"ok": True, "symbol": symbol}


@app.post("/api/portfolio/fix-prices")
def fix_holding_prices(request: Request):
    """Fetch prices for this account's holdings that have none (or only
    stale ones), moving bare or priceless listings to one that has data."""
    return portfolio.repair_holding_prices(request.state.user)


@app.delete("/api/portfolio/{holding_id}")
def remove_holding(holding_id: int, request: Request):
    db.remove_holding(holding_id, request.state.user)
    return {"ok": True}


@app.get("/api/position-size")
def size(capital: float, risk_pct: float, entry: float, stop: float):
    ps = portfolio.position_size(capital, risk_pct, entry, stop)
    if ps is None:
        raise HTTPException(400, "Stop must be below entry; inputs positive.")
    return ps


# ----------------------------------------------------------------- journal
@app.get("/api/journal")
def journal(request: Request):
    syms = None
    if getattr(request.state, "role", "user") != accounts.ROLE_ADMIN:
        syms = db.watchlist_symbols(request.state.user)
    rows = db.get_journal(symbols=syms)
    return {"rows": [
        {"when": r[0], "symbol": r[1], "event": r[2], "price": r[3],
         "action": r[4], "detail": r[5]} for r in rows]}


# ------------------------------------------------------------------ static
app.mount("/static", StaticFiles(directory=str(paths.FRONTEND_DIR)),
          name="static")


from app.analyst import analyst_api
app.include_router(analyst_api.router)
app.include_router(auth_api.router)

# News, results calendar, IPOs (free sources) — app/feeds/
from app.feeds import feeds_api  # noqa: E402
app.include_router(feeds_api.router)


@app.get("/")
def root():
    if _react_index():
        return FileResponse(_react_index())
    return legacy_root()


@app.get("/old")
def legacy_root():
    """The previous vanilla-JS UI, kept until the React port reaches parity.
    Serve index.html with cache-busting version tags on the JS/CSS,
    derived from file mtimes — so every patch is picked up on a normal
    reload, no hard-refresh ritual required."""
    import os
    from fastapi.responses import HTMLResponse
    html = open(paths.FRONTEND_DIR / "index.html",
                encoding="utf-8").read()
    for asset in ("js/app.js", "js/analyst.js", "js/features.js",
                  "js/ui-fx.js", "css/styles.css"):
        try:
            v = int(os.path.getmtime(paths.FRONTEND_DIR / asset))
        except OSError:
            v = 0
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={v}")
    return HTMLResponse(html)

# ====================================================================
# FEATURE PACK 2 — data doctor · tier chips & changes · SIP UI ·
# tax report · notes · auto-refresh scheduler
# All additive: nothing above this line changed.
# ====================================================================

# ------------------------------------------------ data doctor
DOCTOR = {"running": False, "log": [], "done": False}


STALE_DAYS = 7        # last price older than this (calendar days) = stale


@app.get("/api/doctor/report")
def doctor_report():
    """Health of every stock/ETF on the signed-in user's watchlist: how many
    days of prices are stored, the latest price date, and where the data
    came from. Also lists watchlist rows that appear more than once, and
    companies watched on both NSE and BSE."""
    today = datetime.date.today()
    out, seen, dupes = [], {}, []
    for (item_id, at, sym, _sc, label, _a) in db.get_watchlist():
        if at == "mf" or not sym:
            continue
        if sym in seen:
            seen[sym]["ids"].append(item_id)
            continue
        rows = db.stored_rows(sym)
        last = db.last_stored_date(sym) if rows else None
        age = ((today - datetime.date.fromisoformat(last[:10])).days
               if last else None)
        status = ("empty" if rows == 0 else "broken" if rows < 30
                  else "thin" if rows < 250
                  else "stale" if age is not None and age > STALE_DAYS
                  else "ok")
        rec = {"id": item_id, "symbol": sym, "label": label, "rows": rows,
               "last": last,
               "age_days": age, "status": status,
               "source": db.symbol_source(sym) if rows else None,
               "ok": status == "ok", "thin": status == "thin",
               "empty": rows == 0, "ids": [item_id]}
        seen[sym] = rec
        out.append(rec)
    for rec in out:
        if len(rec["ids"]) > 1:
            dupes.append({"symbol": rec["symbol"],
                          "copies": len(rec["ids"])})
    by_base = {}
    for rec in out:
        b, _, suf = rec["symbol"].partition(".")
        if suf in ("NS", "BO"):
            by_base.setdefault(b, []).append(rec["symbol"])
    both = [{"company": b, "symbols": sorted(v)}
            for b, v in sorted(by_base.items()) if len(v) > 1]
    rank = {"empty": 0, "broken": 1, "thin": 2, "stale": 3, "ok": 4}
    out.sort(key=lambda r: (rank[r["status"]], r["rows"]))
    for rec in out:
        rec.pop("ids")
    count = lambda st: sum(1 for r in out if r["status"] == st)
    return {"symbols": out, "checked": len(out),
            "scanned_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "broken": count("empty") + count("broken"),
            "thin": count("thin"), "stale": count("stale"),
            "healthy": count("ok"), "stale_days": STALE_DAYS,
            "duplicates": dupes, "both_exchanges": both}


@app.post("/api/doctor/dedupe")
def doctor_dedupe(request: Request):
    """Remove repeated rows of the same symbol from the signed-in user's
    watchlist, keeping the first one."""
    removed = db.dedupe_watchlist(request.state.user)
    return {"removed": removed}


def _doctor_repair(only=None):
    if only:
        targets = [(only, "stock")]
        DOCTOR["log"].append(f"Repairing {only}…")
    else:
        DOCTOR["log"].append("Looking for symbols with under 30 days of "
                             "prices…")
        seen, targets = set(), []
        for (_id, at, sym, _sc, _l, _a) in db.get_watchlist():
            if (at in ("stock", "etf") and sym and sym not in seen
                    and db.stored_rows(sym) < 30):
                seen.add(sym)
                targets.append((sym, at))
        DOCTOR["log"].append(
            f"{len(targets)} symbol{'' if len(targets) == 1 else 's'} "
            "need repair." if targets else
            "Nothing to repair: every symbol has at least 30 days of prices. "
            "Thin or stale ones fill in with the next data refresh.")
    fixed = swapped = failed = 0
    exch = {"NS": "NSE", "BO": "BSE"}
    for sym, at in targets:
        try:
            downloader.download_ticker(sym, at, progress=lambda m: None)
            best_sym, best = sym, db.stored_rows(sym)
            note = ""
            if best < 30 and (sym.endswith(".NS") or sym.endswith(".BO")):
                base, suf = sym.rsplit(".", 1)
                alt = f"{base}.{'BO' if suf == 'NS' else 'NS'}"
                try:
                    downloader.download_ticker(alt, at,
                                               progress=lambda m: None)
                except Exception:
                    pass
                alt_rows = db.stored_rows(alt)
                if alt_rows > best:
                    if db.repoint_watchlist_symbol(sym, alt):
                        swapped += 1
                        best_sym, best = alt, alt_rows
                    else:
                        note = (f" The {exch[alt[-2:]]} listing ({alt}) is "
                                f"already on a watchlist with {alt_rows} "
                                f"days, so this {exch[suf]} copy can be "
                                "removed.")
            if best >= 30:
                fixed += 1
                DOCTOR["log"].append(
                    f"Fixed {best_sym}: {best} days of prices"
                    + (f" (moved from {sym}, which had no history)"
                       if best_sym != sym else ""))
            else:
                failed += 1
                DOCTOR["log"].append(
                    f"Could not fix {sym}: still {best} days of prices."
                    + (note or " The data source has nothing older; it may "
                       "be newly listed, renamed or delisted."))
        except Exception as e:
            failed += 1
            DOCTOR["log"].append(f"Error on {sym}: {e}")
    if targets:
        DOCTOR["log"].append(
            f"Finished: {fixed} fixed"
            + (f" ({swapped} moved to the other exchange)" if swapped else "")
            + f", {failed} still short of data.")
    DOCTOR.update(running=False, done=True)


@app.post("/api/doctor/repair")
def doctor_repair(symbol: str = None):
    """Re-download symbols with under 30 days of prices (or just `symbol`),
    trying the other exchange when one listing has no history."""
    if DOCTOR["running"]:
        return {"status": "already_running"}
    DOCTOR.update(running=True, done=False, log=[])
    threading.Thread(target=_doctor_repair,
                     args=((symbol or "").strip().upper() or None,),
                     daemon=True).start()
    return {"status": "started"}


@app.get("/api/doctor/status")
def doctor_status():
    return {"running": DOCTOR["running"], "done": DOCTOR["done"],
            "log": DOCTOR["log"][-40:]}


# ------------------------------------------------ checklist tiers
TIERS = {"computing": False, "at": 0.0, "tiers": {}}
_TIER_TTL = 6 * 3600


def _compute_tiers():
    try:
        tiers = {}
        trackers = ledger.active_trackers()
        for (_id, at, sym, _sc, _l, _a) in db.get_watchlist():
            if at != "stock" or not sym:
                continue
            try:
                ck = analysis.checklist(sym)
                tiers[sym] = ck["tier"] if ck else None
                for user in (trackers.get(sym, []) if ck else []):
                    ledger.record(sym, "checklist", ck["tier"],
                                  ck["passed"], {"passed": ck["passed"],
                                                 "applicable": ck["applicable"]},
                                  username=user)
            except Exception:
                tiers[sym] = None
        TIERS["tiers"] = tiers
        TIERS["at"] = time.time()
        db.record_tiers({s: t for s, t in tiers.items() if t})
    finally:
        TIERS["computing"] = False


@app.get("/api/tiers")
def get_tiers():
    """Checklist tier per stock, cached ~6h and computed off-thread so
    the watchlist never waits on it. Also returns recent tier changes."""
    fresh = time.time() - TIERS["at"] < _TIER_TTL and TIERS["tiers"]
    if not fresh and not TIERS["computing"]:
        TIERS["computing"] = True
        threading.Thread(target=_compute_tiers, daemon=True).start()
    return {"ready": bool(TIERS["tiers"]), "tiers": TIERS["tiers"],
            "computing": TIERS["computing"],
            "changes": [{"symbol": s, "from": o, "to": n, "date": d}
                        for (s, o, n, d) in db.tier_changes()]}


# ------------------------------------------------ SIPs
class SipIn(BaseModel):
    scheme_code: int
    amount: float
    day_of_month: int
    start_date: str


@app.get("/api/sips")
def list_sips():
    from app.portfolio import sip as sip_mod
    out = []
    for (sid, code, amount, day, start, label) in db.get_sips():
        ev = None
        try:
            ev = sip_mod.evaluate(code, amount, day, start)
        except Exception:
            pass
        out.append({"id": sid, "scheme_code": code,
                    "label": label or f"MF {code}",
                    "amount": amount, "day": day, "start": start,
                    "eval": ev})
    return {"sips": out}


@app.post("/api/sips")
def create_sip(s: SipIn):
    if s.amount <= 0 or not (1 <= s.day_of_month <= 28):
        raise HTTPException(400, "Amount must be positive; day 1–28.")
    db.add_sip(s.scheme_code, s.amount, s.day_of_month, s.start_date)
    return {"ok": True}


@app.delete("/api/sips/{sip_id}")
def delete_sip(sip_id: int):
    db.remove_sip(sip_id)
    return {"ok": True}


# ------------------------------------------------ tax report
@app.get("/api/taxreport")
def tax_report(request: Request):
    """Realized gains per Indian financial year, split STCG / LTCG by
    the 1-year rule. A worksheet for your CA, not tax advice."""
    import datetime as _dt

    def fy(d):
        return (f"FY{d.year}-{str(d.year + 1)[2:]}" if d.month >= 4
                else f"FY{d.year - 1}-{str(d.year)[2:]}")

    years = {}
    for (_id, sym, qty, bp, bd, sp, sd) in db.get_sells(request.state.user):
        try:
            sdate = _dt.date.fromisoformat(sd)
        except Exception:
            continue
        gain = (sp - bp) * qty
        held = None
        if bd:
            try:
                bdate = _dt.date.fromisoformat(bd)
                held = (sdate - bdate).days
            except Exception:
                pass
        bucket = ("ltcg" if held is not None
                  and portfolio.is_long_term(bdate, sdate) else "stcg")
        y = years.setdefault(fy(sdate),
                             {"stcg": 0.0, "ltcg": 0.0, "trades": 0,
                              "unknown_period": 0})
        y[bucket] += gain
        y["trades"] += 1
        if held is None:
            y["unknown_period"] += 1
    return {"years": [{"fy": k, **{kk: round(vv, 2) if isinstance(vv, float)
                                   else vv for kk, vv in v.items()}}
                      for k, v in sorted(years.items(), reverse=True)]}


# ------------------------------------------------ notes
class NoteIn(BaseModel):
    symbol: str
    text: str


@app.get("/api/notes/{symbol}")
def notes_for(symbol: str, request: Request):
    return {"notes": [{"id": i, "text": t, "created": c}
                      for (i, t, c) in db.get_notes(symbol.upper(),
                                                    request.state.user)]}


@app.post("/api/notes")
def add_note(n: NoteIn, request: Request):
    if not n.text.strip():
        raise HTTPException(400, "Empty note.")
    db.add_note(n.symbol.upper(), n.text.strip(), request.state.user)
    return {"ok": True}


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, request: Request):
    db.remove_note(note_id, request.state.user)
    return {"ok": True}


# ------------------------------------------------ auto-refresh scheduler
def _auto_refresh_loop():
    """Kick a full refresh once per weekday after market close (IST).
    Set AUTO_REFRESH = False in config.py to disable."""
    import datetime as _dt
    hh, mm = (getattr(config, "AUTO_REFRESH_TIME", "16:05")).split(":")
    target = int(hh) * 60 + int(mm)
    # On a market holiday (or before Yahoo publishes the day's bar) the
    # data never becomes "today", and this loop used to start a fresh
    # full refresh every minute until midnight, pinning the phone's CPU
    # and database. Now: one attempt per day, plus one retry 3 h later.
    attempts = {"day": None, "n": 0, "at": 0.0}
    while True:
        time.sleep(60)
        try:
            if not getattr(config, "AUTO_REFRESH", True):
                continue
            now = _dt.datetime.now()
            if now.weekday() >= 5:                       # weekend
                continue
            if now.hour * 60 + now.minute < target:
                continue
            if db.last_price_date() == now.date().isoformat():
                continue                                 # already fresh
            if REFRESH["running"]:
                continue
            today = now.date().isoformat()
            if attempts["day"] != today:
                attempts.update(day=today, n=0, at=0.0)
            if attempts["n"] >= 2 or (attempts["n"] == 1
                                      and time.time() - attempts["at"] < 3 * 3600):
                continue
            attempts["n"] += 1
            attempts["at"] = time.time()
            REFRESH.update(running=True, done=False,
                           log=[f"[auto] scheduled refresh {now:%H:%M}"])
            threading.Thread(target=_do_refresh, daemon=True).start()
        except Exception:
            pass                                         # never die


def _weekly_digest_loop():
    """Send the Telegram digest once a week (default Sunday 18:00 local).
    config.py: AUTO_DIGEST = False to disable, AUTO_DIGEST_DAY = 0..6
    (Mon..Sun), AUTO_DIGEST_TIME = "HH:MM". Skips if Telegram isn't
    configured or if it already went out today."""
    import datetime as _dt
    while True:
        time.sleep(60)
        try:
            if not getattr(config, "AUTO_DIGEST", True):
                continue
            from app.alerts import notify
            if not notify.configured():
                continue
            now = _dt.datetime.now()
            if now.weekday() != int(getattr(config, "AUTO_DIGEST_DAY", 6)):
                continue
            hh, mm = (getattr(config, "AUTO_DIGEST_TIME", "18:00")).split(":")
            if now.hour * 60 + now.minute < int(hh) * 60 + int(mm):
                continue
            from app.analysis import digest as dg
            last = dg.last_sent() or ""
            if last[:10] == now.date().isoformat():
                continue                                 # already sent today
            dg.send_digest()
        except Exception:
            pass                                         # never die


WARM_SYMBOLS_PER_USER = 35        # stays under detail_core's cache cap


def _warm_caches():
    """Pre-compute what each user opens most, so the first view after a
    start or the evening refresh is as quick as a repeat one: their
    portfolio, funds, rankings, and the stock page + verdict of their
    holdings and watchlist. It runs the same route functions a real visit
    does, so it fills exactly the cache entries those visits read
    (app.core.memo). Background thread; a short pause between stocks leaves
    the CPU to anyone actually using the app."""
    from types import SimpleNamespace
    for u in accounts.list_users():
        name = u["username"]
        token = db.current_user.set(name)        # per-user results
        req = SimpleNamespace(state=SimpleNamespace(user=name, role=u["role"]),
                              cookies={})
        try:
            for job in (lambda: get_portfolio(req),
                        lambda: funds.overview(name), rankings):
                try:
                    job()
                except Exception:
                    pass
            held = [h[1] for h in db.get_holdings(name)]
            watch = [w[2] for w in db.get_watchlist("stock") if w[2]]
            for sym in list(dict.fromkeys(held + watch))[:WARM_SYMBOLS_PER_USER]:
                for job in (lambda: detail(sym, req), lambda: verdict_route(sym)):
                    try:
                        job()
                    except Exception:
                        pass                     # e.g. no prices yet (404)
                time.sleep(0.05)
        finally:
            db.current_user.reset(token)


def _repair_holdings_soon():
    """Once per start, a minute in: price any holding left without data
    (earlier downloads may have failed), then warm the caches. Cheap when
    nothing needs repairing."""
    time.sleep(60)
    try:
        portfolio.repair_holding_prices()
    except Exception:
        pass
    try:
        _warm_caches()
    except Exception:
        pass


def _start_background():
    """Called once from the app lifespan (see top of file)."""
    from app.feeds import ipos as _ipos
    threading.Thread(target=_warm_scrips, daemon=True).start()
    threading.Thread(target=_auto_refresh_loop, daemon=True).start()
    threading.Thread(target=_repair_holdings_soon, daemon=True,
                     name="holding-price-repair").start()
    threading.Thread(target=_weekly_digest_loop, daemon=True).start()
    threading.Thread(target=_ipos.subscription_loop, daemon=True,
                     name="ipo-subscription").start()
    try:
        from app.alerts import telegram_bot
        telegram_bot.start()                 # no-op without a bot token
    except Exception:
        pass


# ====================================================================
# REACT FRONTEND — static assets + single-page-app fallback.
# Keep this block LAST: the catch-all route must be registered after
# every API route and router, or it would shadow them.
# ====================================================================
class _HashedAssets(StaticFiles):
    """Vite puts a content hash in every asset name, so a file at a given
    URL never changes: let the browser keep it for a year instead of
    re-asking through the tunnel on every visit."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if (paths.REACT_DIST / "assets").exists():
    app.mount("/assets", _HashedAssets(directory=str(paths.REACT_DIST / "assets")),
              name="react-assets")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Any non-API path (e.g. /stocks/RELIANCE.NS, /portfolio) returns the
    React index so client-side routes survive a page reload."""
    if full_path.startswith(("api/", "analyst/", "docs/", "static/", "assets/")):
        raise HTTPException(404, "Not found.")
    index = _react_index()
    if index is None:
        raise HTTPException(404, "Not found.")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
