import { api } from "./api";

/* eslint-disable @typescript-eslint/no-explicit-any */
// /api/detail/{symbol} sends its chart data as columns (format 2): one date
// list plus one number list per line, instead of repeating every date in
// every one of 13 series. That is about a quarter of the old ~1 MB per
// stock. getDetail() rebuilds the old shape, so every page that reads
// candles / sma_fast / indicators keeps working unchanged.

type Pt = { time: string; value: number };

function line(time: string[], values: (number | null)[]): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < time.length; i++) { const v = values[i]; if (v != null) out.push({ time: time[i], value: v }); }
  return out;
}

export function expandDetail(d: any): any {
  if (!d || d.format !== 2 || !d.series) return d;   // already the old shape
  const s = d.series; const t: string[] = s.time;
  const candles = t.map((time, i) => ({ time, open: s.open[i], high: s.high[i], low: s.low[i], close: s.close[i] }));
  const volume: { time: string; value: number; color: string }[] = [];
  for (let i = 0; i < t.length; i++) {
    const v = s.volume[i], o = s.open[i], c = s.close[i];
    if (v == null || o == null || c == null) continue;
    // s.up is computed from the exact prices on the server
    const up = s.up ? s.up[i] === 1 : c >= o;
    volume.push({ time: t[i], value: v, color: up ? "rgba(34,197,94,0.35)" : "rgba(239,68,68,0.35)" });
  }
  const { series: _drop, ...rest } = d;
  return {
    ...rest,
    candles,
    sma_fast: line(t, s.sma_fast), sma_slow: line(t, s.sma_slow), rsi: line(t, s.rsi),
    indicators: {
      ema20: line(t, s.ema20), bb_upper: line(t, s.bb_upper), bb_lower: line(t, s.bb_lower),
      macd: line(t, s.macd), macd_signal: line(t, s.macd_signal), volume,
    },
  };
}

export const getDetail = (symbol: string) =>
  api.get<any>(`/api/detail/${encodeURIComponent(symbol)}`).then(expandDetail);

// The stored data refreshes once a day, so a stock opened again in the same
// session can be shown from the browser's copy instead of asking the phone.
export const DETAIL_STALE_MS = 10 * 60_000;
