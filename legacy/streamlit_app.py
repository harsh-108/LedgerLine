import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
"""
Streamlit UI for the BSE watchlist tracker.

Run with:  streamlit run app.py

Tabs:
- Watchlist : add/remove items; click any item to see charts, stats,
              and fundamentals inline (no tab switching)
- Screener  : filter your watchlist stocks by fundamentals (Screener-lite)
- Scan      : refresh all data; indicator signal table
- Journal   : signals + automatic market events (big moves, circuits,
              52-week highs/lows)
"""

import pandas as pd
import streamlit as st

from app.alerts import alerts
from app.analysis import analysis
from app.analysis import backtest
from app.analysis import charts
from app.core import database as db
from app.data_sources import live
from app.analysis import nlp
from app.alerts import notify
from app.portfolio import portfolio
from app.portfolio import sip
from app.analysis import ml
from app.analysis import query_engine as qe
from app.data_sources import downloader
from app.analysis import scanner
from app.analysis import theme
import aigo_sdk.auto
st.set_page_config(page_title="BSE Watchlist Tracker", page_icon="📈", layout="wide")
db.init_db()
theme.inject()
_moves = db.latest_moves()
theme.hero(_moves)

_all_items = db.get_watchlist()
_counts = {}
for _r in _all_items:
    _counts[_r[1]] = _counts.get(_r[1], 0) + 1
theme.sidebar(_counts, db.last_price_date(), db.today_signal_count())

_move_map = {m[0]: (m[2], m[3]) for m in _moves}
if _moves:
    _ups = sum(1 for m in _moves if m[3] >= 0)
    _best = max(_moves, key=lambda m: m[3])
    _worst = min(_moves, key=lambda m: m[3])
    oc1, oc2, oc3, oc4 = st.columns(4)
    oc1.metric("Advancing / declining",
               f"{_ups} / {len(_moves) - _ups}")
    oc2.metric(f"Top gainer · {_best[1]}", f"{_best[2]:,.2f}",
               delta=f"{_best[3]:+.2f}%")
    oc3.metric(f"Top loser · {_worst[1]}", f"{_worst[2]:,.2f}",
               delta=f"{_worst[3]:+.2f}%")
    oc4.metric("Signals today", db.today_signal_count())

(tab_watch, tab_pf, tab_screen, tab_ai, tab_bt, tab_scan,
 tab_journal) = st.tabs(
    ["Watchlist", "Portfolio", "Screener", "AI Lab", "Backtest",
     "Scan & Signals", "Journal"]
)


# ----------------------------------------------------------- detail renderer
def fmt_fundamental(key, value):
    if value is None:
        return "—"
    if key == "marketCap":
        return f"₹{value / 1e7:,.0f} Cr"
    if key in ("returnOnEquity", "profitMargins"):
        return f"{value * 100:.1f}%"
    if key == "dividendYield":
        v = value * 100 if value < 1 else value  # yahoo is inconsistent here
        return f"{v:.2f}%"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


@st.dialog(" ", width="large")
def details_dialog(asset_type, symbol, scheme_code, label, item_id=None):
    hc1, hc2 = st.columns([3, 1.4])
    hc1.markdown(f"### {label}")
    if item_id is not None:
        existing = db.get_tag_map().get(item_id, "")
        new_tag = hc2.text_input("Tag", value=existing,
                                 placeholder="e.g. Core, Dividend",
                                 key=f"tag_{item_id}")
        if new_tag != existing:
            db.set_tag(item_id, new_tag.strip())
    render_details(asset_type, symbol, scheme_code, label)


