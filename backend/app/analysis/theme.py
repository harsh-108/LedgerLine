"""
Visual identity for the tracker.

Palette ("ink & marigold" terminal):
  INK      #0B0F1A  page background, near-black indigo
  PANEL    #121829  cards / surfaces
  EDGE     #1F2A44  hairline borders
  TEXT     #E8ECF4  primary text
  MUTED    #8A94AC  secondary text
  MARIGOLD #F2A93B  the one accent (actions, highlights)
  UP       #2FC98C  gains only
  DOWN     #F0525F  losses only

Type: Space Grotesk for display/UI, IBM Plex Mono for every number.
Signature: a scrolling ticker tape of the watchlist under the header.
"""

import streamlit as st

INK = "#0B0F1A"
PANEL = "#121829"
EDGE = "#1F2A44"
TEXT = "#E8ECF4"
MUTED = "#8A94AC"
MARIGOLD = "#F2A93B"
UP = "#2FC98C"
DOWN = "#F0525F"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp {{
    font-family: 'Space Grotesk', sans-serif;
}}
.stApp {{ background: {INK}; }}

/* ---------- hero ---------- */
.hero {{
    padding: 6px 0 2px 0;
}}
.hero .kicker {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem; letter-spacing: 0.22em;
    color: {MARIGOLD}; text-transform: uppercase;
}}
.hero h1 {{
    font-size: 2.1rem; font-weight: 700; margin: 2px 0 4px 0;
    color: {TEXT}; letter-spacing: -0.015em;
}}
.hero .sub {{ color: {MUTED}; font-size: 0.92rem; margin-bottom: 10px; }}

/* ---------- ticker tape ---------- */
.tape-wrap {{
    overflow: hidden; white-space: nowrap;
    border-top: 1px solid {EDGE}; border-bottom: 1px solid {EDGE};
    background: {PANEL};
    padding: 7px 0; margin: 4px 0 18px 0;
}}
.tape {{
    display: inline-block; padding-left: 100%;
    animation: tape-scroll var(--tape-duration, 150s) linear infinite;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem;
}}
.tape-wrap:hover .tape {{ animation-play-state: paused; }}
.tape .sym {{ color: {TEXT}; font-weight: 600; }}
.tape .px  {{ color: {MUTED}; margin-left: 6px; }}
.tape .up   {{ color: {UP};   margin-left: 6px; }}
.tape .down {{ color: {DOWN}; margin-left: 6px; }}
.tape .sep {{ color: {EDGE}; margin: 0 14px; }}
@keyframes tape-scroll {{
    0%   {{ transform: translateX(0); }}
    100% {{ transform: translateX(-100%); }}
}}
@media (prefers-reduced-motion: reduce) {{
    .tape {{ animation: none; padding-left: 0; }}
}}

/* ---------- metric cards ---------- */
div[data-testid="stMetric"] {{
    background: {PANEL};
    border: 1px solid {EDGE};
    border-radius: 10px;
    padding: 12px 14px;
}}
div[data-testid="stMetric"] label {{
    color: {MUTED} !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em; text-transform: uppercase;
}}
div[data-testid="stMetricValue"] {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.25rem !important; color: {TEXT} !important;
}}

/* ---------- watchlist rows ---------- */
.row-badge {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem; letter-spacing: 0.1em;
    padding: 3px 9px; border-radius: 999px;
    border: 1px solid {EDGE}; color: {MUTED};
    display: inline-block;
}}
.badge-up   {{ color: {UP};   border-color: {UP}44; }}
.badge-down {{ color: {DOWN}; border-color: {DOWN}44; }}
.badge-type {{ color: {MARIGOLD}; border-color: {MARIGOLD}33; }}

/* ---------- general chrome ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px; border-bottom: 1px solid {EDGE};
}}
.stTabs [data-baseweb="tab"] {{
    font-weight: 500; color: {MUTED};
}}
.stTabs [aria-selected="true"] {{
    color: {MARIGOLD} !important;
}}
.stButton > button {{
    border-radius: 8px; border: 1px solid {EDGE};
    font-weight: 500;
}}
.stButton > button:hover {{ border-color: {MARIGOLD}; color: {MARIGOLD}; }}
.stButton > button[kind="primary"] {{
    background: {MARIGOLD}; color: {INK}; border: none; font-weight: 600;
}}
.stButton > button[kind="primary"]:hover {{ background: #FFBE55; color: {INK}; }}
[data-testid="stDataFrame"] {{ border: 1px solid {EDGE}; border-radius: 10px; }}
h2, h3 {{ letter-spacing: -0.01em; }}
hr {{ border-color: {EDGE}; }}

/* hide Streamlit dev chrome for a product feel */
#MainMenu, footer, [data-testid="stToolbar"] {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* watchlist row data cell */
.row-data {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem; text-align: right;
    line-height: 1.5; padding-top: 4px;
}}
.row-data .price {{ color: {TEXT}; font-weight: 600; }}
.row-data .chg-up {{ color: {UP}; }}
.row-data .chg-down {{ color: {DOWN}; }}

