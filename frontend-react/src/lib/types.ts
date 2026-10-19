export type { NavItem } from "./nav";
// Shapes returned by the existing backend (backend/app/main.py).
// Fields the UI does not use yet are left out on purpose.

export interface Me {
  user: string | null;
  role?: "admin" | "user";
  email?: string | null;
  email_verified?: boolean;
  has_google?: boolean;
  analyst?: { used: number; limit: number | null };
  telegram_linked?: boolean;
  sessions?: number;
}
export interface AuthStatus {
  has_users: boolean;
  google_client_id?: string;
  email_configured?: boolean;
  invite_required?: boolean;
  google_invite_required?: boolean;
}

export interface TapeItem { label: string; symbol: string; last: number; pct: number | null; held: boolean }

export interface HomeData {
  earnings_week: { symbol: string; date: string }[];
  data_through: string | null;
  advancing: number;
  declining: number;
  movers: { symbol: string; last: number; pct: number }[];
  signals_today: number;
  portfolio: PortfolioTotals | null;
  journal: { created: string; symbol: string; signal: string; price: number | null }[];
}

export interface WatchItem {
  id: number;
  type: "stock" | "etf" | "mf";
  symbol: string; // null for mutual funds at runtime, always guard
  scheme_code: string | number | null;
  label: string | null;
  tag: string | null;
  spark: number[];
  last: number | null;
  pct: number | null;
  mcap: number | null;
  source: string | null;
}
export interface WatchlistData { items: WatchItem[]; last_date: string | null; signals_today: number }

export interface PortfolioTotals {
  invested: number;
  current: number;
  pnl: number;
  pnl_pct?: number;
  day_pct?: number;
  dividends?: number;
  unpriced?: number;
}
export interface Holding {
  Symbol: string;
  Qty: number;
  Last: number | null;
  Invested: number;
  Current: number | null;
  "P&L": number | null;
  "P&L %": number | null;
  "Weight %"?: number | null;
  [key: string]: unknown;
}
export interface PortfolioData {
  holdings: Holding[];
  totals: PortfolioTotals | null;
  allocation: unknown[];
  sectors: unknown[];
}

export interface Candle { time: string; open: number; high: number; low: number; close: number }
export interface LinePoint { time: string; value: number }
export interface Checklist { pros: string[]; cons: string[]; notes: string[]; passed: number; applicable: number; tier: string; tier_text: string }
export interface StockDetail {
  symbol: string;
  stats: Record<string, number | string | null>;
  candles: Candle[];
  sma_fast: LinePoint[];
  sma_slow: LinePoint[];
  rsi: LinePoint[];
  fundamentals: Record<string, number | string | null> | null;
  checklist: Checklist | null;
}
export interface Verdict { symbol: string; tier: "strong" | "mixed" | "weak" | string; score: number; for: Evidence[]; against: Evidence[]; note: string }
export type Evidence = string | { text: string; source?: string };

export interface SymbolHit { symbol: string; name: string; exch?: string }
export interface RefreshStatus { running: boolean; done: boolean; log: string[] }
