# Ledgerline frontend (React)

The new UI for the stock and mutual fund app. It talks to the existing FastAPI
backend through the same `/api` routes and the same session cookie. Design
source: the "Stocks and mutual funds app screens" canvas.

## Run it

```bash
# 1. backend, as before (from the project root)
./run.sh                      # FastAPI on http://localhost:8000

# 2. frontend, in a second terminal
cd frontend-react
npm install
npm run dev                   # http://localhost:5173, proxies /api to :8000
```

For production: `npm run build`, then FastAPI serves `frontend-react/dist`
(see `backend_changes/README.md`). The old UI stays reachable at `/old`.

## What is built

Every page below runs against the real backend. All 22 routes were loaded in a
headless browser against a test database with zero console errors.

| Route | Page | Backend calls |
| --- | --- | --- |
| `/login` | Log in, and first-run admin setup | `/api/auth/status`, `/api/auth/login`, `/api/auth/setup` |
| `/` | Home: movers, results this week, tier changes, track record, journal | `/api/home`, `/api/tiers`, `/api/scorecard` |
| `/watchlists` | Add (stock, ETF, fund), remove, tag filter, sparklines | `/api/watchlist`, `/api/watchlist/add` |
| `/stocks/:symbol` | Verdict, chart, At a glance, your holding, key numbers. Research tab: checklist, base rates, patterns, events, peers, delivery, depth, shareholding, options, documents, notes | `/api/detail`, `/api/verdict`, `/api/patterns`, `/api/events`, `/api/peers`, `/api/notes`, and the optional sources |
| `/portfolio` | Totals, value against invested and NIFTYBEES, allocation, sectors, holdings with thesis and tier, CSV export | `/api/portfolio` |
| `/portfolio/tools` | Add, sell (shows your thesis), position size, rebalance, what-if, dividends | `/api/portfolio`, `/api/sell`, `/api/dividends`, `/api/position-size` |
| `/funds` | Search and track funds, rolling returns table, SIPs, lump-sum holdings | `/api/funds`, `/api/mf/search`, `/api/mf/add`, `/api/sips`, `/api/mf/holdings` |
| `/screener` | Universes, plain-English ask, query language, ready-made screens, near misses on zero results | `/api/universes`, `/api/nlq`, `/api/query` |
| `/research/*` | AI Lab, Backtest, Scorecard, Journal | `/api/rankings`, `/api/predict`, `/api/strategies`, `/api/backtest`, `/api/backtest-all`, `/api/scorecard`, `/api/journal` |
| `/analyst` | Chat with tools-used chips, PDF upload per stock, provider status | `/api/analyst/*`, `/api/docs/*` |
| `/alerts`, `/compare`, `/settings` | Alerts, side-by-side compare, theme and ribbon speed | `/api/alerts`, `/api/detail` |
| `/more/*` | Calculators, Learn glossary, Reports (tax), Data and admin (refresh, NSE sync, data doctor, users, digest) | `/api/taxreport`, `/api/doctor/*`, `/api/nse/*`, `/api/auth/add-user`, `/api/digest` |

**News**, **Results calendar** and **IPOs and new funds** are built on the new
`backend/app/feeds/` module (see `backend_changes/README.md`).

## Settings, search and fund pages

- **Settings** (`pages/Settings.tsx`, `lib/settings.ts`) follows the canvas: Explanations, Data and display, Notifications, Appearance (theme with Match device, top bar or left sidebar, gain and loss colors, ribbon on/off, what it shows, speed, table density) and Account. Every control works and saves in the browser.
- **Search** (`components/Search.tsx`) groups results into Stocks, Mutual funds, Screens, Go to and News, with prices for anything you watch, match highlighting, recent searches and keyboard control.
- **Fund page** (`pages/FundDetail.tsx`, `/funds/:scheme`): NAV chart against NIFTYBEES, returns table, rolling 1Y and 3Y ranges, fund facts, "If you had invested" replayed on real NAVs, and your SIPs and holdings. Expense ratio, fund size, manager and holdings are not in the free AMFI feed, so they are left out.

## Name and logo

`src/lib/brand.ts` holds the product name, tagline and which of the four logo
marks to use (`line`, `loupe`, `scale`, `streak`). Change it there and rebuild.

## Chart attribution

Charts use TradingView Lightweight Charts (Apache 2.0). Its licence asks for
an attribution notice and a link to tradingview.com somewhere users can see.
The logo on each chart is switched off (`attributionLogo: false`) and the
notice sits at the bottom of the Settings page instead. Keep one of the two.

## Carried over from the previous frontend

- **Info buttons.** All 54 plain-language explanations from `ui-fx.js` live in `src/lib/info.json`. `<Term>` and `<InfoTip>` attach the "i" to any label whose text matches a key, including table headers and stat labels.
- **Quick look.** Clicking a stock in the ribbon, Home, Watchlists or Portfolio opens a side panel (`components/Peek.tsx`) so you keep your place. "Open full page" goes to `/stocks/:symbol`. Ctrl-click opens the page directly.
- **Notifications.** Every failed action shows one. Successful actions show one when the mutation sets `meta: { ok: "..." }`. See `main.tsx` and `components/Toast.tsx`.
- **Chart indicators.** SMA 50/200, Volume, EMA 20, Bollinger, MACD and RSI 14 as toggles, plus the 52-week range bar.
- **Watchlists.** Autocomplete add for stocks, ETFs and funds, tag editing, drag to reorder, download history, what changed since your last visit.
- **Portfolio.** Overview, Tools and Reports as one section. Lots when selling, CSV import and export, XIRR, gain by holding.

## Layout

```
src/
  main.tsx            providers: React Query, Router, theme
  App.tsx             routes and the auth guard
  lib/api.ts          fetch wrapper (cookies, JSON errors)
  lib/types.ts        response shapes from backend/app/main.py
  lib/format.ts       rupee, lakh and crore, percent
  lib/nav.ts          the navbar, sub-navs, and what each unbuilt page needs
  components/         AppShell (ribbon, header, tabs, footer), PriceChart, ui primitives, icons
  pages/              one file per page
  styles/tokens.css   colors, type, radius. Dark theme overrides the same names
  styles/global.css   every class used by the components
```

## Conventions

- Fetch with TanStack Query. After a change, `invalidateQueries` the keys it affects.
- Colors only through the CSS variables in `tokens.css`. Green and red mean gain and loss, nothing else.
- Every number on screen goes through `lib/format.ts`.
- Watchlist rows for mutual funds have `symbol: null`. Always guard before calling string methods on it.
- Some endpoints return a bare ticker ("TCS"). `useResolvedSymbol` maps it to the listing that has prices.