def render_details(asset_type, symbol, scheme_code, label):
    period = st.radio(
        "Period", list(charts.PERIODS.keys()), index=2, horizontal=True,
        key=f"period_{symbol or scheme_code}",
    )
    period_days = charts.PERIODS[period]

    if asset_type in ("stock", "etf"):
        df = charts.load_stock_df(symbol)
        if df is None or len(df) < 30:
            st.warning(f"No stored data for {symbol} yet.")
            if st.button("Download data for this item now",
                         type="primary", key=f"dl_{symbol}"):
                log = []
                with st.spinner(f"Downloading {symbol}..."):
                    n = downloader.download_one(
                        symbol=symbol, asset_type=asset_type,
                        progress=log.append,
                    )
                if n:
                    st.success(f"Downloaded {n:,} days — reopen this item "
                               "to see its charts.")
                else:
                    st.error("Download failed again:")
                    st.code("\n".join(str(x) for x in log) or "(empty)")
            return
        stats = list(charts.stock_stats(df).items())
        for start in range(0, len(stats), 4):
            cols = st.columns(4)
            for col, (k, v) in zip(cols, stats[start:start + 4]):
                if k == "Trend":
                    col.metric(k, v, delta="bullish" if v == "UP" else "-bearish")
                elif "return" in k:
                    col.metric(k, v, delta=v)
                else:
                    col.metric(k, v)
        st.plotly_chart(
            charts.stock_figure(df, f"{label} ({symbol})", period_days),
            use_container_width=True,
        )
        BENCH = "NIFTYBEES.NS"
        if symbol != BENCH:
            bdf = charts.load_stock_df(BENCH)
            if bdf is not None and len(bdf) > 30:
                n = period_days or min(len(df), len(bdf))
                n = min(n, len(df), len(bdf))
                s_ret = (df["close"].iloc[-1] / df["close"].iloc[-n] - 1) * 100
                b_ret = (bdf["close"].iloc[-1] / bdf["close"].iloc[-n] - 1) * 100
                diff = s_ret - b_ret
                word = "ahead of" if diff >= 0 else "behind"
                st.metric(
                    f"vs NIFTY 50 (NIFTYBEES) over {period}",
                    f"{s_ret:+.1f}% vs {b_ret:+.1f}%",
                    delta=f"{diff:+.1f} pts {word} the index",
                )
                st.caption(
                    "A stock is only 'doing well' if it beats what the "
                    "index gave you for free."
                )
        if asset_type == "stock":
            ck = analysis.checklist(symbol)
            if ck:
                tier_style = {"strong": ("✓", theme.UP),
                              "mixed": ("~", theme.MARIGOLD),
                              "weak": ("✗", theme.DOWN)}[ck["tier"]]
                st.markdown(
                    f"##### Checklist verdict &nbsp; "
                    f"<span style='color:{tier_style[1]};font-family:monospace'>"
                    f"{tier_style[0]} {ck['tier'].upper()} — "
                    f"{ck['passed']}/{ck['applicable']} checks passed</span>",
                    unsafe_allow_html=True,
                )
                vc1, vc2 = st.columns(2)
                with vc1:
                    if ck["pros"]:
                        st.markdown("**What looks good**")
                        for p in ck["pros"]:
                            st.markdown(f":green[+] {p}")
                with vc2:
                    if ck["cons"]:
                        st.markdown("**What to worry about**")
                        for c in ck["cons"]:
                            st.markdown(f":red[−] {c}")
                for n in ck["notes"]:
                    st.markdown(f":orange[▸] {n}")
                st.info(ck["tier_text"])
                st.caption(
                    "This is a research checklist, not a buy/sell "
                    "instruction — it cannot know your portfolio, horizon, "
                    "or risk tolerance. Data coverage: "
                    f"{ck['data_coverage']}."
                )
                st.divider()
            fund, updated = db.get_fundamentals(symbol)
            if fund:
                st.markdown(f"##### Fundamentals "
                            f"<span style='color:{theme.MUTED};font-size:0.75rem'>"
                            f"(Yahoo snapshot · {updated})</span>",
                            unsafe_allow_html=True)
                items = [(disp, fmt_fundamental(k, fund.get(k)))
                         for k, disp in downloader.FUNDAMENTAL_KEYS.items()
                         if fund.get(k) is not None]
                for row_start in range(0, len(items), 4):
                    cols = st.columns(4)
                    for col, (k, v) in zip(cols, items[row_start:row_start + 4]):
                        col.metric(k, v)
                st.caption(
                    "Yahoo's fundamentals for Indian listings can be incomplete "
                    "or stale — cross-check on screener.in before any decision."
                )
            else:
                st.caption("No fundamentals stored yet — they're fetched "
                           "automatically on download.")
    else:
        nav = charts.load_mf_series(scheme_code)
        if nav is None or len(nav) < 30:
            st.warning("No NAV data stored yet.")
            if st.button("Download NAVs for this fund now",
                         type="primary", key=f"dlmf_{scheme_code}"):
                with st.spinner("Downloading NAV history..."):
                    n = downloader.download_one(
                        asset_type="mf", scheme_code=scheme_code,
                        label=label, progress=lambda m: None,
                    )
                if n:
                    st.success(f"Downloaded {n:,} NAVs — reopen this fund "
                               "to see its charts.")
                else:
                    st.error("Download failed — mfapi.in may be briefly "
                             "unavailable; try again in a minute.")
            return
        stats = list(charts.mf_stats(nav).items())
        for start in range(0, len(stats), 4):
            cols = st.columns(4)
            for col, (k, v) in zip(cols, stats[start:start + 4]):
                if "return" in k or "CAGR" in k:
                    col.metric(k, v, delta=v)
                else:
                    col.metric(k, v)
        st.plotly_chart(charts.mf_figure(nav, label, period_days),
                        use_container_width=True)


