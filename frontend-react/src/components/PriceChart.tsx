import { useEffect, useRef } from "react";
import { createChart, ColorType, LineStyle } from "lightweight-charts";
import type { Candle, LinePoint } from "../lib/types";

export interface Overlays {
  sma?: { fast?: LinePoint[]; slow?: LinePoint[] };
  ema20?: LinePoint[];
  bollinger?: { upper?: LinePoint[]; lower?: LinePoint[] };
  volume?: { time: string; value: number; color?: string }[];
}

// TradingView lightweight-charts (v4), the library the old frontend used.
// Colors come from the CSS tokens, so light and dark themes both work.
export function PriceChart({ candles, overlays = {}, mode, height = 340 }: { candles: Candle[]; overlays?: Overlays; mode: "Line" | "Candles"; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current || candles.length === 0) return;
    const css = getComputedStyle(document.documentElement);
    const token = (n: string) => css.getPropertyValue(n).trim();
    const chart = createChart(el.current, {
      height, localization: { locale: "en-IN", priceFormatter: (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 }).format(v) },
      layout: { attributionLogo: false, background: { type: ColorType.Solid, color: "transparent" }, textColor: token("--text-3"), fontFamily: "Onest, system-ui, sans-serif" },
      grid: { vertLines: { visible: false }, horzLines: { color: token("--line") } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false }, crosshair: { mode: 1 },
    });
    if (mode === "Candles") {
      chart.addCandlestickSeries({ upColor: token("--gain"), downColor: token("--loss"), borderVisible: false, wickUpColor: token("--gain"), wickDownColor: token("--loss") }).setData(candles);
    } else {
      chart.addAreaSeries({ lineColor: token("--action"), topColor: "rgba(36,86,230,0.12)", bottomColor: "rgba(36,86,230,0)", lineWidth: 2 }).setData(candles.map((c) => ({ time: c.time, value: c.close })));
    }
    const line = (data: LinePoint[] | undefined, color: string, dashed = false) => { if (data?.length) chart.addLineSeries({ color, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }).setData(data); };
    line(overlays.sma?.fast, token("--action")); line(overlays.sma?.slow, "#B7791F");
    line(overlays.ema20, "#7C4DDB");
    line(overlays.bollinger?.upper, token("--slate"), true); line(overlays.bollinger?.lower, token("--slate"), true);
    if (overlays.volume?.length) {
      const v = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", priceLineVisible: false, lastValueVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      v.setData(overlays.volume.map((x) => ({ time: x.time, value: x.value, color: x.color })));
    }
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => el.current && chart.applyOptions({ width: el.current.clientWidth }));
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [candles, overlays, mode, height]);
  return <div ref={el} style={{ width: "100%", height }} role="img" aria-label="Price chart" />;
}
