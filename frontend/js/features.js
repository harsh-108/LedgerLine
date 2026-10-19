/* Funds page + Scorecard page. Loaded after app.js and reuses its helpers
   ($, api, fmt, pctCls, toast, sparkSVG, openDrawer, WL, loadSips).
   Nothing here is required by the rest of the app — if this file fails
   to load, the two pages are simply empty. */

/* ====================================================================
   FUNDS
   ==================================================================== */
const _pct = (v, d = 1) => v == null ? `<span class="muted">—</span>`
  : `<span class="${pctCls(v)}">${v >= 0 ? "+" : ""}${Number(v).toFixed(d)}%</span>`;

let FUNDS = null;

async function loadFunds() {
  let d;
  try {
    d = await api("/api/funds");
  } catch (e) {
    $("#mfTable").innerHTML = `<div class="inline-msg err">Could not load funds: ${e.message}</div>`;
    return;
  }
  FUNDS = d;
  const t = d.totals, bm = d.benchmark.returns || {};
  const best = d.funds.filter(f => f.stats && f.stats.returns["1y"] != null)
    .sort((a, b) => b.stats.returns["1y"] - a.stats.returns["1y"])[0];
  $("#mfTotals").innerHTML = `
    <div class="metric"><div class="k">Funds tracked</div><div class="v">${t.funds}</div></div>
    <div class="metric"><div class="k">Invested (SIP + lump sum)</div><div class="v">₹${fmt(t.invested, 0)}</div>
      <div class="d">SIP ₹${fmt(t.sip_invested, 0)} · lump ₹${fmt(t.lumpsum_invested, 0)}</div></div>
    <div class="metric"><div class="k">Value today</div><div class="v">₹${fmt(t.value, 0)}</div>
      <div class="d ${pctCls(t.pnl)}">${t.pnl >= 0 ? "+" : ""}₹${fmt(t.pnl, 0)}</div></div>
    <div class="metric"><div class="k">NIFTYBEES 1Y</div><div class="v">${bm["1y"] != null ? _pct(bm["1y"]) : "—"}</div>
      <div class="d">the fee-free bar</div></div>
    ${best ? `<div class="metric"><div class="k">Best 1Y</div><div class="v">${_pct(best.stats.returns["1y"])}</div>
      <div class="d">${best.label}</div></div>` : ""}`;

  if (!d.funds.length) {
    $("#mfTable").innerHTML = `<div class="empty">No funds yet — search above by
      name (e.g. "parag parikh flexi") and pick the direct-growth plan.</div>`;
  } else {
    const row = (f) => {
      const s = f.stats, r = s ? s.returns : {}, roll = s && s.rolling["1y"];
      if (f.error) return `<tr class="mf-row" data-id="${f.id}"><td><div class="wl-name">${f.label}</div>
        <div class="wl-sub">${f.scheme_code}</div></td>
        <td colspan="11" class="muted">stats unavailable: ${f.error}</td>
        <td><button class="rm-btn" data-mfrm="${f.id}" title="Remove from watchlist">✕</button></td></tr>`;
      return `<tr class="mf-row" data-id="${f.id}">
        <td><div class="wl-name">${f.label}</div>
          <div class="wl-sub">${f.scheme_code}${s ? " · since " + s.since : ""}</div></td>
        <td>${s ? sparkSVG(s.spark, 80, 24) : ""}</td>
        <td class="num">${s ? fmt(s.latest_nav, 2) : "—"}<br>
          <span class="muted" style="font-size:.7em">${s ? s.nav_date : "no NAVs"}</span></td>
        <td class="num">${_pct(s && s.day_pct, 2)}</td>
        <td class="num">${_pct(r["1m"])}</td>
        <td class="num">${_pct(r["6m"])}</td>
        <td class="num">${_pct(r["1y"])}</td>
        <td class="num">${_pct(r["3y"] != null ? (Math.pow(1 + r["3y"] / 100, 1 / 3) - 1) * 100 : null)}</td>
        <td class="num">${roll ? `${_pct(roll.median)}<br><span class="muted" style="font-size:.7em">worst ${roll.worst.toFixed(1)}%</span>` : `<span class="muted">—</span>`}</td>
        <td class="num">${_pct(f.vs_index_1y)}</td>
        <td class="num">${s ? `<span class="neg">${s.max_drawdown.toFixed(1)}%</span>` : "—"}</td>
        <td class="num">${f.position ? `₹${fmt(f.position.value, 0)}<br><span class="${pctCls(f.position.pnl_pct)}" style="font-size:.7em">${f.position.pnl_pct >= 0 ? "+" : ""}${f.position.pnl_pct}%</span>` : `<span class="muted">—</span>`}</td>
        <td><button class="rm-btn" data-mfrm="${f.id}" title="Remove from watchlist">✕</button></td>
      </tr>`;
    };
    $("#mfTable").innerHTML = `<table><thead><tr>
      <th>Fund</th><th>90d</th><th class="num">NAV</th><th class="num">Day</th>
      <th class="num">1M</th><th class="num">6M</th><th class="num">1Y</th>
      <th class="num" title="3-year return, annualised">3Y CAGR</th>
      <th class="num" title="Median of every 1-year holding period in the history">Rolling 1Y</th>
      <th class="num" title="1Y return minus NIFTYBEES 1Y return">vs NIFTYBEES</th>
      <th class="num">Max DD</th><th class="num">Held</th><th></th></tr></thead>
      <tbody>${d.funds.map(row).join("")}</tbody></table>`;
    $("#mfTable").querySelectorAll(".mf-row").forEach(tr =>
      tr.addEventListener("click", (e) => {
        if (e.target.dataset.mfrm) return;
        const item = (window.WL || []).find(i => i.id == tr.dataset.id)
          || { id: +tr.dataset.id, type: "mf",
               scheme_code: d.funds.find(f => f.id == tr.dataset.id).scheme_code,
               label: d.funds.find(f => f.id == tr.dataset.id).label };
        openDrawer(item);
      }));
    $("#mfTable").querySelectorAll("[data-mfrm]").forEach(b =>
      b.addEventListener("click", async () => {
        if (!confirm("Remove this fund from the watchlist? NAV history stays in the DB.")) return;
        await api(`/api/watchlist/${b.dataset.mfrm}`, { method: "DELETE" });
        if (window.loadWatchlist) await loadWatchlist();
        loadFunds();
      }));
  }
  // schemes selects for SIP + holdings (WL may be stale right after an add)
  const opts = d.funds.map(f => `<option value="${f.scheme_code}">${f.label}</option>`).join("")
    || `<option value="">No funds yet</option>`;
  $("#mhScheme").innerHTML = opts;
  if (window.loadSips) { loadSips(); $("#spScheme").innerHTML = opts; }
  renderMfHoldings(d);
}
window.loadFunds = loadFunds;