# ------------------------------------------------------------------ Watchlist
with tab_watch:
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("Current watchlist")
        st.caption("Click an item to open its charts and fundamentals right here.")
        items = db.get_watchlist()
        if not items:
            st.info("Watchlist is empty. Add something on the right.")
        else:
            wdf = pd.DataFrame(
                items,
                columns=["id", "type", "symbol", "scheme_code", "label", "added"],
            )
            counts = wdf["type"].value_counts().to_dict()
            st.caption(
                f"{counts.get('stock', 0)} stocks · {counts.get('etf', 0)} ETFs · "
                f"{counts.get('mf', 0)} mutual funds"
            )
            fc1, fc2, fc3 = st.columns([3, 1.6, 1.6])
            search = fc1.text_input(
                "Search", placeholder="Filter by name or symbol...",
                label_visibility="collapsed",
            )
            tag_options = ["All tags"] + db.all_tags() + ["Untagged"]
            tag_pick = fc2.selectbox("Tag", tag_options,
                                     label_visibility="collapsed")
            if fc3.button("Live quotes", use_container_width=True,
                          help="Fetch current prices (delayed via Yahoo, "
                               "real-time if SmartAPI configured)"):
                syms = [r[2] for r in db.get_watchlist()
                        if r[1] in ("stock", "etf")]
                with st.spinner("Fetching quotes..."):
                    quotes, provider = live.get_quotes(syms)
                st.session_state["live_quotes"] = quotes
                st.session_state["live_provider"] = provider
            if "live_quotes" in st.session_state:
                st.caption(f"Live prices via "
                           f"{st.session_state['live_provider']} — "
                           f"{len(st.session_state['live_quotes'])} quotes "
                           "loaded (shown in rows below)")
            tag_map = db.get_tag_map()
            if tag_pick == "Untagged":
                wdf = wdf[~wdf["id"].isin(tag_map.keys())]
            elif tag_pick != "All tags":
                ids_with = [k for k, v in tag_map.items() if v == tag_pick]
                wdf = wdf[wdf["id"].isin(ids_with)]
            if search:
                s = search.lower()
                wdf = wdf[
                    wdf["label"].str.lower().str.contains(s, na=False)
                    | wdf["symbol"].fillna("").str.lower().str.contains(s)
                ]
            for _, row in wdf.iterrows():
                rid = int(row["id"])
                c1, c2, c3, c4 = st.columns([4.2, 3.2, 1.1, 0.9])
                display = row["symbol"] or f"MF {row['scheme_code']}"
                if c1.button(
                    f"{row['label']}  ·  {display}",
                    key=f"sel{rid}", use_container_width=True,
                ):
                    details_dialog(row["type"], row["symbol"],
                                   row["scheme_code"], row["label"],
                                   item_id=rid)
                if row["type"] == "mf":
                    spark = db.recent_navs(int(row["scheme_code"]))
                    last = spark[-1] if spark else None
                    pct = ((spark[-1] / spark[-2] - 1) * 100
                           if len(spark) > 1 else None)
                else:
                    spark = db.recent_closes(row["symbol"])
                    last, pct = _move_map.get(row["symbol"], (None, None))
                    lq = st.session_state.get("live_quotes", {})
                    if row["symbol"] in lq:
                        live_last, live_prev = lq[row["symbol"]]
                        last = live_last
                        if live_prev:
                            pct = (live_last / live_prev - 1) * 100
                    elif last is None and spark:
                        last = spark[-1]
                c2.markdown(theme.row_data_cell(spark, last, pct),
                            unsafe_allow_html=True)
                c3.markdown(theme.badge(row["type"].upper(), "type"),
                            unsafe_allow_html=True)
                if c4.button("✕", key=f"rm{rid}", help="Remove from watchlist"):
                    db.remove_watchlist_item(rid)
                    st.rerun()

    with right:
        st.subheader("Add a stock or ETF")
        with st.container(border=True):
            sym = st.text_input(
                "Ticker",
                placeholder="e.g. ADANIPOWER or TATAELXSI.BO",
                help="Suffix optional — .NS and .BO are tried automatically.",
            )
            a_type = st.radio("Type", ["stock", "etf"], horizontal=True)
            if st.button("Add to watchlist", type="primary", disabled=not sym):
                with st.spinner(f"Validating {sym.upper()}..."):
                    ok, resolved, msg = downloader.resolve_and_validate(sym.upper())
                if ok:
                    db.add_ticker(resolved, a_type)
                    log = []
                    with st.spinner(f"Downloading history for {resolved}..."):
                        n = downloader.download_one(
                            symbol=resolved, asset_type=a_type,
                            progress=log.append,
                        )
                    if n:
                        st.success(f"Added {resolved} — {n:,} days of "
                                   "history downloaded. Click it in the "
                                   "watchlist to open details.")
                        st.rerun()
                    else:
                        st.error(
                            f"{resolved} was added to the watchlist, but the "
                            "history download failed (Yahoo may be "
                            "throttling). Open its details for a one-click "
                            "retry, or run a full refresh in the Scan tab."
                        )
                        with st.expander("Download log"):
                            st.code("\n".join(str(x) for x in log) or "(empty)")
                else:
                    st.error(msg)

        st.subheader("Add a mutual fund")
        with st.container(border=True):
            q = st.text_input("Search fund name", placeholder="e.g. parag parikh flexi")
            if q:
                try:
                    results = downloader.search_schemes(q)[:15]
                except Exception as e:
                    results = []
                    st.error(f"Search failed: {e}")
                if results:
                    choice = st.selectbox(
                        "Matches (official AMFI names)",
                        options=results,
                        format_func=lambda r: f"{r[1]}  [{r[0]}]",
                    )
                    if st.button("Add this fund", type="primary"):
                        db.add_mf(choice[0], choice[1][:60])
                        with st.spinner("Downloading NAV history..."):
                            n = downloader.download_one(
                                asset_type="mf", scheme_code=choice[0],
                                label=choice[1][:60], progress=lambda m: None,
                            )
                        if n:
                            st.success(f"Added with {n:,} NAVs: {choice[1]}")
                            st.rerun()
                        else:
                            st.error("Fund added but the NAV download "
                                     "failed — open its details for a "
                                     "one-click retry.")
                elif q:
                    st.caption("No matches — try fewer words.")

    st.divider()
    st.subheader("SIP tracker (mutual funds)")
    st.caption("Simulates your SIP against actual NAV history and computes "
               "XIRR — the true annualized return accounting for the timing "
               "of every installment.")
    scol1, scol2 = st.columns([3, 2], gap="large")
    with scol2:
        with st.container(border=True):
            mf_items = db.get_watchlist("mf")
            if not mf_items:
                st.caption("Add a mutual fund to the watchlist first.")
            else:
                s_fund = st.selectbox(
                    "Fund", mf_items, format_func=lambda r: r[4],
                    key="sip_fund")
                sc_a, sc_b = st.columns(2)
                s_amt = sc_a.number_input("Monthly amount (₹)",
                                          min_value=0.0, value=5000.0,
                                          step=500.0)
                s_day = sc_b.number_input("Day of month", 1, 28, 5)
                s_start = st.date_input("Started on", key="sip_start")
                if st.button("Add SIP", type="primary",
                             disabled=not (s_fund and s_amt)):
                    db.add_sip(s_fund[3], s_amt, int(s_day), str(s_start))
                    st.rerun()
    with scol1:
        sips = db.get_sips()
        if not sips:
            st.info("No SIPs tracked yet.")
        else:
            for sid, scheme, amt, dom, start, slabel in sips:
                res = sip.evaluate(scheme, amt, dom, start)
                rc1, rc2 = st.columns([6, 1])
                if res:
                    xirr_txt = (f"{res['xirr_pct']:+.1f}%"
                                if res["xirr_pct"] is not None else "n/a")
                    rc1.markdown(
                        f"**{slabel or scheme}** · ₹{amt:,.0f}/mo since "
                        f"{start} — {res['installments']} installments · "
                        f"invested ₹{res['invested']:,.0f} → "
                        f"**₹{res['current_value']:,.0f}** "
                        f"({res['abs_return_pct']:+.1f}% abs, "
                        f"**XIRR {xirr_txt}**)"
                    )
                else:
                    rc1.markdown(f"**{slabel or scheme}** — NAV history "
                                 "missing; download this fund first.")
                if rc2.button("✕", key=f"sip_rm{sid}"):
                    db.remove_sip(sid)
                    st.rerun()

