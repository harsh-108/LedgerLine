# decisions.md — why things are the way they are

Append-only log. Newest last. Each entry: the decision, the
alternatives that lost, and why. Entries marked *(inherited)* predate
this log and were reconstructed from code comments.

---

**D-001 *(inherited)* — SQLite as the only datastore.**
Alternatives: Postgres, flat CSVs. SQLite wins for a single-user local
app: zero setup, one file to back up (`data/market_data.db`), fast
enough for ~70 tickers × 10y daily candles. Postgres adds a service to
babysit for no gain at this scale. Revisit only if this becomes
multi-machine.

**D-002 *(inherited)* — FastAPI + vanilla JS, no build step.**
Alternatives: React/Vite SPA, Streamlit. Streamlit (kept in `legacy/`)
hit its ceiling: no real routing, reruns whole scripts per click.
React adds node_modules + a build pipeline to a project edited casually.
Vanilla JS with one `app.js` keeps edit → refresh instant. Cost
accepted: manual DOM code. Consequence: React/Vue component libraries
(Animate UI, Inspira UI) can't be used directly — their *patterns* are
ported in CSS/JS instead (see D-013).

**D-003 *(inherited)* — yfinance primary, NSE/SmartAPI fallbacks.**
Yahoo is free, no signup, 10y history — but flaky for .BO tickers.
Decision: layered sources with per-source tagging in `save_prices`
rather than switching wholesale to a paid feed.

**D-004 — Session-cookie auth, scrypt hashing (not JWT).**
JWTs can't be revoked without a denylist (a table anyway) and expire
awkwardly for an app left open all day. Server-side session rows are
simpler and instantly revocable. scrypt via stdlib `hashlib` = zero
dependencies.

**D-005 — AI analyst as a tool-calling loop, not RAG-everything.**
Alternatives: stuff all data into the prompt; embeddings-based RAG.
Tool calls let the model pull only what the question needs (screener,
backtest, filings search), keeping prompts small and answers auditable
(`tools_used` in every reply). Cap: 4 rounds, 4000 chars/result —
free-tier token budgets are the binding constraint (see D-009).

**D-006 — Keyword search over filings, no embeddings.**
Alternatives: sentence-transformers + vector store. For ≤ a few dozen
documents per stock, scored keyword match over 1,400-char chunks finds
the right passages, needs zero new dependencies, no index build, no
model download. Embeddings become worth it only at 100s of documents.

**D-007 — BSE auto-fetch allowed; Screener/Tijori scraping refused.**
BSE announcements are public regulatory filings — fetching them (rate
limited, ≤12 files) is legitimate. Screener/Tijori are login-walled
products; ingesting their data happens only via the user's own manual
export. Ethics line drawn deliberately in code comments.

**D-008 — 2026-06: Groq model swap `llama-3.3-70b` → `gpt-oss-120b`.**
Groq deprecated llama-3.3-70b-versatile for free tier (announced
2026-06-17); calls began returning 400. Lesson encoded: model names now
come from `.env` (`GROQ_MODEL`) so the next deprecation is a config
edit, not a code fix. Error handler upgraded to surface the provider's
own message.

**D-009 — Provider chain with failover + cooldown, in ~60 lines.**
Alternatives: LiteLLM / LangChain routers. Rejected: heavyweight deps
for what is one loop over an ordered list. Design points: (a) any
OpenAI-compatible endpoint plugs in via `.env`; (b) failed provider is
benched (`_down_until`) so later calls skip it fast; (c) if EVERY
provider is rate-limited with a short retry hint, sleep once and retry
— an answer 20s late beats an error bubble.

**D-010 — Second Groq entry (`groq-alt`, gpt-oss-20b) on the same key.**
Discovery: Groq free-tier TPM limits are per *model*, not per key. A
second model = a second 8k-token bucket for free. Trade-off accepted:
20b is a weaker analyst than 120b; it's the overflow lane, not the
default.

**D-011 — Token diet: `MAX_TOOL_ROUNDS` 6→4, result cap 9000→4000.**
Observed: single questions burned >8k TPM (limit) on Groq; the second
LLM call of a turn was dying. Halving payloads keeps a full teardown
under one TPM window. Cost: the model sees truncated tool output —
acceptable because tools return the head of ranked/sorted data.

**D-012 — Gemini demoted to optional third fallback.**
User's new AI Studio key landed on prepaid billing with zero credits
(Google requires prepay for new keys as of 2026); also
`gemini-2.5-flash` 404s for new users (shutdown 2026-10-16), so the
default is `gemini-3.5-flash`. Chain runs fine on the two Groq buckets;
Gemini activates only if `GEMINI_API_KEY` is set and funded.

**D-013 — Markdown rendered client-side with a hand-rolled ~60-line
renderer, and tables banned in the system prompt.**
Alternatives: `marked` + DOMPurify via CDN. Rejected: two third-party
scripts to render five constructs (bold, headers, bullets, code,
tables). Own renderer escapes HTML *first* (XSS-safe by construction,
verified with a script-injection test). Prompt-side, markdown tables
are banned — a 6-column ASCII table can never render well in a 700px
chat bubble; "Label: value" lines can.

**D-014 — 2026-08: repo restructured to backend/ + frontend/ packages.**
Alternatives: keep flat (35 files in one dir), or full src-layout with
setup.py. Chosen middle: `backend/app/{core,data_sources,analysis,
analyst,portfolio,alerts}` — grouped by domain, no packaging ceremony.
All imports rewritten to absolute `app.*` form. Old Streamlit UI →
`legacy/`, utilities → `scripts/` with sys.path bootstraps.