function renderMfHoldings(d) {
  const rows = [];
  d.funds.forEach(f => (f.holdings || []).forEach(h => {
    const nav = f.stats ? f.stats.latest_nav : null;
    const value = nav ? h.units * nav : null, cost = h.units * h.buy_nav;
    rows.push(`<div class="div-row">
      <span>${f.label}<br><span class="muted">${fmt(h.units, 3)} u @ ${fmt(h.buy_nav, 2)}${h.buy_date ? " · " + h.buy_date : ""}</span></span>
      <span class="num">${value != null ? "₹" + fmt(value, 0) : "—"}</span>
      <span class="num ${value != null ? pctCls(value - cost) : ""}">${value != null ? (value >= cost ? "+" : "") + ((value / cost - 1) * 100).toFixed(1) + "%" : "no NAV"}</span>
      <button class="rm-btn" style="opacity:1" data-mhrm="${h.id}">✕</button>
    </div>`);
  }));
  $("#mhList").innerHTML = rows.join("");
  $("#mhList").querySelectorAll("[data-mhrm]").forEach(b =>
    b.addEventListener("click", async () => {
      await api(`/api/mf/holdings/${b.dataset.mhrm}`, { method: "DELETE" });
      loadFunds();
    }));
}

on("#mhAdd", "click", async () => {
  const msg = $("#mhMsg");
  try {
    await api("/api/mf/holdings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheme_code: +$("#mhScheme").value,
        units: +$("#mhUnits").value, buy_nav: +$("#mhNav").value,
        buy_date: $("#mhDate").value || null }),
    });
    toast("Holding added.", "success");
    $("#mhUnits").value = ""; $("#mhNav").value = "";
    loadFunds();
  } catch (e) { msg.textContent = e.message; msg.className = "inline-msg err"; }
});