# ------------------------------------------------------------------- Screener

# ------------------------------------------------------------------ Portfolio
with tab_pf:
    st.subheader("Holdings")
    pcol1, pcol2 = st.columns([3, 2], gap="large")

    with pcol2:
        with st.container(border=True):
            st.markdown("**Add a holding**")
            wl_syms = [r[2] for r in db.get_watchlist()
                       if r[1] in ("stock", "etf")]
            h_sym = st.selectbox("Symbol", wl_syms) if wl_syms else None
            hc1, hc2 = st.columns(2)
            h_qty = hc1.number_input("Quantity", min_value=0.0, step=1.0)
            h_px = hc2.number_input("Buy price", min_value=0.0, step=1.0)
            h_date = st.date_input("Buy date", value=None)
            if st.button("Add holding", type="primary",
                         disabled=not (h_sym and h_qty and h_px)):
                db.add_holding(h_sym, h_qty, h_px,
                               str(h_date) if h_date else None)
                st.rerun()

        with st.container(border=True):
            st.markdown("**Position size calculator**")
            st.caption("How many shares can you buy so a stop-loss hit "
                       "costs only X% of your capital?")
            sc1, sc2 = st.columns(2)
            cap = sc1.number_input("Capital (₹)", min_value=0.0,
                                   value=100000.0, step=10000.0)
            riskp = sc2.number_input("Risk per trade (%)", min_value=0.1,
                                     value=1.0, step=0.25)
            sc3, sc4 = st.columns(2)
            entry = sc3.number_input("Entry price", min_value=0.0, step=1.0)
            stop = sc4.number_input("Stop-loss price", min_value=0.0, step=1.0)
            if entry and stop:
                ps = portfolio.position_size(cap, riskp, entry, stop)
                if ps is None:
                    st.error("Stop must be below entry, and inputs positive.")
                elif ps["shares"] == 0:
                    st.warning(ps["note"])
                else:
                    st.success(
                        f"Buy up to **{ps['shares']} shares** "
                        f"(₹{ps['outlay']:,.0f}, {ps['outlay_pct']}% of "
                        f"capital). If the stop at {ps['stop_pct']}% hits, "
                        f"you lose ₹{ps['risk_amount']:,.0f} — your chosen "
                        f"{riskp}%."
                    )

    with pcol1:
        val, totals = portfolio.valuation()
        if val.empty:
            st.info("No holdings yet — add your first on the right. "
                    "Holdings must be in the watchlist (for price data).")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Invested", f"₹{totals['invested']:,.0f}")
            m2.metric("Current value", f"₹{totals['current']:,.0f}")
            m3.metric("Total P&L", f"₹{totals['pnl']:+,.0f}",
                      delta=f"{totals['pnl_pct']:+.2f}%")
            if totals["unpriced"]:
                st.caption(f"{totals['unpriced']} holding(s) have no price "
                           "data yet — add them to the watchlist and "
                           "download.")
            show = val.drop(columns=["id"])
            st.dataframe(show, use_container_width=True, hide_index=True)
            rm = st.selectbox(
                "Remove a holding", ["—"] + [
                    f"{r['Symbol']} · {r['Qty']} @ {r['Buy price']} (id {r['id']})"
                    for _, r in val.iterrows()],
            )
            if rm != "—" and st.button("Remove selected"):
                db.remove_holding(int(rm.split("id ")[1].rstrip(")")))
                st.rerun()

            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("**Allocation**")
                st.plotly_chart(charts.allocation_pie(val),
                                use_container_width=True)
            with cc2:
                st.markdown("**Correlation (1y daily returns)**")
                syms = val["Symbol"].unique().tolist()
                corr = portfolio.correlation_matrix(syms)
                if corr is None:
                    st.caption("Need 2+ holdings with price history.")
                else:
                    st.plotly_chart(charts.corr_heatmap(corr),
                                    use_container_width=True)
                    high = [(a, b, corr.loc[a, b])
                            for a in corr.index for b in corr.columns
                            if a < b and corr.loc[a, b] >= 0.7]
                    if high:
                        st.warning(
                            "Highly correlated pairs (move together — "
                            "closer to one bet than two): " + ", ".join(
                                f"{a.split('.')[0]}–{b.split('.')[0]} "
                                f"({v:.2f})" for a, b, v in high)
                        )


