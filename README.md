# Ledgerline

**A personal research terminal for Indian stocks and mutual funds, with an AI analyst that shows its sources and a scorecard that grades its own calls.**

It runs on an old Android phone: FastAPI + React in Termux, reached from anywhere over an ngrok tunnel. No cloud bill.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React_18-TypeScript-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![Tests](https://img.shields.io/badge/tests-287_passing-brightgreen)

## Demo

<!--
  To embed the video: open this file on github.com, click the pencil (Edit),
  put the cursor on the empty line below and drag your .mp4 into the editor.
  GitHub uploads it and inserts a link that plays inline. Then commit.
  (Free accounts: up to 10 MB per video; paid: up to 100 MB.)
-->


## What it does

| Area | Highlights |
|---|---|
| **Stocks** | Candlestick charts with SMA 50/200, EMA 20, Bollinger bands, RSI and MACD; fundamentals; delivery data; shareholding; peers; compare up to four stocks |
| **Buy / Hold / Sell** | A research checklist turns into a plain call, with what supports it and what argues against it |
| **Screener** | Ask in English: *"IT stocks with market cap above 2000 crore"* becomes a validated query over NIFTY 50/100/500 or your watchlist |
| **Portfolio** | Holdings and lots, P&L, XIRR, dividends, allocation, value over time against NIFTYBEES with the same cash flows, sell and rebalance tools, tax reports |
| **Mutual funds** | Any AMFI scheme, NAV history, rolling returns, SIPs, comparison against simply holding the index |
| **Research** | Backtests (5 strategies, trading costs included), factor rankings, an ML lab, a journal of signals, and a scorecard |
| **AI analyst** | Answers questions using your portfolio, the stored data and the company filings you upload, and names its sources |
| **Also** | Alerts on Telegram, news with plain-language explainers, IPO prospectus reader, results calendar, SIP calculators |

## The AI and ML inside

**Large language models**
- **Tool-calling analyst.** The model chooses among 15 read-only tools: stock snapshot, statements, peers, patterns, events, shareholding, live quote, your portfolio, mutual funds, the screener, symbol lookup, document list/search/read, and web search.
- **Provider failover.** Gemini, then Groq (`gpt-oss`), then OpenRouter, each with its own cooldown. Reasoning models' cut-off answers are detected and never shown as complete.
- **English screener.** The model only translates English into the app's own query language. A whitelist parser validates and runs it, so the model never sees your data.
- **Document search.** Filings are split along their own structure and searched with BM25 (SQLite FTS5), with synonyms and a coverage re-rank.
- **News explainer and prospectus reader.** Short summaries of headlines, and key figures pulled from IPO prospectuses as checked JSON.

**Machine learning and statistics**
- **Next-day direction model.** Gradient boosting (scikit-learn `HistGradientBoostingClassifier`) on 9 technical features. It's tested strictly in time order and always shown next to a naive baseline, because about 50–55% is what honest next-day prediction looks like.
- **Base rates.** What actually happened 1, 3 and 6 months after each past signal on the same stock.
- **Factor ranking.** Momentum, value, quality and trend, standardised across your watchlist, with the weights shown.
- **Self-grading scorecard.** Every call is recorded with that day's price and graded later against the real outcome and against NIFTYBEES. Nothing is edited after the fact.

## Safety and privacy

- **Prompt-injection defence.** A scanner that sees through leetspeak, look-alike letters, invisible characters and base64 checks every question and screener query. Attacks are refused before any AI call. Text from filings and the web is fenced off as untrusted, and instruction-like passages in it are flagged.
- **Personal-data masking.** PAN, Aadhaar, phone numbers, emails, bank and demat numbers are replaced with tokens before anything reaches an AI service, and restored in the reply.
- **Scoped AI.** The analyst's tools are read-only and limited to the signed-in user. Answers are rate-limited, rendered as plain text and kept to the app's subject.
- **Accounts.** PBKDF2 password hashing, hashed session tokens, invite-only sign-up, Google sign-in, login rate limits, sign-in alerts on Telegram, "sign out other devices", security headers. Internal errors are hidden from users.

## Built to be fast on a phone

- **Result cache.** Results are reused until the stored data actually changes. Every writer bumps a data version, so nothing is ever stale.
- **Pre-warmed pages.** After each daily refresh, each user's portfolio, funds and stock pages are built in advance.
- **Compact chart data.** Chart data is sent as columns: about 210 KB per stock instead of 1 MB.
- **Lean database access.** One SQLite connection per thread, no per-request schema work, indexed price lookups.
- **Self-healing on the phone.** The server and the tunnel each restart within 10 seconds if they die, even after Android kills the session.

## Tech stack

**Backend:** Python, FastAPI, SQLite (FTS5), pandas, NumPy, scikit-learn
**Frontend:** React 18, TypeScript, Vite, TanStack Query, TradingView Lightweight Charts
**AI:** Gemini, Groq, OpenRouter (any OpenAI-compatible API)
**Data:** Yahoo Finance, NSE, AMFI (mfapi.in), BSE filings, Angel One SmartAPI (live quotes)
**Running it:** Termux on Android, ngrok, Telegram Bot API, Resend (email)

## Getting started

You need Python 3.11+ and Node.js 18+.

```bash
git clone https://github.com/<your-username>/ledgerline.git
cd ledgerline

# 1. Python packages
python -m venv .venv
.venv\Scripts\activate                 # Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Settings: copy the example and add at least one AI key
copy .env.example .env                 # Linux/macOS: cp .env.example .env

# 3. Build the web app
cd frontend-react
npm install
npm run build
cd ..

# 4. Start
run.bat                                # Linux/macOS: ./run.sh
```

Open http://localhost:8000. On first start you create the admin account. Then press **Refresh data** to download prices for the starter watchlist.

### Settings (`.env`)

| Key | Needed for |
|---|---|
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | the AI analyst, English screener and news explainer (at least one) |
| `LLM_PROVIDER_ORDER` | the order providers are tried in |
| `APP_BASE_URL` | links in emails; an `https://` address also turns on secure cookies |
| `GOOGLE_CLIENT_ID` | Google sign-in (optional) |
| `RESEND_API_KEY`, `MAIL_FROM` | verification and password-reset emails (optional) |
| `TELEGRAM_BOT_TOKEN` | alerts and sign-in notices on Telegram (optional) |
| `SMARTAPI_*` | live quotes from Angel One (optional) |
| `TAVILY_API_KEY` | web search for the analyst (optional) |
| `SIGNUP_REQUIRE_INVITE` | `1` = new accounts need an invite code |

`.env` is never committed. `.env.example` lists every setting.

### Running on an Android phone

See [deploy/termux/TERMUX.md](deploy/termux/TERMUX.md): install in Termux, start on boot, a reserved ngrok domain, and one-command updates that roll back automatically if the new version fails to start.

## Tests

```bash
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest
```

287 tests cover the API, sign-in and sessions, the cache, the screener, the analyst's guards and the privacy masking. The vendored prompt-injection scanner's own tests run too. Tests use a throwaway database.

## Project layout

```
backend/app/         FastAPI app: core, data sources, analysis, analyst, portfolio, alerts
frontend-react/      React + TypeScript UI
deploy/termux/       phone setup, boot supervisor, updater
scripts/             health checks, password reset
docs/                development notes, request flow, design decisions
```

More in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), [docs/flow.md](docs/flow.md) and [docs/decisions.md](docs/decisions.md).

## Disclaimer

Ledgerline is a personal research tool, not investment advice. Its Buy / Hold / Sell calls come from rules applied to stored and possibly delayed data, and its own scorecard shows how often they turn out right. Do your own research before investing.