/* ---- fund search / add ---- */
let mfTimer = null, mfHits = [];
const mfBox = () => $("#mfSuggest");
function mfHide() { mfBox().classList.add("hidden"); }
on("#mfSearch", "input", () => {
  clearTimeout(mfTimer);
  const q = $("#mfSearch").value.trim();
  if (q.length < 3) { mfHide(); return; }
  mfTimer = setTimeout(async () => {
    try {
      const r = await api(`/api/mf/search?q=${encodeURIComponent(q)}`);
      mfHits = r.results;
      if (!mfHits.length) { mfBox().innerHTML = `<div class="suggest-item"><span class="s-name">No match on mfapi.in</span></div>`; }
      else mfBox().innerHTML = mfHits.map((h, i) => `
        <div class="suggest-item" data-i="${i}">
          <span class="s-sym">${h.scheme_code}</span>
          <span class="s-name" title="${h.name}">${h.name}</span>
        </div>`).join("");
      mfBox().classList.remove("hidden");
      mfBox().querySelectorAll(".suggest-item[data-i]").forEach(el =>
        el.addEventListener("mousedown", e => { e.preventDefault(); mfAdd(mfHits[+el.dataset.i]); }));
    } catch (e) {
      mfBox().innerHTML = `<div class="suggest-item"><span class="s-name">${e.message}</span></div>`;
      mfBox().classList.remove("hidden");
    }
  }, 350);
});
on("#mfSearch", "blur", () => setTimeout(mfHide, 150));
on("#mfSearch", "keydown", (e) => { if (e.key === "Escape") mfHide(); });

async function mfAdd(hit) {
  mfHide();
  const msg = $("#mfMsg");
  msg.className = "inline-msg"; msg.textContent = `Adding ${hit.name} and downloading its NAV history…`;
  msg.classList.remove("hidden");
  try {
    const r = await api("/api/mf/add", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheme_code: hit.scheme_code, label: hit.name.slice(0, 60) }),
    });
    msg.textContent = r.note || `${r.name}: ${r.rows} NAVs stored.`;
    msg.className = "inline-msg " + (r.note ? "warn" : "ok");
    $("#mfSearch").value = "";
    if (window.loadWatchlist) await loadWatchlist();
    loadFunds();
  } catch (e) { msg.textContent = e.message; msg.className = "inline-msg err"; }
}

/* ---- extra blocks in the MF drawer ---- */
function mfDrawerExtras(d) {
  let html = "";
  const st = d.detail || {};
  if (st.rolling && (st.rolling["1y"] || st.rolling["3y"])) {
    const r = (label, x) => !x ? "" : `<tr><td>${label}</td>
      <td class="num">${_pct(x.median)}</td><td class="num neg">${x.worst.toFixed(1)}%</td>
      <td class="num pos">+${x.best.toFixed(1)}%</td><td class="num">${x.positive_pct}%</td>
      <td class="num muted">${x.windows}</td></tr>`;
    html += `<div class="section-label">Rolling returns (annualised)</div>
      <table class="br-table"><thead><tr><th>Hold for</th><th class="num">Median</th>
      <th class="num">Worst entry</th><th class="num">Best entry</th><th class="num">Positive</th>
      <th class="num">windows</th></tr></thead><tbody>
      ${r("1 year", st.rolling["1y"])}${r("3 years", st.rolling["3y"])}</tbody></table>
      <div class="hint">Every possible entry date in the history, held for that
        long. The worst row is the realistic downside of bad timing.</div>`;
  }
  if (d.vs_index_1y != null) {
    html += `<div class="inline-msg ${d.vs_index_1y >= 0 ? "ok" : "warn"}">
      1Y vs NIFTYBEES: ${_pct(d.vs_index_1y)} — ${d.vs_index_1y >= 0
        ? "ahead of the index ETF over the last year."
        : "behind the index ETF; the fee needs to be earning something."}</div>`;
  }
  if (d.position) {
    const p = d.position;
    html += `<div class="section-label">Your holding</div><div class="summary-row">
      <div class="metric"><div class="k">Units</div><div class="v">${fmt(p.units, 3)}</div><div class="d">avg NAV ${fmt(p.avg_nav, 2)}</div></div>
      <div class="metric"><div class="k">Invested</div><div class="v">₹${fmt(p.invested, 0)}</div></div>
      <div class="metric"><div class="k">Value</div><div class="v">₹${fmt(p.value, 0)}</div>
        <div class="d ${pctCls(p.pnl)}">${p.pnl >= 0 ? "+" : ""}₹${fmt(p.pnl, 0)} (${p.pnl_pct}%)</div></div></div>`;
  }
  if (d.sips && d.sips.length) {
    html += `<div class="section-label">SIPs in this fund</div>` + d.sips.map(s => {
      const e = s.eval;
      return `<div class="div-row"><span>₹${fmt(s.amount, 0)}/mo since ${s.start}</span>
        <span class="num">${e ? "₹" + fmt(e.current_value, 0) : "—"}</span>
        <span class="num ${e && e.xirr_pct >= 0 ? "pos" : "neg"}">${e && e.xirr_pct != null ? (e.xirr_pct >= 0 ? "+" : "") + e.xirr_pct.toFixed(1) + "% XIRR" : "—"}</span></div>`;
    }).join("");
  }
  return html;
}
window.mfDrawerExtras = mfDrawerExtras;

