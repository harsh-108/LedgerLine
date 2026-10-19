"""
Plotly figure builders for the Details tab.

- stock/ETF: candlestick + SMA overlays, RSI panel, volume panel, stats
- mutual fund: NAV growth line + rolling drawdown, stats with CAGR
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.core import config
from app.core import database as db
from app.core import memo
from app.analysis.scanner import compute_indicators


# ---- visual identity (matches theme.py) ----
INK, PANEL, EDGE = "#0B0F1A", "#121829", "#1F2A44"
TEXT, MUTED, MARIGOLD = "#E8ECF4", "#8A94AC", "#F2A93B"
UP, DOWN = "#2FC98C", "#F0525F"

def _style(fig):
    fig.update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PANEL,
        font=dict(family="IBM Plex Mono, monospace", color=TEXT, size=11),
        hoverlabel=dict(bgcolor=INK, font_family="IBM Plex Mono, monospace"),
    )
    fig.update_xaxes(gridcolor=EDGE, zerolinecolor=EDGE, linecolor=EDGE)
    fig.update_yaxes(gridcolor=EDGE, zerolinecolor=EDGE, linecolor=EDGE)
    for ann in fig.layout.annotations:
        ann.font = dict(family="Space Grotesk, sans-serif", size=13, color=MUTED)
    return fig

PERIODS = {"3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260, "Max": None}


# ---------------------------------------------------------------- helpers
def _returns(series: pd.Series):
    """Simple % returns over standard lookbacks, where enough history exists."""
    out = {}
    for label, days in [("1M", 21), ("6M", 126), ("1Y", 252), ("3Y", 756)]:
        if len(series) > days:
            out[label] = (series.iloc[-1] / series.iloc[-days - 1] - 1) * 100
    return out


def _cagr(series: pd.Series):
    years = (series.index[-1] - series.index[0]).days / 365.25
    if years < 1:
        return None
    return ((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1) * 100


# ------------------------------------------------------------ stocks/ETFs
@memo.memoize("stock_df", max_items=80)
def load_stock_df(symbol):
    rows = db.load_ohlc(symbol)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    ind = compute_indicators(df["close"])
    df["sma_fast"], df["sma_slow"], df["rsi"] = (
        ind["sma_fast"], ind["sma_slow"], ind["rsi"]
    )
    return df


def stock_stats(df):
    close = df["close"]
    last_yr = df.tail(252)
    stats = {
        "Last close": f"{close.iloc[-1]:,.2f}",
        "52w high": f"{last_yr['high'].max():,.2f}",
        "52w low": f"{last_yr['low'].min():,.2f}",
        "RSI (14)": f"{df['rsi'].iloc[-1]:.1f}",
        "Trend": "UP" if df["sma_fast"].iloc[-1] > df["sma_slow"].iloc[-1] else "DOWN",
    }
    for label, val in _returns(close).items():
        stats[f"{label} return"] = f"{val:+.1f}%"
    return stats


def stock_figure(df, title, period_days=None):
    d = df.tail(period_days) if period_days else df
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
        subplot_titles=(title, "RSI (14)", "Volume"),
    )
    fig.add_trace(go.Candlestick(
        x=d.index, open=d["open"], high=d["high"],
        low=d["low"], close=d["close"], name="Price",
        increasing_line_color=UP, increasing_fillcolor=UP,
        decreasing_line_color=DOWN, decreasing_fillcolor=DOWN,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=d.index, y=d["sma_fast"], name=f"SMA {config.SMA_FAST}",
        line=dict(width=1.4, color=MARIGOLD),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=d.index, y=d["sma_slow"], name=f"SMA {config.SMA_SLOW}",
        line=dict(width=1.4, color=MUTED),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d["rsi"], name="RSI",
                             line=dict(width=1.2, color=MARIGOLD)), row=2, col=1)
    fig.add_hline(y=config.RSI_OVERBOUGHT, line_dash="dot", line_color=DOWN, opacity=0.6, row=2, col=1)
    fig.add_hline(y=config.RSI_OVERSOLD, line_dash="dot", line_color=UP, opacity=0.6, row=2, col=1)

    vol_colors = [UP if c >= o else DOWN for o, c in zip(d["open"], d["close"])]
    fig.add_trace(go.Bar(x=d.index, y=d["volume"], name="Volume",
                         marker_color=vol_colors, opacity=0.55,
                         marker_line_width=0), row=3, col=1)

    fig.update_layout(
        height=700, xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.06),
        margin=dict(l=40, r=20, t=60, b=30),
    )
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    return _style(fig)


# ------------------------------------------------------------ mutual funds
@memo.memoize("mf_series", max_items=60)
def load_mf_series(scheme_code):
    rows = db.load_navs(scheme_code)
    if not rows:
        return None
    s = pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]))
    return s.sort_index()


def mf_stats(nav: pd.Series):
    stats = {"Latest NAV": f"{nav.iloc[-1]:,.2f}"}
    for label, val in _returns(nav).items():
        stats[f"{label} return"] = f"{val:+.1f}%"
    cagr = _cagr(nav)
    if cagr is not None:
        stats["CAGR (full history)"] = f"{cagr:+.1f}%"
    running_max = nav.cummax()
    stats["Max drawdown"] = f"{((nav / running_max - 1).min() * 100):.1f}%"
    return stats


def mf_figure(nav: pd.Series, title, period_days=None):
    d = nav.tail(period_days) if period_days else nav
    drawdown = (d / d.cummax() - 1) * 100
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.05,
        subplot_titles=(title, "Drawdown from peak (%)"),
    )
    fig.add_trace(go.Scatter(x=d.index, y=d.values, name="NAV",
                             line=dict(width=1.6, color=MARIGOLD)), row=1, col=1)
    fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown.values, name="Drawdown",
                             fill="tozeroy", line=dict(width=1, color=DOWN),
                             fillcolor="rgba(240,82,95,0.18)"), row=2, col=1)
    fig.update_layout(
        height=560, showlegend=False,
        margin=dict(l=40, r=20, t=60, b=30),
    )
    return _style(fig)


def allocation_pie(df):
    """Holdings allocation by current value."""
    d = df.dropna(subset=["Current"])
    fig = go.Figure(go.Pie(
        labels=d["Symbol"], values=d["Current"], hole=0.55,
        textinfo="label+percent", textfont_size=11,
        marker=dict(line=dict(color=INK, width=2)),
    ))
    fig.update_layout(height=360, showlegend=False,
                      margin=dict(l=10, r=10, t=10, b=10))
    return _style(fig)


def corr_heatmap(corr):
    labels = [s.split(".")[0] for s in corr.columns]
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=labels, y=labels,
        colorscale=[[0, DOWN], [0.5, PANEL], [1, UP]],
        zmin=-1, zmax=1, text=corr.values, texttemplate="%{text:.2f}",
        textfont=dict(size=9),
    ))
    fig.update_layout(height=max(380, 26 * len(labels)),
                      margin=dict(l=10, r=10, t=10, b=10))
    return _style(fig)


def equity_curves(curves, title):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curves.index, y=curves["hold_curve"],
                             name="Buy & hold", line=dict(width=1.4, color=MUTED)))
    fig.add_trace(go.Scatter(x=curves.index, y=curves["strat_curve"],
                             name="Golden-cross strategy",
                             line=dict(width=1.6, color=MARIGOLD)))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=MUTED)),
        height=420, legend=dict(orientation="h", y=1.08),
        margin=dict(l=40, r=20, t=60, b=30),
        yaxis_title="Growth of ₹1",
    )
    return _style(fig)