**D-015 — `app/core/paths.py` as the single path authority.**
Root cause of two real bugs was cwd-relative paths (`.env` not found
when uvicorn started elsewhere; the code comment in old config.py
records a phantom-database bug from the same cause). Now every file
location derives from anchors computed off `__file__`. Rule going
forward: no bare relative paths anywhere.

**D-016 — Frontend cache-busting via mtime query strings, including
`analyst.js`/`ui-fx.js`; service worker stays pass-through.**
A caching SW plus cached JS caused "my edit does nothing" confusion.
Decision: SW exists only for PWA installability and explicitly caches
nothing; the root handler stamps `?v=mtime` on every script/style.

**D-017 — 2026-08: strategy/metric "i" explanations live client-side
in `ui-fx.js` (INFO dict), not the database.**
Alternatives: serve from a new API route. This text is static teaching
content coupled to UI labels; shipping it in JS means zero round trips,
and the MutationObserver attaches buttons to anything rendered later.
Backend already exposes short `desc` per strategy — the UI dict holds
the *longer* significance notes. If the two drift, backend labels win.

**D-018 — Visual layer additive-only (`ui-fx.js` + CSS appendix).**
Design tokens adapted from Metric Flow (designmd.ai, MIT): vibrancy
reserved for data, subtle elevation, dense layout. Lenis (MIT) loaded
from CDN with `defer` and a feature check — offline or blocked, the app
scrolls natively and everything still works. `prefers-reduced-motion`
honored. Hard rule: deleting ui-fx.js and the CSS appendix must never
break a feature.

**D-019 — Peer comparison: discovered `research.peers()` already
existed with a UI button; the newly written duplicate was deleted.**
Lesson encoded: before building a roadmap feature, grep routes AND
`research.py`/`extras.py` — this codebase has more surface than its
file names suggest. The existing implementation stays canonical.

**D-020 — Verdict card synthesizes, never recommends.**
`verdict.py` merges checklist tier, composite rank, 200-DMA state, and
active signals weighted by their own base rates into strong/mixed/weak
"case" tiers with ≤3 reasons per side. Hard rule: no "BUY"/"SELL"
strings anywhere — the card's value is forcing both evidence lists into
one glance; a directive word would make users skip them.

**D-021 — Position sizer is pure client-side arithmetic.**
`shares = capital × risk% ÷ (entry − stop)`. No API round trip, no
persistence — the barrier to sizing was never computation, it was
having the field in front of you at decision time. A >25% concentration
warning is inlined; beta-adjustment deferred until someone asks.

**D-022 — Buy thesis stored on the lot, replayed at removal.**
`holdings.thesis` column (nullable migration via `ensure_v2_columns`),
optional input in the add form, shown italic under each lot, and an
interstitial on remove: "you bought because X — has that broken?"
reusing the existing `dlgForm` dialog. Selling for reasons unrelated to
the buy reason is the best-documented retail failure mode; one field
and one dialog is the cheapest possible countermeasure.

**D-023 — What-changed card uses `users.last_seen` + the existing
journal table; no snapshot infrastructure yet.**
Full diffing (score/verdict flips) needs nightly snapshots — deferred.
v1 ships the highest-value slice: signals fired since your previous
visit, and an explicit "nothing changed — doing nothing is a position"
state. Snapshot tables are the natural next entry in this log.

**D-024 — Modal scroll bug: Lenis `prevent` callback, not CSS hacks.**
Root cause: Lenis (added in D-018) intercepts wheel events globally, so
scrolling inside the stock dialog moved the page behind it. Fix at the
source: `prevent: node => node.closest("#drawer, .dlg-overlay, …")`
plus `overscroll-behavior: contain` as belt-and-braces. Light-mode
hover contrast fixed with theme-scoped overrides (`.btn:hover` was
forcing white text onto light surfaces).

**D-025 — Regression from D-022: two more `get_holdings` unpack sites
were hiding in `main.py` (detail route line ~685, refresh helper ~474)
and crashed `/api/detail` with "too many values to unpack".**
Root cause: widening a core query's column list while fixing consumers
by grep of one file instead of the whole tree. Rule added: when a
`database.py` SELECT changes shape, grep the FULL repo for the function
name and audit every tuple-unpack before shipping — or better, return
dicts from new query helpers so added columns can never break callers.

**D-026 — "i" coverage extended to candle patterns, backtest rule
rows, and AI-Lab stat cards; matcher now scans `td:first-child`.**
Pattern/rule explanations deliberately teach skepticism ("folklore is
direction; base rates are evidence", "never rank rules by win rate")
rather than definitions alone — the info layer's job is decision
hygiene, not a glossary. Exact-text matching keeps false positives at
zero; the cost (a renamed label silently loses its ⓘ) is accepted and
caught by eye.

**D-027 — Nav rail overflows on short windows once the Analyst button
is injected; fixed with rail scroll + tighter spacing under 820px,
not by shrinking the nav.**
`overflow-y: auto` with a 4px thumb keeps every element reachable at
any window height. Hiding footer items or collapsing nav labels was
rejected: the status line ("N stocks · signals today") and the
"signals are prompts, not instructions" note are load-bearing copy.

**D-028 — Analyst learns mutual funds via a `mutual_funds` tool over
existing NAV plumbing (`charts.load_mf_series` + `mf_stats`), not a
new data path.**
Returns per-fund stats with an optional name/scheme filter, an honest
"no NAV stored yet — run a refresh" state, and a system-prompt line so
the model reaches for the tool instead of claiming it lacks fund data.
Discovered en route: `get_watchlist` returns positional tuples — same
foot-gun class as D-025; the dict-rows refactor gains another argument.