/* ====================================================================
   SCORECARD
   ==================================================================== */
const KIND_LABEL = { verdict: "Verdict card", checklist: "Checklist tier",
                     ml_nextday: "Next-day model" };
const CALL_LABEL = { strong: "STRONG CASE", mixed: "MIXED", weak: "WEAK CASE",
                     up: "UP", down: "DOWN" };
const callChip = (c) => `<span class="sc-call sc-${c}">${CALL_LABEL[c] || c}</span>`;
const outcomeChip = (o) => o == null ? `<span class="sc-out sc-pending">waiting</span>`
  : `<span class="sc-out sc-${o}">${{ right: "✓ right", wrong: "✗ wrong", no_call: "no call" }[o]}</span>`;

async function loadScorecard() {
  const kind = $("#scKind").value, status = $("#scStatus").value,
        sym = $("#scSymbol").value.trim().toUpperCase();
  const tOnly = $("#scTrackedOnly") ? $("#scTrackedOnly").checked : true;
  let d;
  try {
    d = await api(`/api/scorecard?limit=400&tracked_only=${tOnly}${kind ? "&kind=" + kind : ""}${
      status ? "&status=" + status : ""}${sym ? "&symbol=" + encodeURIComponent(sym) : ""}`);
  } catch (e) {
    $("#scTable").innerHTML = `<div class="inline-msg err">${e.message}</div>`; return;
  }
  renderTracked(d.tracked || []);
  const all = d.summary;
  const total = all.reduce((a, g) => a + g.total, 0);
  const scored = all.reduce((a, g) => a + g.scored, 0);
  const right = all.reduce((a, g) => a + g.right, 0);
  const pending = all.reduce((a, g) => a + g.pending, 0);
  $("#scSummary").innerHTML = `
    <div class="metric"><div class="k">Calls recorded</div><div class="v">${total}</div>
      <div class="d">${pending} waiting for their horizon</div></div>
    <div class="metric"><div class="k">Graded</div><div class="v">${scored}</div>
      <div class="d">excludes "mixed"</div></div>
    <div class="metric"><div class="k">Overall accuracy</div>
      <div class="v ${scored ? (right / scored >= 0.5 ? "pos" : "neg") : ""}">${scored ? (right / scored * 100).toFixed(0) + "%" : "—"}</div>
      <div class="d">${scored ? right + " right · " + (scored - right) + " wrong" : "nothing graded yet"}</div></div>`;

  $("#scByKind").innerHTML = !all.length ? "" : `<div class="card table-card"><table><thead><tr>
    <th>Call type</th><th class="num">Horizon</th><th class="num">Recorded</th>
    <th class="num">Graded</th><th class="num">Accuracy</th><th class="num">Avg return</th>
    <th class="num" title="How often the call beat NIFTYBEES in its direction">Beat index</th>
    <th>By call</th></tr></thead><tbody>${all.map(g => `<tr>
      <td>${KIND_LABEL[g.kind] || g.kind}</td>
      <td class="num">${g.horizon_days === 1 ? "next day" : g.horizon_days + "d"}</td>
      <td class="num">${g.total}</td>
      <td class="num">${g.scored}${g.no_call ? ` <span class="muted">(+${g.no_call} mixed)</span>` : ""}</td>
      <td class="num">${g.accuracy == null ? `<span class="muted">—</span>` : `<b class="${g.accuracy >= 50 ? "pos" : "neg"}">${g.accuracy}%</b>`}</td>
      <td class="num">${_pct(g.avg_ret, 2)}</td>
      <td class="num">${g.beat_index_pct == null ? `<span class="muted">—</span>` : g.beat_index_pct + "%"}</td>
      <td>${Object.entries(g.by_call).map(([c, b]) => `${callChip(c)} <span class="muted">${
        b.accuracy == null ? "n/a" : b.accuracy + "% of " + (b.right + b.wrong)}</span>`).join(" &nbsp; ") || `<span class="muted">—</span>`}</td>
    </tr>`).join("")}</tbody></table>
    <div class="hint">Accuracy near 50% on next-day calls is what honest daily
      prediction looks like. What matters more is the 30/90-day verdict rows —
      and whether "strong" beats the index, not just zero.</div></div>`;

  if (!d.rows.length) {
    $("#scTable").innerHTML = `<div class="empty">${!(d.tracked || []).length
      ? `Nothing tracked yet — add stocks above (type one, or "+ watchlist" / "+ portfolio"),
         then "Snapshot all now". After that, every data refresh records and grades them automatically.`
      : `No calls recorded${sym || kind || status ? " for this filter" : " for the tracked stocks yet"}
         — press "Snapshot all now" to record today's calls, or wait for the next data refresh.`}</div>`;
    return;
  }
  $("#scTable").innerHTML = `<table><thead><tr>
    <th>Date</th><th>Symbol</th><th>Type</th><th>Call</th><th class="num">Price then</th>
    <th class="num">Horizon</th><th class="num">Price after</th><th class="num">Return</th>
    <th class="num">NIFTYBEES</th><th>Outcome</th></tr></thead><tbody>
    ${d.rows.map(r => `<tr title="${r.detail ? scDetail(r) : ""}">
      <td class="num">${r.date}</td>
      <td><b>${r.symbol.split(".")[0]}</b></td>
      <td>${KIND_LABEL[r.kind] || r.kind}</td>
      <td>${callChip(r.call)}${r.kind === "ml_nextday" && r.score != null ? ` <span class="muted">${(r.score * 100).toFixed(0)}%</span>` : ""}${r.kind === "checklist" && r.detail ? ` <span class="muted">${r.detail.passed}/${r.detail.applicable}</span>` : ""}</td>
      <td class="num">${fmt(r.price_at)}</td>
      <td class="num">${r.horizon_days === 1 ? "1 day" : r.horizon_days + "d"}</td>
      <td class="num">${r.price_after != null ? fmt(r.price_after) + `<br><span class="muted" style="font-size:.7em">${r.date_after}</span>` : `<span class="muted">—</span>`}</td>
      <td class="num">${_pct(r.ret_pct, 2)}</td>
      <td class="num">${_pct(r.bm_ret_pct, 2)}${r.beat_index != null ? `<br><span class="muted" style="font-size:.7em">${r.beat_index ? "beat index" : "lagged index"}</span>` : ""}</td>
      <td>${outcomeChip(r.outcome)}</td>
    </tr>`).join("")}</tbody></table>`;
}
window.loadScorecard = loadScorecard;

