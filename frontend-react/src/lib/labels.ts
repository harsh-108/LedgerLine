// Turn backend codes into words people read.
const SIGNALS: Record<string, string> = {
  GOLDEN_CROSS: "Golden cross (50-day rose above 200-day)",
  DEATH_CROSS: "Death cross (50-day fell below 200-day)",
  RSI_OVERSOLD: "RSI dropped below 30",
  RSI_OVERBOUGHT: "RSI rose above 70",
  NEW_52W_HIGH: "New 52-week high",
  NEW_52W_LOW: "New 52-week low",
  PRICE_ALERT: "Price alert triggered",
  VOLUME_SPIKE: "Unusual volume",
};
export function signalLabel(code: string | null | undefined): string {
  if (!code) return "";
  return SIGNALS[code] ?? code.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

// The app's tiers shown as calls (backend analysis.ACTION). Stored and
// graded as strong / mixed / weak; people read Buy / Hold / Sell.
export const TIER_LABEL: Record<string, string> = { strong: "Buy", mixed: "Hold", weak: "Sell" };
export const tierKind = (t?: string | null) => (t === "strong" ? "gain" : t === "weak" ? "loss" : t === "mixed" ? "guide" : undefined);

export const CALL_KIND: Record<string, string> = { verdict: "Verdict card", checklist: "Checklist tier", ml_nextday: "Next-day model" };
