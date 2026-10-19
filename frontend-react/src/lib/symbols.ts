import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { WatchlistData } from "./types";

// Some endpoints return "TCS" while the database key is "TCS.NS".
// Resolve a bare ticker through the watchlist, falling back to NSE.
export function useResolvedSymbol(raw: string): { symbol: string; ready: boolean } {
  const bare = !raw.includes(".");
  const wl = useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchlistData>("/api/watchlist"), enabled: bare, staleTime: 5 * 60_000 });
  if (!bare) return { symbol: raw.toUpperCase(), ready: true };
  if (wl.isLoading) return { symbol: raw, ready: false };
  // Mutual funds in the watchlist have no symbol, so guard against null.
  // The same company can be listed twice (TCS.NS and TCS.BO): prefer the one that has prices.
  const matches = (wl.data?.items ?? []).filter((i) => i.symbol && i.symbol.split(".")[0].toUpperCase() === raw.toUpperCase());
  const hit = matches.find((i) => i.last != null) ?? matches[0];
  return { symbol: hit ? hit.symbol : `${raw.toUpperCase()}.NS`, ready: true };
}

export function useWatchSymbols() {
  const wl = useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchlistData>("/api/watchlist"), staleTime: 5 * 60_000 });
  // A symbol can sit on the list twice (added twice, or as both stock and
  // ETF). Repeats would show up as identical rows in every picker.
  return [...new Set((wl.data?.items ?? []).filter((i) => i.type !== "mf" && i.symbol).map((i) => i.symbol))];
}