/* ---- tracked list ---- */
function renderTracked(list) {
  const box = $("#scTrackList");
  if (!box) return;
  const inWl = (sym) => (window.WL || []).some(i => i.symbol === sym);
  box.innerHTML = !list.length
    ? `<span class="muted">Nothing tracked yet.</span>`
    : list.map(t => `<span class="chip ${inWl(t.symbol) ? "" : "chip-ghost"}"
        title="${t.source} · since ${t.added_at}${inWl(t.symbol) ? "" : " · not on the watchlist: no price data will be downloaded for it until it is"}">
        ${t.symbol.split(".")[0]}<small class="muted"> .${t.symbol.split(".")[1] || ""}</small>
        <button class="chip-x" data-untrack="${t.symbol}" title="Stop tracking">×</button></span>`).join("");
  box.querySelectorAll("[data-untrack]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/scorecard/track/${encodeURIComponent(b.dataset.untrack)}`, { method: "DELETE" });
    loadScorecard();
  }));
}
async function trackAdd(body) {
  const msg = $("#scMsg");
  try {
    const r = await api("/api/scorecard/track", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    toast(`${r.added} stock${r.added === 1 ? "" : "s"} added to tracking.`, "success");
    $("#scTrackInput").value = "";
    loadScorecard();
  } catch (e) { msg.className = "inline-msg err"; msg.classList.remove("hidden"); msg.textContent = e.message; }
}
on("#scAddWl", "click", () => trackAdd({ source: "watchlist" }));
on("#scAddPf", "click", () => trackAdd({ source: "portfolio" }));
on("#scTrackAdd", "click", () => {
  const v = $("#scTrackInput").value.trim();
  if (v) trackAdd({ symbols: v.split(/[,\s]+/).filter(Boolean), source: "manual" });
});
on("#scTrackInput", "keydown", (e) => { if (e.key === "Enter") $("#scTrackAdd").click(); });
on("#scTrackedOnly", "change", loadScorecard);
/* suggestions from the watchlist (no network) */
on("#scTrackInput", "input", () => {
  const q = $("#scTrackInput").value.trim().toUpperCase(), box = $("#scTrackSuggest");
  const hits = !q ? [] : (window.WL || []).filter(i => i.type !== "mf" && i.symbol &&
    (i.symbol.includes(q) || (i.label || "").toUpperCase().includes(q))).slice(0, 8);
  if (!hits.length) { box.classList.add("hidden"); return; }
  box.innerHTML = hits.map(h => `<div class="suggest-item" data-sym="${h.symbol}">
    <span class="s-sym">${h.symbol.split(".")[0]}</span><span class="s-name">${h.label}</span>
    <span class="s-exch">${h.symbol.endsWith(".NS") ? "NSE" : "BSE"}</span></div>`).join("");
  box.classList.remove("hidden");
  box.querySelectorAll("[data-sym]").forEach(el => el.addEventListener("mousedown", (e) => {
    e.preventDefault(); box.classList.add("hidden");
    trackAdd({ symbols: [el.dataset.sym], source: "manual" });
  }));
});
on("#scTrackInput", "blur", () => setTimeout(() => $("#scTrackSuggest").classList.add("hidden"), 150));

function scDetail(r) {
  const d = r.detail;
  if (r.kind === "verdict") return [...(d.for || []).map(x => "✓ " + x), ...(d.against || []).map(x => "✗ " + x)].join("\n").replace(/"/g, "'");
  if (r.kind === "checklist") return `${d.passed}/${d.applicable} checks passed`;
  if (r.kind === "ml_nextday") return `model edge ${d.model_edge} (${d.verdict})`;
  return "";
}

["#scKind", "#scStatus"].forEach(s => on(s, "change", loadScorecard));
on("#scSymbol", "input", () => { clearTimeout(window._scT); window._scT = setTimeout(loadScorecard, 300); });
on("#scSnap", "click", async () => {
  const msg = $("#scMsg");
  msg.className = "inline-msg"; msg.classList.remove("hidden");
  msg.textContent = "Recording today's verdict + checklist for every watchlist stock…";
  try {
    await api("/api/scorecard/snapshot", { method: "POST" });
    const poll = setInterval(async () => {
      const s = await api("/api/scorecard/snapshot/status");
      if (!s.running) {
        clearInterval(poll);
        msg.textContent = (s.log[s.log.length - 1] || "Done.");
        msg.className = "inline-msg ok";
        loadScorecard();
      }
    }, 1500);
  } catch (e) { msg.textContent = e.message; msg.className = "inline-msg err"; }
});

/* home card */
async function loadHomeScore() {
  const card = $("#homeScoreCard");
  if (!card) return;
  try {
    const d = await api("/api/scorecard?limit=1");
    const v30 = d.summary.find(g => g.kind === "verdict" && g.horizon_days === 30);
    const total = d.summary.reduce((a, g) => a + g.total, 0);
    if (!total) { card.classList.add("hidden"); return; }
    card.classList.remove("hidden");
    const scored = d.summary.reduce((a, g) => a + g.scored, 0);
    const right = d.summary.reduce((a, g) => a + g.right, 0);
    $("#homeScore").innerHTML = `<div class="summary-row">
      <div class="metric"><div class="k">Calls logged</div><div class="v">${total}</div></div>
      <div class="metric"><div class="k">Graded</div><div class="v">${scored}</div></div>
      <div class="metric"><div class="k">Accuracy</div>
        <div class="v ${scored ? (right / scored >= 0.5 ? "pos" : "neg") : ""}">${scored ? (right / scored * 100).toFixed(0) + "%" : "—"}</div>
        <div class="d">${v30 && v30.accuracy != null ? "verdict @30d: " + v30.accuracy + "%" : "waiting on horizons"}</div></div>
    </div>`;
  } catch (e) { card.classList.add("hidden"); }
}
window.loadHomeScore = loadHomeScore;

/* links created after load (verdict card inside the drawer) */
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-goto]");
  if (!a) return;
  e.preventDefault();
  if ($("#drawerClose")) $("#drawerClose").click();
  document.querySelector(`.rail-link[data-page="${a.dataset.goto}"]`)?.click();
});