/* sidebar */
section[data-testid="stSidebar"] {{
    background: {PANEL}; border-right: 1px solid {EDGE};
}}
.side-brand {{
    font-family: 'Space Grotesk', sans-serif; font-weight: 700;
    font-size: 1.15rem; color: {TEXT}; letter-spacing: -0.01em;
}}
.side-kicker {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem;
    letter-spacing: 0.2em; color: {MARIGOLD}; text-transform: uppercase;
}}
.side-stat {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
    color: {MUTED}; margin: 2px 0;
}}
.side-stat b {{ color: {TEXT}; font-weight: 600; }}
</style>
"""


def inject():
    st.markdown(_CSS, unsafe_allow_html=True)


def hero(moves):
    """Header + scrolling ticker tape. moves: [(symbol,label,close,pct)]."""
    st.markdown(
        """
        <div class="hero">
          <div class="kicker">Personal terminal · BSE / NSE / AMFI</div>
          <h1>Watchlist Tracker</h1>
          <div class="sub">Free data, your rules. Signals are prompts to
          investigate — never automatic buy or sell instructions.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if moves:
        cells = []
        for symbol, label, close, pct in moves:
            cls = "up" if pct >= 0 else "down"
            arrow = "▲" if pct >= 0 else "▼"
            cells.append(
                f'<span class="sym">{label}</span>'
                f'<span class="px">{close:,.2f}</span>'
                f'<span class="{cls}">{arrow} {abs(pct):.2f}%</span>'
                f'<span class="sep">·</span>'
            )
        tape = "".join(cells)
        # ~7s per item reads comfortably; floor of 90s for short lists
        duration = max(90, len(moves) * 7)
        st.markdown(
            f'<div class="tape-wrap"><div class="tape" '
            f'style="--tape-duration:{duration}s">{tape}{tape}</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="tape-wrap"><div class="tape" style="animation:none;'
            'padding-left:12px;">No price data yet — run a download in the '
            "Scan tab to light up the tape.</div></div>",
            unsafe_allow_html=True,
        )


def badge(text, kind=""):
    """kind: '' | 'up' | 'down' | 'type'"""
    cls = f"row-badge badge-{kind}" if kind else "row-badge"
    return f'<span class="{cls}">{text}</span>'


def sparkline(values, width=92, height=26):
    """Inline SVG sparkline; green/red by first-to-last direction."""
    if not values or len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    n = len(values)
    pts = " ".join(
        f"{(i / (n - 1)) * width:.1f},{height - 2 - ((v - lo) / rng) * (height - 4):.1f}"
        for i, v in enumerate(values)
    )
    color = UP if values[-1] >= values[0] else DOWN
    return (f'<svg width="{width}" height="{height}" '
            f'style="vertical-align:middle">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="1.6" stroke-linejoin="round" '
            f'stroke-linecap="round" opacity="0.9"/></svg>')


def row_data_cell(spark_values, last, pct):
    """Sparkline + price + day change as one HTML cell."""
    spark = sparkline(spark_values) if spark_values else ""
    if last is None:
        return (f'<div class="row-data">{spark} '
                f'<span style="color:{MUTED}">no data</span></div>')
    cls = "chg-up" if (pct or 0) >= 0 else "chg-down"
    arrow = "▲" if (pct or 0) >= 0 else "▼"
    pct_txt = f'{arrow} {abs(pct):.2f}%' if pct is not None else ""
    return (f'<div class="row-data">{spark} '
            f'<span class="price">{last:,.2f}</span> '
            f'<span class="{cls}">{pct_txt}</span></div>')


def sidebar(counts, last_date, signals_today):
    """Branded sidebar with data status."""
    with st.sidebar:
        st.markdown('<div class="side-kicker">Personal terminal</div>'
                    '<div class="side-brand">Watchlist Tracker</div>',
                    unsafe_allow_html=True)
        st.markdown("---")
        st.markdown(
            f'<div class="side-stat">Tracking <b>{counts.get("stock", 0)}</b> '
            f'stocks · <b>{counts.get("etf", 0)}</b> ETFs · '
            f'<b>{counts.get("mf", 0)}</b> funds</div>'
            f'<div class="side-stat">Data through <b>{last_date or "—"}</b></div>'
            f'<div class="side-stat">Signals today <b>{signals_today}</b></div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.caption("Free data: Yahoo Finance + AMFI (mfapi.in). Signals are "
                   "prompts to investigate, never instructions.")
