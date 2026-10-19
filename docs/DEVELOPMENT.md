# Development notes

How the code is organised and the conventions to keep. For how a request
travels through the code, see [flow.md](flow.md); for why things are the
way they are, see [decisions.md](decisions.md).

## Layout

```
backend/
  app/
    main.py          FastAPI app: routes, startup, background jobs
    core/            config, paths, .env loader, SQLite, auth, accounts,
                     result cache (memo.py), LLM provider chain (llm.py)
    data_sources/    Yahoo downloader, NSE, Angel One SmartAPI, live quotes,
                     index universes
    analysis/        checklist, patterns, base rates, backtests, ML model,
                     factor ranking, verdict, screener query engine, news NLP
    analyst/         AI analyst (tool-calling loop), its API router,
                     document library, prompt-injection guard, PII masking
    portfolio/       holdings and P&L, SIPs, mutual funds
    alerts/          signal engine and notifications (Telegram)
  prompt_injection_sdk/   vendored scanner (see its VENDORED.md)
  tests/
frontend-react/      React + TypeScript UI (Vite); FastAPI serves dist/
frontend/            the previous plain-JS UI, still served at /old
deploy/termux/       running and updating the app on an Android phone
scripts/             health checks, password reset, dev database
docs/
data/                runtime state, never committed: market_data.db, caches
```

## Conventions

- **All paths** come from `app/core/paths.py`. Never hardcode a relative
  path; add an anchor there instead.
- **Secrets** only ever live in `.env`, read through `app.core.envutil.get`.
- **New API routes**: small features go in `app/main.py`; anything with
  more than a couple of endpoints gets its own `APIRouter` module next to
  its logic (see `app/analyst/analyst_api.py`) and one `include_router`
  line in `main.py`.
- **Anything that writes stored data** carries `@db._changes_data`. Cached
  results (`app/core/memo.py`) are reused until the data version moves, so
  a writer without it leaves pages showing old numbers for up to 6 hours.
- **Database access** goes through `database.get_conn()`, which reuses one
  SQLite connection per thread. No per-row `iterrows`, no DDL per request.
- **Runtime files** belong in `data/`. Deleting that folder is a factory
  reset.
- Shell scripts under `deploy/termux/` must keep LF line endings
  (`.gitattributes` enforces this).

## Running locally

```bash
# backend, from the project root
run.bat                       # Windows (uses .venv and the dev database if present)
./run.sh                      # Linux / macOS

# frontend with hot reload, in a second terminal
cd frontend-react
npm install
npm run dev                   # http://localhost:5173, proxies /api to :8000
```

`npm run build` writes `frontend-react/dist`, which FastAPI serves on
http://localhost:8000.

`run.bat` uses `data/market_data.dev.db` whenever that file exists (made by
`scripts/make_dev_db.py`, keeping only one account), otherwise
`data/market_data.db`. `LEDGERLINE_DB` picks the file; only a bare file
name inside `data/` is accepted.

## Tests

```bash
cd backend
python -m pytest
```

The suite uses a throwaway database and never touches `data/`.

## Health checks

| Script | What it tells you |
|---|---|
| `scripts/check_setup.py` | which database the server opens, the accounts and holdings in it, whether each portfolio builds (`--login NAME` checks a password) |
| `scripts/check_llm.py` | which AI keys are set and whether each provider answers on its own |
| `scripts/check_smartapi.py` | the Angel One live-quote login |
| `scripts/check_mail.py` | email sending through Resend |
| `scripts/check_nse.py` | NSE endpoints |

## Forgot your login?

Accounts are local. On the machine running the app:

```bash
python scripts/reset_password.py --list      # shows the usernames
python scripts/reset_password.py             # pick one, set a new password
```

It backs up `data/market_data.db` to `data/backups/` first, then rewrites
only that account's password hash.

## Moving the database to another machine

Never copy `market_data.db` while a server is using it: recent changes sit
in `market_data.db-wal`, and a copy without them (or with an old `-wal`
left on the target) is reported as "database disk image is malformed".
Make a snapshot with SQLite's backup instead:

```python
import sqlite3
src = sqlite3.connect("file:data/market_data.db?mode=ro", uri=True)
dst = sqlite3.connect("market_data.snapshot.db")
src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
dst.close()
```

On the target, delete every `market_data*.db*` file in `data/` and put the
snapshot there as `market_data.db`.

## AI provider chain

The analyst, the English screener, the news explainer and the prospectus
reader all go through `app/core/llm.py`, which tries providers in order
with automatic failover and a cooldown per provider. The default order is
`gemini`, `groq`, `groq-alt`, `openrouter`, each only if its key is set.
`LLM_PROVIDER_ORDER` overrides the order, and a provider missing from it is
skipped even when its key is set.

Gemini and Groq's gpt-oss models are reasoning models: their thinking
counts against `max_tokens`. Callers check `finish_reason == "length"` and
refuse or annotate a cut-off answer instead of using it.

## Scorecard (the app grades itself)

Every call the app shows (the verdict, the checklist's Buy/Hold/Sell and
the next-day model) is written to the `predictions` table with that day's
close, then graded once its horizon passes: the next trading day for the
model, 30 and 90 days for the others, against the actual close and against
NIFTYBEES over the same window. Ledger rows are never edited or deleted.
