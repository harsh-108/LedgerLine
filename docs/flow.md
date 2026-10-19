# flow.md — how execution travels through this codebase

Entry point for everything: `backend/app/main.py` (FastAPI app object
`app`). Started by `run.sh` / `run.bat` → `uvicorn app.main:app`.
Exit point for everything: a JSON response (API routes) or a file
response (frontend assets). The browser side has exactly one entry:
`frontend/index.html` loads `js/app.js` (the whole SPA), plus
`js/analyst.js` (analyst page) and `js/ui-fx.js` (cosmetics).

Conventions in this file: `A → B` means A calls B.
`[file.py:fn]` pins the function. Only meaningful hops are shown.

---

## 1. Server startup

```
uvicorn app.main:app
 → main.py module import
    → app/core/config.py            (settings + watchlist constants)
    → app/core/paths.py             (anchors every filesystem path)
    → database.init_db()            [core/database.py]  creates/migrates
    │                               sqlite at data/market_data.db
    → auth._ensure_tables()         [core/auth.py]  users + sessions
    → database.seed_watchlist_if_empty()
    → app.mount("/static", frontend/)
    → app.include_router(analyst_api.router)   [analyst/analyst_api.py]
    → background thread: scheduled refresh loop (downloader, alerts)
```

## 2. Request lifecycle: any authenticated call

```
HTTP request
 → require_login middleware          [main.py, ~line 51]
    → skip if path in PUBLIC_PATHS   (/login, /api/auth/*, /static/*)
    → read "wt_session" cookie
    → auth.session_user(token)       [core/auth.py]
       hit  → request.state.user set → route handler runs
       miss → 401 JSON (API) or 307 redirect to /login (pages)
```

## 3. Login / first-run

```
GET /            → main.root() → 307 /login (no cookie)
GET /login       → FileResponse(frontend/login.html)
login.html JS    → POST /api/auth/setup   (only if no users exist)
                 → POST /api/auth/login
    → auth.verify(username, pw)          scrypt hash compare
    → auth.start_session(username)       row in sessions table
    → Set-Cookie wt_session → JS redirects to /
GET /            → main.root() reads frontend/index.html,
                   appends ?v=mtime to js/css links (cache-bust),
                   returns HTML → browser boots app.js
```

## 4. SPA boot (browser)

```
app.js IIFE
 → GET /api/summary        → stats for Home cards
 → GET /api/watchlist      → sidebar + tables render
 → rail-link click → showPage(name): toggles .page visibility,
   lazy-fetches that page's data on first open
analyst.js IIFE
 → injects "Analyst" rail button + #page-analyst section
 → GET /api/analyst/status → shows/hides "no key" banner
ui-fx.js IIFE
 → attaches "i" info buttons (INFO dict), scroll reveals,
   stat count-ups, Lenis smooth scroll
```

## 5. Data refresh ("Refresh data" button / scheduler)

```
POST /api/refresh                        [main.py]
 → for each watchlist row:
    downloader.download_ticker(sym)      [data_sources/downloader.py]
     → yfinance history fetch (retries)
     → falls back: nse_source / smartapi_source when configured
     → database.save_prices(df, sym)     upsert into prices table
    downloader.fetch_fundamentals(sym)   → fundamentals table
 → analysis.evaluate(sym)                [analysis/analysis.py]
     checklist verdict per stock (trend, RSI, valuation checks)
 → alerts.scan()                         [alerts/alerts.py]
     → db.log_signal(sym, TYPE, ...)     GOLDEN_CROSS / RSI_* / PRICE_ALERT
     → notify.send(...)                  [alerts/notify.py] if configured
exit: JSON progress summary → app.js re-renders Home
```

## 6. Screener query

```
POST /api/screener/query {q}
 → query_engine.run_query(q)             [analysis/query_engine.py]
    → build_metrics()      one wide pandas frame: price + fundamentals
    → _parse_condition()   "roe > 15 and pe < 30" → mask
    → returns matching rows + the metric table
 → app.js renders table (th labels match ui-fx INFO keys → "i" buttons)
```

## 7. Backtest

```
GET /api/strategies → backtest.STRATEGIES labels     (dropdown)
GET /api/backtest/{sym}?strategy=X&cost=Y
 → backtest.run(sym, cost, X)            [analysis/backtest.py]
    → database.stored_rows(sym) → pandas
    → STRATEGIES[X]["fn"](df)  → 0/1 position series
    → equity curves with per-side costs vs buy-and-hold
 exit: {strategy, buy_hold, curves, trades} → app.js draws
       lightweight-charts equity curves
```

## 8. AI analyst chat (the long one)

```
POST /api/analyst/chat {text}
 → analyst_api.chat_route()              [analyst/analyst_api.py]
 → analyst.chat(session_id, text)        [analyst/analyst.py]
    → _get_session() / _trim()           per-user rolling history
    → loop ≤ MAX_TOOL_ROUNDS (4):
        _call_llm(messages)
         → _providers()                  groq → groq-alt → gemini
         → requests.post(provider.url)   OpenAI-format chat completion
         → on 429/error: bench provider (_down_until), try next;
           if ALL 429 with short hint: sleep once, retry chain
        model returns tool_calls?
         → _run_tool(name, args) dispatches to TOOLS dict:
             screen_stocks   → query_engine.run_query
             stock_snapshot  → database + analysis
             backtest        → backtest.run
             base_rates      → base_rates.compute
             live_quote      → live.quote (SmartAPI) or yahoo
             search_documents→ documents.search_chunks
             list_documents  → documents.list_docs
             web_search      → tavily (if TAVILY_API_KEY)
         → tool result JSON appended to messages (capped 4000 chars)
        no tool_calls → final text
    → sess["messages"] += final reply (tools not persisted)
 exit: {reply, tools_used, provider}
 → analyst.js: mdRender(reply) → styled bubble
```

## 9. Document ingest (filings library)

```
POST /api/docs/upload (multipart)        [analyst/analyst_api.py]
 → documents.ingest_file(bytes, ...)     [analyst/documents.py]
    → _extract_text: pypdf / pandas-excel / plain
    → _chunk(text) ~1400 chars, 150 overlap
    → documents + doc_chunks tables
POST /api/docs/fetch-bse {scrip_code}
 → documents.fetch_from_bse()
    → BSE announcements API (public filings, 1 yr)
    → title match: transcript/annual/presentation (≤12 files)
    → same ingest path per PDF
exit: {added: N} → analyst.js refreshes filing list
```

## 10. Scripts (standalone entries)

```
scripts/check_smartapi.py  → layer-by-layer SmartAPI credential probe
scripts/reset.py           → surgical wipe of data/ tables
legacy/streamlit_app.py    → old UI; same backend modules, run via
                             `streamlit run legacy/streamlit_app.py`
```