with tab_screen:
    st.subheader("Query")
    st.caption(
        "Screener-style queries over your watchlist — fundamentals AND "
        "technicals. Fields accept plain-English names ('market cap', "
        "'price to earnings', 'dividend yield'...). Combine with and/or, "
        "add 'sort by <field> desc' and 'top N'."
    )
    if nlp.available():
        nl_text = st.text_input(
            "Ask in plain English",
            placeholder="e.g. cheap IT stocks that fell this month but are "
                        "still in an uptrend",
        )
        if nl_text:
            with st.spinner("Translating via Groq..."):
                nl_result, gen_query, nl_err = nlp.ask(nl_text)
            if nl_err:
                st.error(nl_err)
            else:
                st.caption(f"Generated query: `{gen_query}`")
                if nl_result.empty:
                    st.warning("No stocks match.")
                else:
                    st.dataframe(nl_result, use_container_width=True,
                                 hide_index=True)
        st.divider()
    else:
        st.caption("Tip: add GROQ_API_KEY to a .env file to unlock "
                   "plain-English queries (free at console.groq.com).")

    qcol1, qcol2 = st.columns([3, 1])
    query_text = qcol1.text_input(
        "Query", placeholder="pe < 25 and roe > 15 sort by market cap desc",
        label_visibility="collapsed",
    )
    example = qcol2.selectbox(
        "Examples", ["— examples —"] + qe.EXAMPLES,
        label_visibility="collapsed",
    )
    if example != "— examples —" and not query_text:
        query_text = example
    if query_text:
        try:
            with st.spinner("Running query..."):
                qresult, expl, _diag = qe.run_query(query_text)
            if qresult.empty:
                st.warning(f"No stocks match: {expl}")
            else:
                st.caption(f"Matched {len(qresult)} stock(s) · filter: {expl}")
                st.dataframe(qresult, use_container_width=True,
                             hide_index=True)
        except qe.QueryError as e:
            st.error(str(e))
    st.divider()

    st.subheader("Quick filters")
    st.caption(
        "Filter your watchlist stocks by fundamentals (Yahoo snapshot data). "
        "For full statements, shareholding, and peer comparison, screener.in "
        "remains the reference — this is the quick first pass."
    )
    fund_map = db.all_fundamentals()
    if not fund_map:
        st.info("No fundamentals stored yet. Run 'Download / refresh data' in "
                "the Scan tab, or refresh below.")
    c1, c2, c3, c4 = st.columns(4)
    max_pe = c1.number_input("Max P/E (0 = ignore)", 0.0, 500.0, 0.0, 5.0)
    min_roe = c2.number_input("Min ROE %", 0.0, 100.0, 0.0, 1.0)
    min_mcap = c3.number_input("Min market cap (₹ Cr)", 0.0, 3e7, 0.0, 1000.0)
    min_dy = c4.number_input("Min dividend yield %", 0.0, 20.0, 0.0, 0.25)

    if st.button("Refresh fundamentals for all stocks"):
        log_area = st.empty()
        lines = []

        def progress(m):
            lines.append(str(m))
            log_area.code("\n".join(lines[-10:]))

        with st.spinner("Fetching fundamentals..."):
            downloader.refresh_all_fundamentals(progress=progress)
        st.rerun()

    if fund_map:
        rows = []
        for symbol, f in fund_map.items():
            pe = f.get("trailingPE")
            roe = (f.get("returnOnEquity") or 0) * 100
            mcap_cr = (f.get("marketCap") or 0) / 1e7
            dy = f.get("dividendYield") or 0
            dy = dy * 100 if dy < 1 else dy
            if max_pe and (pe is None or pe > max_pe):
                continue
            if min_roe and roe < min_roe:
                continue
            if min_mcap and mcap_cr < min_mcap:
                continue
            if min_dy and dy < min_dy:
                continue
            rows.append({
                "Symbol": symbol,
                "Sector": f.get("sector", "—"),
                "Mkt cap (₹Cr)": round(mcap_cr) if mcap_cr else None,
                "P/E": round(pe, 1) if pe else None,
                "P/B": round(f["priceToBook"], 2) if f.get("priceToBook") else None,
                "ROE %": round(roe, 1) if roe else None,
                "Net margin %": round((f.get("profitMargins") or 0) * 100, 1) or None,
                "Div yield %": round(dy, 2) if dy else None,
                "D/E": round(f["debtToEquity"], 1) if f.get("debtToEquity") else None,
            })
        if rows:
            sdf = pd.DataFrame(rows).sort_values("Mkt cap (₹Cr)", ascending=False)
            st.dataframe(sdf, use_container_width=True, hide_index=True, height=520)
            st.caption(f"{len(rows)} of {len(fund_map)} stocks pass the filters. "
                       "A screen narrows the list; it never replaces reading "
                       "the business.")
        else:
            st.warning("No stocks pass these filters — loosen them a bit.")


