import { useEffect, useRef } from "react";
import { createChart, ColorType, LineStyle } from "lightweight-charts";

export interface Series { name: string; color: string; dashed?: boolean; data: { time: string; value: number }[] }

export function SeriesChart({ series, height = 260, legend = true, guides }: { series: Series[]; height?: number; legend?: boolean; guides?: number[] }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current || series.every((s) => s.data.length === 0)) return;
    const css = getComputedStyle(document.documentElement);
    const token = (n: string) => css.getPropertyValue(n).trim();
    const chart = createChart(el.current, {
      height,
      localization: { locale: "en-IN", priceFormatter: (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 }).format(v) },
      layout: { attributionLogo: false, background: { type: ColorType.Solid, color: "transparent" }, textColor: token("--text-3"), fontFamily: "Onest, system-ui, sans-serif" },
      grid: { vertLines: { visible: false }, horzLines: { color: token("--line") } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    });
    const made = series.map((s) => { const ls = chart.addLineSeries({ color: s.color.startsWith("--") ? token(s.color) : s.color, lineWidth: 2, lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: false }); ls.setData(s.data); return ls; });
    (guides ?? []).forEach((g) => made[0]?.createPriceLine({ price: g, color: token("--text-3"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: "" }));
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => el.current && chart.applyOptions({ width: el.current.clientWidth }));
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [series, height, guides]);
  return (
    <div>
      {legend && <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginBottom: 8 }}>
        {series.map((s) => (<span key={s.name} className="secondary" style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13 }}><span style={{ width: 14, height: 3, borderRadius: 2, background: s.color.startsWith("--") ? `var(${s.color})` : s.color }} />{s.name}</span>))}
      </div>}
      <div ref={el} style={{ width: "100%", height }} role="img" aria-label="Chart" />
    </div>
  );
}
