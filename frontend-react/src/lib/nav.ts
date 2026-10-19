// The navbar from the mockups. `ready: false` routes render the ComingSoon
// page, which names the mockup screen and backend endpoints to port next.
export interface NavItem { label: string; to: string; ready?: boolean; mock?: string; endpoints?: string[]; adminOnly?: boolean }

export const TABS: NavItem[] = [
  { label: "Home", to: "/" , ready: true },
  { label: "Watchlists", to: "/watchlists", ready: true },
  { label: "Portfolio", to: "/portfolio", ready: true },
  { label: "Mutual Funds", to: "/funds", mock: "Funds tracker", endpoints: ["/api/funds", "/api/mf/search", "/api/sips", "/api/mf/holdings"] },
  { label: "Screener", to: "/screener", mock: "Screener, filters and query mode", endpoints: ["/api/query", "/api/nlq", "/api/universes"] },
  { label: "Research", to: "/research/ai-lab", mock: "AI Lab", endpoints: ["/api/rankings", "/api/predict/{symbol}"] },
  { label: "Analyst", to: "/analyst", mock: "AI analyst", endpoints: ["/analyst/chat", "/analyst/status", "/docs/upload"] },
  { label: "News", to: "/news", mock: "News and in-app reader", endpoints: ["/api/news (new)"] },
  { label: "More", to: "/more/calculators", mock: "Calculators and goals", endpoints: ["/api/position-size"] },
];

export const PORTFOLIO: NavItem[] = [
  { label: "Overview", to: "/portfolio" },
  { label: "Tools: add, sell, size, rebalance", to: "/portfolio/tools" },
  { label: "Reports", to: "/more/reports" },
];

export const RESEARCH: NavItem[] = [
  { label: "AI Lab", to: "/research/ai-lab", mock: "AI Lab", endpoints: ["/api/rankings", "/api/predict/{symbol}"] },
  { label: "Backtest", to: "/research/backtest", mock: "Backtest", endpoints: ["/api/strategies", "/api/backtest/{symbol}", "/api/backtest-all/{symbol}"] },
  { label: "Scorecard", to: "/research/scorecard", mock: "Scorecard", endpoints: ["/api/scorecard", "/api/scorecard/track"] },
  { label: "Journal", to: "/research/journal", mock: "Journal", endpoints: ["/api/journal", "/api/notes"] },
];

export const MORE: NavItem[] = [
  { label: "Calculators and goals", to: "/more/calculators", mock: "Calculators and goals", endpoints: ["/api/position-size"] },
  { label: "IPOs and new funds", to: "/more/ipos", mock: "IPOs and new fund offers", endpoints: ["/api/ipos (new)"] },
  { label: "Results calendar", to: "/more/calendar", mock: "Results calendar", endpoints: ["/api/events/{symbol}"] },
  { label: "Learn", to: "/more/learn", mock: "Learn hub and glossary", endpoints: [] },
  { label: "Data and admin", to: "/more/admin", mock: "Data and admin", endpoints: ["/api/doctor/report", "/api/nse/status", "/api/universe/status", "/api/admin/users"], adminOnly: true },
];

export const OTHER: NavItem[] = [
  { label: "Alerts", to: "/alerts", mock: "Alerts center", endpoints: ["/api/alerts"] },
  { label: "Settings", to: "/settings", mock: "Settings", endpoints: ["/api/settings (new)"] },
  { label: "Compare", to: "/compare", mock: "Compare", endpoints: ["/api/detail/{symbol}", "/api/peers/{symbol}"] },
];