# -------------------------------------------------------------------- AI Lab
with tab_ai:
    st.subheader("Factor rankings")
    st.caption(
        "A transparent composite score across your watchlist: momentum (30%, "
        "6-month return), value (25%, earnings yield), quality (25%, ROE), "
        "trend (20%, above/below the 200-day SMA) — each z-scored across the "
        "list. No black box; this is how real quant funds rank, and it is far "
        "more defensible than any next-day predictor."
    )
    if st.button("Compute rankings"):
        with st.spinner("Ranking watchlist..."):
            ranks, _weights = ml.rank_watchlist()
        if ranks.empty:
            st.warning("No data yet — run a download first.")
        else:
            st.session_state["ai_ranks"] = ranks
    if "ai_ranks" in st.session_state:
        st.dataframe(st.session_state["ai_ranks"], use_container_width=True,
                     hide_index=True, height=480)
        st.caption(
            "A high score means the stock currently looks good on these "
            "four factors relative to the rest of YOUR watchlist — it is "
            "a ranking, not a prediction, and says nothing about stocks "
            "outside the list."
        )

    st.divider()
    st.subheader("Next-day direction model (educational)")
    st.caption(
        "A gradient-boosted classifier on technical features, trained on the "
        "past and tested on the most recent 30% it never saw. Honest "
        "expectation: 50-55% accuracy. The point of this section is to SHOW "
        "you how weak next-day prediction is, with real numbers — not to "
        "give trading advice."
    )
    eligible, excluded = ml.eligible_stocks()
    if excluded:
        st.caption(
            f"{len(eligible)} of {len(eligible) + len(excluded)} stocks have "
            f"enough stored history (~2 years / {ml.MIN_ROWS}+ trading days) "
            "to train on. The rest are hidden — Yahoo's .BO history is often "
            "shallow; switching those tickers to .NS and re-downloading "
            "usually unlocks a full decade."
        )
    if not eligible:
        st.info("No stock has enough stored history yet. Run a full download "
                "in the Scan tab, and consider .NS tickers for deeper "
                "history.")
    else:
        pick = st.selectbox(
            "Stock", eligible,
            format_func=lambda r: f"{r[4]} ({r[2]})",
        )
        if st.button("Train & evaluate", type="primary"):
            with st.spinner("Training on history, testing on unseen data..."):
                res = ml.predict(pick[2])
            if res is None:
                st.warning("Training failed unexpectedly for this stock — "
                           "its data may have gaps. Try re-downloading.")
            else:
                st.session_state["ai_pred"] = res
        if "ai_pred" in st.session_state:
            res = st.session_state["ai_pred"]
            st.markdown(f"**Results for {res['symbol']}**")
            with st.container(border=True):
                kind, msg = ml.verdict(res)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("P(up tomorrow)", f"{res['prob_up'] * 100:.0f}%")
                c2.metric("Test accuracy", f"{res['test_accuracy'] * 100:.1f}%")
                c3.metric("Naive baseline", f"{res['baseline_accuracy'] * 100:.1f}%")
                c4.metric("Edge", f"{res['edge'] * 100:+.1f} pts",
                          delta=f"{res['edge'] * 100:+.1f}")
                if kind == "no_edge":
                    st.error(msg)
                elif kind == "weak":
                    st.warning(msg)
                else:
                    st.warning(msg)
                st.caption(
                    f"Trained on {res['n_train']} days, tested on "
                    f"{res['n_test']} unseen days ({res['test_period']})."
                )
                st.markdown("**What the model paid attention to** "
                            "(permutation importance on test data):")
                imp_df = pd.DataFrame(res["importances"],
                                      columns=["Feature", "Importance"])
                st.dataframe(imp_df, use_container_width=True,
                             hide_index=True)
                st.caption(
                    "Importance near zero (or negative) means the feature "
                    "carried no real signal on unseen data — which, for "
                    "daily prices, is the usual truth."
                )


# ------------------------------------------------------------------- Backtest
with tab_bt:
    st.subheader("Backtest: golden-cross vs buy-and-hold")
    st.caption(
        "Simulates the app's own trend signal — long when SMA-50 is above "
        "SMA-200, in cash otherwise — with real per-side costs, against "
        "simply holding. Next-day execution, no lookahead. Past results "
        "guarantee nothing; the lesson is usually what costs and missed "
        "rebounds do to a plausible-looking strategy."
    )
    bt_eligible, _bt_excl = ml.eligible_stocks()
    if not bt_eligible:
        st.info("No stock has enough history yet (~2 years needed).")
    else:
        bc1, bc2 = st.columns([3, 1])
        bt_pick = bc1.selectbox(
            "Stock", bt_eligible, format_func=lambda r: f"{r[4]} ({r[2]})",
            key="bt_pick",
        )
        bt_cost = bc2.number_input("Cost per side (%)", 0.0, 2.0, 0.20, 0.05)
        if st.button("Run backtest", type="primary"):
            with st.spinner("Simulating..."):
                res = backtest.run(bt_pick[2], cost_per_side_pct=bt_cost)
            if res is None:
                st.warning("Not enough usable history for this stock.")
            else:
                st.session_state["bt_res"] = res
        if "bt_res" in st.session_state:
            res = st.session_state["bt_res"]
            st.markdown(f"**Results for {res['symbol']}** "
                        f"({res['years']} years)")
            s, h = res["strategy"], res["buy_hold"]
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Strategy CAGR", f"{s['cagr']}%",
                      delta=f"{s['cagr'] - h['cagr']:+.2f} vs hold")
            r2.metric("Buy & hold CAGR", f"{h['cagr']}%")
            r3.metric("Strategy max drawdown", f"{s['max_dd']}%")
            r4.metric("Hold max drawdown", f"{h['max_dd']}%")
            st.plotly_chart(
                charts.equity_curves(res["curves"],
                                     f"Growth of ₹1 — {res['symbol']}"),
                use_container_width=True,
            )
            st.info(backtest.summary_text(res))
            if res["n_trades"]:
                with st.expander(
                        f"Trade log — {res['n_trades']} round trips, "
                        f"{res['win_rate']:.0f}% winners"):
                    st.dataframe(res["trades"], use_container_width=True,
                                 hide_index=True)

# ---------------------------------------------------------------------- Scan
with tab_scan:
    c1, c2 = st.columns([1, 3])
    with c1:
        st.subheader("Data refresh")
        st.caption("Pulls latest prices, NAVs, and fundamentals for the whole "
                   "watchlist, then auto-logs signals and market events.")
        if st.button("Download / refresh data", type="primary"):
            log_area = st.empty()
            lines = []

            def progress(msg):
                lines.append(str(msg))
                log_area.code("\n".join(lines[-15:]))

            with st.spinner("Downloading..."):
                downloader.run_all(progress=progress, sleep=0.4)
            with st.spinner("Scanning for signals and events..."):
                scanner.scan_all(log_to_journal=True)
                fired_alerts = alerts.check_all()
            if fired_alerts:
                for msg in fired_alerts:
                    st.warning(msg)
            st.success("Refresh complete — new events are in the Journal.")

    with c2:
        st.subheader("Indicators & signals")
        if st.button("Run scan"):
            with st.spinner("Scanning..."):
                result = scanner.scan_all(log_to_journal=True)
            if result.empty:
                st.warning("No data yet — run a download first.")
            else:
                fired = result[result["signals"] != ""]
                if not fired.empty:
                    st.warning(f"{len(fired)} item(s) with signals or events "
                               "(logged to journal):")
                    st.dataframe(fired, use_container_width=True, hide_index=True)
                else:
                    st.info("No new signals or events today.")
                st.dataframe(
                    result.sort_values(["type", "name"]),
                    use_container_width=True, hide_index=True,
                )
                st.caption(
                    "Indicator signals: GOLDEN/DEATH_CROSS (SMA 50/200), "
                    "RSI_OVERSOLD/OVERBOUGHT (30/70). Auto events: BIG_GAIN/"
                    "BIG_DROP (±5%), POSSIBLE_UPPER/LOWER_CIRCUIT (±9.5%, "
                    "heuristic — exact bands vary by stock), NEW_52W_HIGH/LOW."
                )


    st.divider()
    st.subheader("Price alerts")
    tg = "connected" if notify.configured() else (
        "not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to "
        ".env for phone notifications (see notify.py header)")
    st.caption(f"Alerts fire once after a data refresh, log to the Journal, "
               f"then disarm (re-add to re-arm). Telegram: {tg}.")
    ac1, ac2, ac3, ac4 = st.columns([2.4, 1.8, 1.4, 1])
    a_syms = [r[2] for r in db.get_watchlist() if r[1] in ("stock", "etf")]
    a_sym = ac1.selectbox("Symbol", a_syms, key="al_sym") if a_syms else None
    a_kind = ac2.selectbox("Condition", ["price_above", "price_below",
                                         "day_move"], key="al_kind",
                           help="day_move fires when the daily change "
                                "exceeds ±X%")
    a_val = ac3.number_input("Value", min_value=0.0, step=1.0, key="al_val")
    if ac4.button("Add", disabled=not (a_sym and a_val), key="al_add"):
        db.add_alert(a_sym, a_kind, a_val)
        st.rerun()
    existing_alerts = db.get_alerts(active_only=False)
    if existing_alerts:
        for aid, asym, akind, aval, aactive in existing_alerts:
            lc1, lc2, lc3 = st.columns([5, 1.4, 1])
            status = "armed" if aactive else "fired"
            lc1.markdown(f"`{asym}` · {akind.replace('_', ' ')} "
                         f"{aval:,.2f}")
            lc2.markdown(theme.badge(status.upper(),
                                     "type" if aactive else ""),
                         unsafe_allow_html=True)
            if lc3.button("✕", key=f"al_rm{aid}"):
                db.remove_alert(aid)
                st.rerun()
    if notify.configured() and st.button("Send Telegram test message"):
        ok, err = notify.send("✅ Watchlist Tracker: Telegram is working.")
        st.success("Sent — check your phone.") if ok else st.error(err)

# ------------------------------------------------------------------- Journal
with tab_journal:
    st.subheader("Journal")
    st.caption(
        "Everything notable, logged automatically on each scan: indicator "
        "signals plus market events — big single-day moves, possible circuits, "
        "and fresh 52-week highs/lows. Review monthly."
    )
    rows = db.get_journal()
    if not rows:
        st.info("Nothing logged yet — run a download + scan first.")
    else:
        jdf = pd.DataFrame(
            rows, columns=["when", "symbol", "event", "price", "your action",
                           "detail"]
        )
        event_filter = st.multiselect(
            "Filter events", sorted(jdf["event"].unique()), default=[]
        )
        if event_filter:
            jdf = jdf[jdf["event"].isin(event_filter)]
        st.dataframe(jdf, use_container_width=True, hide_index=True, height=520)
