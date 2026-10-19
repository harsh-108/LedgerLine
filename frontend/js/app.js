/* Watchlist Tracker frontend. Vanilla JS, no build step. */
const $ = (s) => document.querySelector(s);
/* attach without dying: if the element is missing (stale HTML vs new JS,
   or vice versa), log and skip instead of breaking the whole app */
const on = (sel, ev, fn) => {
  const el = $(sel);
  if (el) el.addEventListener(ev, fn);
  else console.warn("missing element for handler:", sel);
};
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = "/login"; throw new Error("Signed out."); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
};
const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const pctCls = (v) => (v >= 0 ? "pos" : "neg");
const pctTxt = (v) => (v == null ? "" : `${v >= 0 ? "▲" : "▼"} ${Math.abs(v).toFixed(2)}%`);

/* ------------------------------------------------ notifications
   In-app toasts + modal forms replacing the browser's native alert()
   and prompt() dialogs (which carry the ugly "localhost:8000 says"
   chrome). Icons are motion-first animated SVGs in the style of
   Its Hover (itshover.com, open source) — the icon animates with
   intent as the toast lands. */
const ICONS = {
  success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle class="ico-ring" cx="12" cy="12" r="9.5"/>
      <path class="ico-draw" d="M8 12.4l2.7 2.7L16 9.4"/></svg>`,
  error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path class="ico-shake" d="M10.3 3.9L2.6 17.2a2 2 0 001.7 3h15.4a2 2 0
        001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/>
      <line class="ico-pop" x1="12" y1="9" x2="12" y2="13.2"/>
      <circle class="ico-pop" cx="12" cy="16.6" r="0.4" fill="currentColor"/></svg>`,
  info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <g class="ico-swing">
      <path d="M18 8a6 6 0 10-12 0c0 7-2.4 8.4-2.4 8.4h16.8S18 15 18 8z"/>
      <path d="M10.3 20.4a2 2 0 003.4 0"/></g></svg>`,
};
function toast(msg, type = "info", ms = 4200) {
  let box = $("#toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "toasts";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = `<span class="toast-ico">${ICONS[type] || ICONS.info}</span>
    <span class="toast-msg"></span><button class="toast-x" aria-label="Dismiss">×</button>`;
  t.querySelector(".toast-msg").textContent = msg;
  const gone = () => {
    t.classList.add("out");
    setTimeout(() => t.remove(), 260);
  };
  t.querySelector(".toast-x").addEventListener("click", gone);
  box.appendChild(t);
  setTimeout(gone, ms);
}

/* Modal form: dlgForm(title, [{name,label,type,value,placeholder}], submit)
   -> Promise resolving {name: value, ...} or null on cancel. */
function dlgForm(title, fields, submitLabel = "Save") {
  return new Promise((resolve) => {
    const ov = document.createElement("div");
    ov.className = "dlg-overlay";
    ov.innerHTML = `<div class="dlg" role="dialog" aria-modal="true">
      <div class="dlg-title"></div>
      <div class="dlg-fields"></div>
      <div class="dlg-actions">
        <button class="btn ghost dlg-cancel" type="button">Cancel</button>
        <button class="btn dlg-ok" type="button"></button>
      </div></div>`;
    ov.querySelector(".dlg-title").textContent = title;
    ov.querySelector(".dlg-ok").textContent = submitLabel;
    const holder = ov.querySelector(".dlg-fields");
    fields.forEach((f) => {
      const w = document.createElement("label");
      w.className = "dlg-field";
      const cap = document.createElement("span");
      cap.textContent = f.label;
      const inp = document.createElement("input");
      inp.type = f.type || "text";
      inp.name = f.name;
      if (f.value != null) inp.value = f.value;
      if (f.placeholder) inp.placeholder = f.placeholder;
      if (f.step) inp.step = f.step;
      w.append(cap, inp);
      holder.appendChild(w);
    });
    const close = (val) => {
      ov.classList.add("out");
      setTimeout(() => ov.remove(), 180);
      resolve(val);
    };
    ov.querySelector(".dlg-cancel").addEventListener("click", () => close(null));
    ov.addEventListener("click", (e) => { if (e.target === ov) close(null); });
    ov.addEventListener("keydown", (e) => { if (e.key === "Escape") close(null); });
    ov.querySelector(".dlg-ok").addEventListener("click", () => {
      const out = {};
      ov.querySelectorAll("input").forEach((i) => { out[i.name] = i.value; });
      close(out);
    });
    holder.addEventListener("keydown", (e) => {
      if (e.key === "Enter") ov.querySelector(".dlg-ok").click();
    });
    document.body.appendChild(ov);
    const first = holder.querySelector("input");
    if (first) first.focus();
  });
}

/* ------------------------------------------------ navigation */
document.querySelectorAll(".rail-link").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".rail-link").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    $(`#page-${b.dataset.page}`).classList.remove("hidden");
    if (b.dataset.page === "portfolio") loadPortfolio();
    if (b.dataset.page === "journal") loadJournal();
    if (b.dataset.page === "ailab" || b.dataset.page === "backtest") loadEligible();
    if (b.dataset.page === "backtest") loadStrategies();
    if (b.dataset.page === "screener") refreshUniverses();
    if (b.dataset.page === "home") loadHome();
    if (b.dataset.page === "more") loadMore();
    if (b.dataset.page === "funds" && window.loadFunds) loadFunds();
    if (b.dataset.page === "scorecard" && window.loadScorecard) loadScorecard();
  })
);

/* ------------------------------------------------ sparklines */
function sparkSVG(vals, w = 96, h = 28) {
  if (!vals || vals.length < 2) return "";
  const lo = Math.min(...vals), hi = Math.max(...vals), rng = hi - lo || 1;
  const pts = vals.map((v, i) =>
    `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - lo) / rng) * (h - 4)).toFixed(1)}`
  ).join(" ");
  const color = vals[vals.length - 1] >= vals[0] ? "var(--up)" : "var(--down)";
  return `<svg width="${w}" height="${h}"><polyline points="${pts}" fill="none"
    stroke="${color}" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/></svg>`;
}

/* ------------------------------------------------ watchlist */
const skeleton = (n = 5) =>
  `<div class="skel">${'<div class="skel-row"></div>'.repeat(n)}</div>`;
let WL = [];
let PREV_PRICES = {};
async function loadWatchlist() {
  let data;
  try {
    data = await api("/api/watchlist");
  } catch (e) {
    $("#wlList").innerHTML =
      `<div class="inline-msg err">Could not load the watchlist: ${e.message}.
       Check the uvicorn terminal for the traceback, then reload.</div>`;
    return;
  }
  WL = data.items;
  $("#freshness").textContent = data.last_date ? `data through ${data.last_date}` : "no data yet";
  $("#railStatus").textContent =
    `${WL.filter(i => i.type === "stock").length} stocks · ` +
    `${WL.filter(i => i.type === "etf").length} ETFs · ` +
    `${WL.filter(i => i.type === "mf").length} MFs\n${data.signals_today} signals today`;
  renderWatchlist();
  const ups = WL.filter(i => i.pct != null && i.pct >= 0).length;
  const dns = WL.filter(i => i.pct != null && i.pct < 0).length;
  const priced = WL.filter(i => i.pct != null);
  let best = null, worst = null;
  if (priced.length) {
    best = priced.reduce((a, b) => (a.pct > b.pct ? a : b));
    worst = priced.reduce((a, b) => (a.pct < b.pct ? a : b));
  }
  $("#wlSummary").innerHTML = `
    <div class="metric"><div class="k">Advancing / declining</div>
      <div class="v">${ups} / ${dns}</div></div>
    ${best ? `<div class="metric"><div class="k">Top gainer</div>
      <div class="v">${best.label}</div>
      <div class="d pos">${pctTxt(best.pct)}</div></div>` : ""}
    ${worst ? `<div class="metric"><div class="k">Top loser</div>
      <div class="v">${worst.label}</div>
      <div class="d neg">${pctTxt(worst.pct)}</div></div>` : ""}
    <div class="metric"><div class="k">Signals today</div>
      <div class="v">${data.signals_today}</div></div>`;
  const chg = document.getElementById("changedCard") ||
    Object.assign(document.createElement("div"),
                  { id: "changedCard", className: "card" });
  /* fill the right-hand grid column instead of dangling full-width
     below the grid (which left an ugly async-looking gap) */
  const rightCol = document.querySelector("#page-home .grid-2 > div:last-child");
  (rightCol || $("#page-home")).appendChild(chg);
  loadChanged();
  loadTape();
  loadAlerts();
  loadTiers();
  if (window.loadHomeScore) loadHomeScore();
}

function priceFlash(i) {
  const prev = PREV_PRICES[i.id];
  PREV_PRICES[i.id] = i.last;
  if (prev == null || i.last == null || prev === i.last) return "";
  return i.last > prev ? "flash-up" : "flash-down";
}

function renderWatchlist() {
  const q = $("#search").value.toLowerCase();
  const items = WL.filter(i =>
    !q || i.label.toLowerCase().includes(q) || (i.symbol || "").toLowerCase().includes(q));
  if (!items.length) { $("#wlList").innerHTML = `<div class="empty">Nothing matches.</div>`; return; }
  const draggable = !q;               /* reorder only makes sense unfiltered */
  $("#wlList").innerHTML = items.map(i => `
    <div class="wl-row" data-id="${i.id}" ${draggable ? 'draggable="true"' : ""}>
      <div><div class="wl-name">${i.label}${tierChip(i.symbol)}</div>
        <div class="wl-sub">${i.symbol || "MF " + i.scheme_code}${
          i.source === "smartapi"
            ? ` <span class="src-chip" title="History from Angel One SmartAPI (raw exchange prices — long-term charts won't match split-adjusted sources)">AO</span>`
            : ""}</div></div>
      <div class="wl-spark">${sparkSVG(i.spark)}</div>
      <div class="wl-price ${priceFlash(i)}">${fmt(i.last)}
        <span class="wl-chg ${i.pct != null ? pctCls(i.pct) : ""}">${pctTxt(i.pct)}</span></div>
      <div><span class="tag-chip ${i.tag ? "gold" : ""}">${i.tag || i.type}</span></div>
      <button class="rm-btn" data-rm="${i.id}" title="Remove">✕</button>
    </div>`).join("");
  document.querySelectorAll(".wl-row").forEach(r =>
    r.addEventListener("click", (e) => {
      if (e.target.dataset.rm) return;
      openDrawer(WL.find(i => i.id == r.dataset.id));
    }));
  document.querySelectorAll(".rm-btn").forEach(b =>
    b.addEventListener("click", async () => {
      await api(`/api/watchlist/${b.dataset.rm}`, { method: "DELETE" });
      loadWatchlist();
    }));
  if (draggable) wireDragReorder();
}
$("#search").addEventListener("input", renderWatchlist);

/* ---- add-ticker autocomplete ---- */
let sgTimer = null, sgItems = [], sgSel = -1;
const sgBox = () => $("#suggestBox");
function sgHide() { sgBox().classList.add("hidden"); sgSel = -1; }
function sgRender() {
  if (!sgItems.length) { sgHide(); return; }
  sgBox().innerHTML = sgItems.map((s, i) => `
    <div class="suggest-item ${i === sgSel ? "sel" : ""}" data-i="${i}">
      <span class="s-sym">${s.symbol.split(".")[0]}</span>
      <span class="s-name">${s.name}</span>
      <span class="s-exch">${s.exch}${s.type === "etf" ? " · ETF" : ""}</span>
    </div>`).join("");
  sgBox().classList.remove("hidden");
  sgBox().querySelectorAll(".suggest-item").forEach(el =>
    el.addEventListener("mousedown", e => { e.preventDefault(); sgPick(+el.dataset.i); }));
}
let sgPickedMf = null;                 /* {scheme_code, name} in MF mode */
function sgPick(i) {
  const s = sgItems[i];
  if (!s) return;
  if (s.type === "mf") {
    sgPickedMf = { scheme_code: +s.symbol, name: s.name };
    $("#addSymbol").value = s.name;
  } else {
    $("#addSymbol").value = s.symbol;
    $("#addType").value = s.type;
  }
  sgHide();
  $("#addBtn").focus();
}
$("#addType").addEventListener("change", () => {
  const mf = $("#addType").value === "mf";
  $("#addSymbol").placeholder = mf
    ? "Fund name · e.g. motilal oswal small cap (3+ letters)"
    : "Add ticker · type 2+ letters";
  $("#addSymbol").value = ""; sgHide();
});
$("#addSymbol").addEventListener("input", () => {
  clearTimeout(sgTimer);
  const q = $("#addSymbol").value.trim();
  if ($("#addType").value === "mf") {           /* mutual-fund mode */
    if (q.length < 3) { sgHide(); return; }
    sgBox().innerHTML = `<div class="suggest-item muted">Searching AMFI schemes…</div>`;
    sgBox().classList.remove("hidden");
    sgTimer = setTimeout(async () => {
      try {
        const d = await api(`/api/mf/search?q=${encodeURIComponent(q)}`);
        sgItems = d.results.map(r => ({ symbol: String(r.scheme_code), name: r.name,
                                        exch: "AMFI", type: "mf" }));
        sgSel = -1;
        if (!sgItems.length) {
          sgBox().innerHTML = `<div class="suggest-item muted">No scheme matches "${q}" on mfapi.in — try fewer words.</div>`;
          return;
        }
        sgRender();
      } catch (e) {
        sgBox().innerHTML = `<div class="suggest-item muted">Fund search failed: ${e.message}</div>`;
      }
    }, 350);
    return;
  }
  if (q.length < 2) { sgHide(); return; }
  sgBox().innerHTML = `<div class="suggest-item muted">Searching…</div>`;
  sgBox().classList.remove("hidden");
  sgTimer = setTimeout(async () => {
    try {
      const d = await api(`/api/symbol-search?q=${encodeURIComponent(q)}`);
      sgItems = d.items; sgSel = -1;
      if (!d.items.length) {
        sgBox().innerHTML = `<div class="suggest-item muted">${d.error
          ? `Search unavailable (${d.error}) — type the exact symbol, e.g. MODEFENCE`
          : `No NSE/BSE match for "${q}" — try fewer words or the symbol itself`}.
          Looking for a mutual fund? Switch the type to <b>Mutual fund</b>.</div>`;
        return;
      }
      sgRender();
    } catch (e) {
      sgBox().innerHTML = `<div class="suggest-item muted">Search failed: ${e.message}. Restart uvicorn if this persists.</div>`;
    }
  }, 220);
});
$("#addSymbol").addEventListener("keydown", e => {
  if (sgBox().classList.contains("hidden")) return;
  if (e.key === "ArrowDown") { e.preventDefault(); sgSel = Math.min(sgSel + 1, sgItems.length - 1); sgRender(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); sgSel = Math.max(sgSel - 1, 0); sgRender(); }
  else if (e.key === "Enter" && sgSel >= 0) { e.preventDefault(); sgPick(sgSel); }
  else if (e.key === "Escape") sgHide();
});
$("#addSymbol").addEventListener("blur", () => setTimeout(sgHide, 150));

$("#addBtn").addEventListener("click", async () => {
  const sym = $("#addSymbol").value.trim();
  if (!sym) return;
  const msg = $("#addMsg");
  if ($("#addType").value === "mf") {
    const pick = sgPickedMf && sgPickedMf.name === sym ? sgPickedMf
      : (/^\d{5,7}$/.test(sym) ? { scheme_code: +sym, name: "" } : null);
    if (!pick) {
      msg.className = "inline-msg err";
      msg.textContent = "Pick a fund from the suggestions (or type its AMFI scheme code).";
      return;
    }
    msg.className = "inline-msg"; msg.textContent = `Adding ${pick.name || pick.scheme_code} and downloading NAV history…`;
    try {
      const r = await api("/api/mf/add", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheme_code: pick.scheme_code, label: (pick.name || "").slice(0, 60) }),
      });
      msg.className = "inline-msg " + (r.note ? "warn" : "ok");
      msg.textContent = r.note || `Added ${r.name} — ${r.rows.toLocaleString()} NAVs. It's on the Funds page too.`;
      $("#addSymbol").value = ""; sgPickedMf = null;
      await loadWatchlist();
    } catch (e) { msg.className = "inline-msg err"; msg.textContent = e.message; }
    return;
  }
  msg.className = "inline-msg"; msg.textContent = `Validating & downloading ${sym}…`;
  try {
    const r = await api("/api/watchlist/add", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, asset_type: $("#addType").value }),
    });
    msg.className = "inline-msg ok";
    msg.textContent = `Added ${r.symbol} — ${r.rows.toLocaleString()} days of history.`;
    $("#addSymbol").value = "";
    await loadWatchlist();
    const it = WL.find(i => i.symbol === r.symbol);
    if (it) {
      const row = document.querySelector(`.wl-row[data-id="${it.id}"]`);
      if (row) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        row.classList.add("flash");
        setTimeout(() => row.classList.remove("flash"), 2400);
      }
    }
  } catch (e) { msg.className = "inline-msg err"; msg.textContent = e.message; }
});

/* ------------------------------------------------ refresh */
$("#refreshBtn").addEventListener("click", async () => {
  $("#refreshBtn").classList.add("busy");        // icon spins while running
  await api("/api/refresh", { method: "POST" });
  $("#refreshLog").classList.remove("hidden");
  const timer = setInterval(async () => {
    const s = await api("/api/refresh/status");
    $("#refreshLog").textContent = s.log.join("\n") || "starting…";
    if (!s.running && s.done) {
      clearInterval(timer);
      $("#refreshBtn").classList.remove("busy");
      $("#refreshLog").textContent += "\nDone.";
      setTimeout(() => $("#refreshLog").classList.add("hidden"), 4000);
      loadWatchlist();
    }
  }, 1200);
});

/* ------------------------------------------------ NSE sync */
$("#nseBtn").addEventListener("click", async () => {
  $("#nseBtn").classList.add("busy");
  try { await api("/api/nse/sync", { method: "POST" }); }
  catch (e) {
    $("#nseBtn").classList.remove("busy");
    $("#refreshLog").classList.remove("hidden");
    $("#refreshLog").textContent = e.message;
    return;
  }
  $("#refreshLog").classList.remove("hidden");
  const t = setInterval(async () => {
    const s = await api("/api/nse/status");
    $("#refreshLog").textContent = s.log.join("\n") || "starting NSE sync…";
    if (!s.running && s.result) {
      clearInterval(t);
      $("#nseBtn").classList.remove("busy");
      const r = s.result;
      let tail = `\nMatched ${r.matched}/${r.checked}. `;
      if (r.mismatches && r.mismatches.length)
        tail += "MISMATCHES: " + r.mismatches.map(m =>
          `${m.symbol} (ours ${m.ours} vs NSE ${m.nse}, ${m.diff_pct}%)`).join(", ") +
          " — consider re-downloading those.";
      else tail += "No mismatches — your data agrees with the exchange.";
      $("#refreshLog").textContent += tail;
    }
  }, 1500);
});

/* ------------------------------------------------ drawer + charts */
const CHART_OPTS = {
  layout: { background: { color: "transparent" }, textColor: "#7E8290",
            fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
  grid: { vertLines: { color: "#1B1D24" }, horzLines: { color: "#1B1D24" } },
  rightPriceScale: { borderColor: "#23252D" },
  timeScale: { borderColor: "#23252D" },
  crosshair: { mode: 0 },
};
let drawerCharts = [];
function clearCharts() { drawerCharts.forEach(c => c.remove()); drawerCharts = []; }

function statCards(stats) {
  return `<div class="summary-row">` + Object.entries(stats).map(([k, v]) => {
    const isRet = /return|CAGR/.test(k);
    const cls = isRet ? (String(v).startsWith("+") ? "pos" : "neg") : "";
    return `<div class="metric"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`;
  }).join("") + `</div>`;
}


/* ---------------- verdict card (synthesis of the app's own checks) */
function trackRecordLine(tr) {
  if (!tr || !Object.keys(tr).length) {
    return `<div class="vd-track muted">Track record on this stock: no graded
      calls yet — today's call was recorded and will be graded after 1M / 3M
      (see Scorecard).</div>`;
  }
  const part = (h) => tr[h] ? `${h}d: ${tr[h].right}/${tr[h].right + tr[h].wrong} right` : null;
  return `<div class="vd-track">Track record on this stock — ${
    [part(30), part(90)].filter(Boolean).join(" · ")}
    <a href="#" data-goto="scorecard" class="vd-link">scorecard →</a></div>`;
}
async function loadVerdict(symbol) {
  const holder = document.getElementById("verdictHolder");
  if (!holder) return;
  try {
    const v = await api(`/api/verdict/${symbol}`);
    const col = { strong: "var(--up)", mixed: "var(--warn)",
                  weak: "var(--down)" }[v.tier];
    const li = (arr, cls, mark) => arr.map(r =>
      `<li class="${cls}">${mark} ${r.text}
         <span class="vd-src">${r.source}</span></li>`).join("");
    holder.innerHTML = `
      <div class="vd-card" style="--vd:${col}">
        <div class="vd-head">
          <span class="vd-tier">${v.tier === "strong" ? "STRONG CASE"
            : v.tier === "weak" ? "WEAK CASE" : "MIXED"}</span>
          <span class="ifx-i" data-key="__verdict" style="display:inline-flex"></span>
        </div>
        <ul class="vd-list">
          ${li(v.for, "vd-for", "✓")}${li(v.against, "vd-against", "✗")}
        </ul>
        ${trackRecordLine(v.track_record)}
        <div class="hint">${v.note}</div>
      </div>`;
    holder.querySelector(".ifx-i").textContent = "i";
  } catch (e) { holder.innerHTML = ""; }
}

/* ---------------- position sizer: from "whether" to "how much" */
function sizerHtml(symbol) {
  return `<div class="section-label">Position size
      <span class="ifx-i" data-key="__sizer">i</span></div>
    <div class="sizer" data-sym="${symbol}">
      <label>Capital ₹<input id="szCap" type="number" min="0"
        placeholder="500000"></label>
      <label>Risk %<input id="szRisk" type="number" min="0.1" step="0.1"
        value="1"></label>
      <label>Entry ₹<input id="szEntry" type="number" min="0"
        placeholder="last price"></label>
      <label>Stop ₹<input id="szStop" type="number" min="0"
        placeholder="support level"></label>
      <div class="sizer-out num" id="szOut">Fill the fields — shares
        sized so a stop-out costs exactly your risk budget.</div>
    </div>`;
}
function wireSizer() {
  const out = document.getElementById("szOut");
  if (!out) return;
  const g = (id) => +document.getElementById(id).value;
  const upd = () => {
    const cap = g("szCap"), riskPct = g("szRisk"),
          entry = g("szEntry"), stop = g("szStop");
    if (!(cap > 0 && riskPct > 0 && entry > 0 && stop > 0)) return;
    if (stop >= entry) {
      out.textContent = "Stop must be below entry for a long position.";
      return;
    }
    const riskAmt = cap * riskPct / 100;
    const shares = Math.floor(riskAmt / (entry - stop));
    const invested = shares * entry;
    out.innerHTML = shares <= 0
      ? "Risk budget too small for even one share at this stop."
      : `<b>${shares} shares</b> = ₹${invested.toLocaleString("en-IN")}
         (${(invested / cap * 100).toFixed(1)}% of capital) ·
         stop-out loses ₹${Math.round(shares * (entry - stop))
           .toLocaleString("en-IN")} (${riskPct}%)`
        + (invested / cap > 0.25
           ? ` <span class="vd-against">· above 25% concentration —
               deliberate?</span>` : "");
  };
  ["szCap", "szRisk", "szEntry", "szStop"].forEach((id) =>
    document.getElementById(id).addEventListener("input", upd));
}

/* ---------------- what-changed card on Home */
async function loadChanged() {
  const host = document.getElementById("changedCard");
  if (!host) return;
  try {
    const d = await api("/api/changed");
    if (!d.since) {
      host.innerHTML = `<div class="hint">First visit marker set —
        from now on this card shows what changed while you were away.</div>`;
      return;
    }
    if (!d.signals.length) {
      host.innerHTML = `<div class="hint">Nothing new since
        ${d.since} — no fresh signals. "Do nothing" is a position.</div>`;
      return;
    }
    const rupee = (p) => p == null ? "—"
      : (+p).toLocaleString("en-IN", { maximumFractionDigits: 2 });
    host.innerHTML = `<div class="section-label">Since your last visit
        (${d.since})</div>` +
      d.signals.slice(0, 6).map(s =>
        `<div class="chg-row"><b>${s.symbol.split(".")[0]}</b>
           ${s.signal} @ ₹${rupee(s.price)}
           <span class="vd-src">${s.at}</span></div>`).join("");
  } catch (e) { host.innerHTML = ""; }
}

async function openDrawer(item) {
  $("#drawer").classList.add("open");
  $("#drawerScrim").classList.remove("hidden");
  $("#drawerTitle").textContent = item.label;
  /* symbol avatar: initials on a hue derived from the name, so every
     stock gets a stable identity colour */
  const base = (item.symbol || item.label || "?").split(".")[0];
  const hue = [...base].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  const av = $("#drawerAvatar");
  av.textContent = base.slice(0, 2);
  av.style.background =
    `linear-gradient(135deg, hsl(${hue} 55% 38%), hsl(${(hue + 40) % 360} 55% 26%))`;
  /* untracked symbol (opened from the tape or elsewhere): offer to watch */
  const tracked = item.id != null;
  $("#drawerTag").classList.toggle("hidden", !tracked);
  const wbtn = $("#drawerWatch");
  wbtn.classList.toggle("hidden", tracked);
  wbtn.onclick = async () => {
    wbtn.disabled = true; wbtn.textContent = "Adding…";
    try {
      await api("/api/watchlist/add", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: item.symbol,
                               asset_type: item.type || "stock" }),
      });
      wbtn.textContent = "Watching ✓";
      await loadWatchlist();
    } catch (e) { wbtn.textContent = e.message.slice(0, 40); }
    finally { wbtn.disabled = false; }
  };
  $("#drawerTag").value = item.tag || "";
  $("#drawerTag").onchange = async () => {
    if (item.id == null) return;
    await api(`/api/watchlist/${item.id}/tag`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: $("#drawerTag").value }),
    });
    loadWatchlist();
  };
  const body = $("#drawerBody");
  body.innerHTML = skeleton(4);
  window.__drawerSymbol = item.symbol;   /* for verdict/sizer loaders */
  clearCharts();
  try {
    if (item.type === "mf") {
      const d = await api(`/api/mf/${item.scheme_code}`);
      body.innerHTML = statCards(d.stats) +
        (window.mfDrawerExtras ? mfDrawerExtras(d) : "") +
        `<div class="section-label">NAV history</div><div id="navChart" class="chart-box"></div>`;
      const c = LightweightCharts.createChart($("#navChart"), CHART_OPTS);
      c.addLineSeries({ color: "#D9B45B", lineWidth: 2 }).setData(d.nav);
      c.timeScale().fitContent(); drawerCharts.push(c);
    } else {
      const d = await api(`/api/detail/${item.symbol}`);
      let html = statCards(d.stats);
      if (d.delivery) {
        const strong = d.delivery[1] >= 60;
        html += `<div class="summary-row"><div class="metric">
          <div class="k">Delivery % (NSE · ${d.delivery[0]})</div>
          <div class="v ${strong ? "pos" : ""}">${d.delivery[1].toFixed(1)}%</div>
          <div class="d">${strong ? "high — real accumulation" : "of traded qty taken as delivery"}</div>
        </div></div>`;
      }
      if (d.position) {
        const p = d.position;
        const vs = p.stock_ret_since != null ? `
          <div class="pos-vs">Since your first buy (${p.first_buy}):
            this stock <b class="${pctCls(p.stock_ret_since)}">${p.stock_ret_since >= 0 ? "+" : ""}${p.stock_ret_since}%</b>
            · NIFTYBEES <b class="${pctCls(p.index_ret_since)}">${p.index_ret_since >= 0 ? "+" : ""}${p.index_ret_since}%</b>
            — ${p.stock_ret_since >= p.index_ret_since
              ? "your pick is ahead of the index so far."
              : "the index has done better with the same time."}</div>` : "";
        const lotRows = p.lots.length > 1 ? `
          <div class="lot-list">${p.lots.map((l, i) => `
            <div class="lot-row">
              <span>Lot ${i + 1}</span>
              <span class="num">${l.qty} @ ₹${fmt(l.buy_price)}</span>
              ${l.thesis ? `<span class="lot-thesis" title="Your thesis at buy time">“${l.thesis}”</span>` : ""}
              <span class="num muted">${l.buy_date || "—"}</span>
              <button class="btn btn-small" data-lotsell="${l.id}" data-lotqty="${l.qty}" title="Record a sale from this lot">Sell</button>
              <button class="rm-btn" style="opacity:1" data-lotrm="${l.id ?? ""}" title="Delete this lot (no sale recorded)">✕</button>
            </div>`).join("")}</div>` : "";
        const lotSell = p.lots.length === 1
          ? `<button class="btn btn-small" style="float:right" data-lotsell="${p.lots[0].id}" data-lotqty="${p.lots[0].qty}">Sell</button>` : "";
        html += `<div class="section-label">Your position ${lotSell}</div>
          <div class="pos-card">
            <div class="summary-row">
              <div class="metric"><div class="k">Held</div>
                <div class="v">${p.qty} sh</div>
                <div class="d">avg ₹${fmt(p.avg_cost)}</div></div>
              <div class="metric"><div class="k">Invested</div>
                <div class="v">₹${fmt(p.invested, 0)}</div></div>
              <div class="metric"><div class="k">P&amp;L</div>
                <div class="v ${pctCls(p.pnl)}">₹${fmt(p.pnl, 0)}</div>
                <div class="d ${pctCls(p.pnl_pct)}">${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct}%</div></div>
              ${p.holding_days != null ? `<div class="metric"><div class="k">Holding for</div>
                <div class="v">${p.holding_days}d</div>
                <div class="d">${p.ltcg_eligible ? "LTCG window (>1y)" : `STCG until day 366 (${366 - p.holding_days} to go)`}</div></div>` : ""}
              ${p.dividends ? `<div class="metric"><div class="k">Dividends</div>
                <div class="v">₹${fmt(p.dividends, 0)}</div></div>` : ""}
            </div>${vs}
            ${lotRows}
            <div class="hint">The hold/sell decision needs three things this
            panel now shows: what you'd give up vs the index, your tax window,
            and the checklist + base rates below. It stays your call.</div>
          </div>`;
      }
      html += `<div id="verdictHolder"></div>`;
      html += `<div class="section-label">Price · SMA 50/200</div>
               <div class="ind-toggles">
                 <label><input type="checkbox" id="tgVol" checked> Volume</label>
                 <label><input type="checkbox" id="tgEma"> EMA 20</label>
                 <label><input type="checkbox" id="tgBb"> Bollinger</label>
                 <label><input type="checkbox" id="tgMacd"> MACD</label>
               </div>
               <div id="priceChart" class="chart-box"></div>
               <div id="macdChart" class="chart-box small hidden"></div>
               <div class="section-label">RSI 14</div>
               <div id="rsiChart" class="chart-box small"></div>`;
      if (d.checklist) {
        const ck = d.checklist;
        const col = { strong: "var(--up)", mixed: "var(--accent)", weak: "var(--down)" }[ck.tier];
        html += `<div class="section-label">Checklist verdict</div>
          <div class="ck-tier" style="color:${col}">
            ${ck.tier.toUpperCase()} — ${ck.passed}/${ck.applicable} checks passed</div>
          <ul class="ck-list">
            ${ck.pros.map(p => `<li class="ck-pro">${p}</li>`).join("")}
            ${ck.cons.map(c => `<li class="ck-con">${c}</li>`).join("")}
            ${ck.notes.map(n => `<li class="ck-note">${n}</li>`).join("")}
          </ul>
          <div class="hint">${ck.tier_text}</div>
          ${ck.decision_frame ? `<div class="ck-frame">${ck.decision_frame}</div>` : ""}`;
      }
      html += sizerHtml(item.symbol);
      if (d.base_rates) {
        const br = d.base_rates, HZ = ["1m", "3m", "6m"];
        const cell = (s) => s.n < 3
          ? `<td class="num muted" colspan="4">only ${s.n}× — too few to summarize</td>`
          : `<td class="num ${pctCls(s.median)}">${s.median >= 0 ? "+" : ""}${s.median}%</td>
             <td class="num">${s.hit_rate}%</td>
             <td class="num pos">+${s.best}%</td>
             <td class="num neg">${s.worst}%</td>`;
        const block = (title, horizons, occurrences, active) => `
          <div class="br-block ${active ? "br-active" : ""}">
            <div class="br-title">${title}
              ${active ? `<span class="tag-chip gold">active now</span>` : ""}
              <span class="br-n">${occurrences}× in ${br.years}y</span></div>
            <table class="br-table"><thead><tr>
              <th>After</th><th class="num">Median</th><th class="num">Positive</th>
              <th class="num">Best</th><th class="num">Worst</th></tr></thead><tbody>
              ${HZ.map(h => `<tr><td>${h}</td>${cell(horizons[h])}</tr>`).join("")}
            </tbody></table>
          </div>`;
        const shown = br.signals.filter(s =>
          s.occurrences >= 1 && (s.occurrences >= 3 || br.active.includes(s.signal)));
        if (shown.length) {
          html += `<div class="section-label">What happened historically</div>
            <div class="hint">Every past time each signal fired on THIS stock,
            and the stock's return afterwards. Compare against the baseline —
            a signal only matters if it beats it.</div>` +
            block(`Any period (baseline)`, br.baseline, "all", false) +
            shown.map(s =>
              block(s.label, s.horizons, s.occurrences,
                    br.active.includes(s.signal))).join("") +
            `<div class="hint">${br.note}</div>`;
        }
      }
      if (d.fundamentals) {
        const F = d.fundamentals, L = {
          sector: "Sector", marketCap: "Mkt cap", trailingPE: "P/E",
          priceToBook: "P/B", trailingEps: "EPS", returnOnEquity: "ROE",
          profitMargins: "Margin", debtToEquity: "D/E", dividendYield: "Div yield", beta: "Beta",
        };
        const fmtF = (k, v) => {
          if (v == null) return "—";
          if (k === "marketCap") return "₹" + fmt(v / 1e7, 0) + " Cr";
          if (k === "returnOnEquity" || k === "profitMargins") return (v * 100).toFixed(1) + "%";
          if (k === "dividendYield") return ((v < 1 ? v * 100 : v)).toFixed(2) + "%";
          return typeof v === "number" ? fmt(v) : v;
        };
        html += `<div class="section-label">Fundamentals
          <span style="text-transform:none;letter-spacing:0"> · Yahoo snapshot ${d.fundamentals_updated || ""}</span></div>
          <div class="summary-row">` +
          Object.entries(L).filter(([k]) => F[k] != null).map(([k, lab]) =>
            `<div class="metric"><div class="k">${lab}</div><div class="v">${fmtF(k, F[k])}</div></div>`
          ).join("") + `</div>
          <div class="hint">Cross-check on screener.in before any decision — Yahoo's Indian fundamentals can be stale.</div>`;
      }
      html += `<div class="section-label">Your notes</div>
        <div id="ntList" class="nt-list"></div>
        <div class="add-row">
          <input id="ntInput" type="text" class="wide"
                 placeholder="Why are you watching this? Thesis, levels, doubts…">
          <button id="ntAdd" class="btn">Save</button>
        </div>`;
      html += `<div class="section-label">Compare</div>
        <div class="add-row">
          <select id="cmpSel"><option value="">Overlay another stock…</option>${
            WL.filter(w => w.type === "stock" && w.symbol !== item.symbol)
              .map(w => `<option value="${w.symbol}">${w.label}</option>`).join("")
          }</select>
        </div>
        <div id="cmpChart" class="chart-box small hidden"></div>
        <div id="cmpNote" class="hint hidden"></div>`;
      html += `<div class="section-label">More research</div>
        <div class="research-strip">
          <button class="btn btn-small" data-rs="patterns">Patterns</button>
          <button class="btn btn-small" data-rs="financials">Financials</button>
          <button class="btn btn-small" data-rs="peers">Peers</button>
          <button class="btn btn-small" data-rs="events">Events</button>
          <button class="btn btn-small" data-rs="delivery">Delivery %</button>
          <button class="btn btn-small" data-rs="depth">Depth</button>
        </div>
        <div id="rsOut"></div>`;
      body.innerHTML = html;
      loadVerdict(item.symbol);
      wireSizer(item.symbol);
      document.querySelectorAll("[data-rs]").forEach(b =>
        b.addEventListener("click", () => loadResearch(b.dataset.rs, item.symbol)));
      wireCompare(item, d.candles);
      wireNotes(item.symbol);
      document.querySelectorAll("[data-lotsell]").forEach(b =>
        b.addEventListener("click", async () => {
          const maxq = +b.dataset.lotqty;
          const vals = await dlgForm(`Sell ${item.symbol.split(".")[0]}`, [
            { name: "qty", label: `Quantity (you hold ${maxq})`,
              type: "number", value: maxq, step: "any" },
            { name: "price", label: "Sell price per share (₹)",
              type: "number", step: "any", placeholder: "0.00" },
            { name: "date", label: "Sell date", type: "date",
              value: new Date().toISOString().slice(0, 10) },
          ], "Record sell");
          if (!vals) return;
          const qty = parseFloat(vals.qty), price = parseFloat(vals.price);
          if (!(qty > 0)) return toast("Quantity must be positive.", "error");
          if (!(price > 0)) return toast("Sell price must be positive.", "error");
          if (!vals.date) return toast("A sell date is required.", "error");
          try {
            await api("/api/sell", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ lot_id: +b.dataset.lotsell, qty, price,
                                     date: vals.date }),
            });
            toast(`Sold ${qty} × ${item.symbol.split(".")[0]} recorded.`, "success");
            openDrawer(item); loadPortfolio();
          } catch (e) { toast(e.message, "error"); }
        }));
      document.querySelectorAll("[data-lotrm]").forEach(b =>
        b.addEventListener("click", async () => {
          await api(`/api/portfolio/${b.dataset.lotrm}`, { method: "DELETE" });
          openDrawer(item);          /* re-render with the lot gone */
          loadPortfolio();
        }));
      const pc = LightweightCharts.createChart($("#priceChart"), CHART_OPTS);
      const candleSeries = pc.addCandlestickSeries({
        upColor: "#34D399", downColor: "#F87171",
        wickUpColor: "#34D399", wickDownColor: "#F87171", borderVisible: false,
      });
      candleSeries.setData(d.candles);
      markActivePatterns(candleSeries, d.candles, item.symbol);
      pc.addLineSeries({ color: "#D9B45B", lineWidth: 1 }).setData(d.sma_fast);
      pc.addLineSeries({ color: "#7E8290", lineWidth: 1 }).setData(d.sma_slow);
      const ind = d.indicators || {};
      /* volume as a bottom histogram on its own scale */
      let volS = null, emaS = null, bbU = null, bbL = null, macdChart = null;
      if (ind.volume) {
        volS = pc.addHistogramSeries({ priceScaleId: "vol",
          priceFormat: { type: "volume" } });
        volS.setData(ind.volume);
        pc.priceScale("vol").applyOptions({
          scaleMargins: { top: 0.82, bottom: 0 } });
      }
      const mkLine = (data, color, style) => {
        const s = pc.addLineSeries({ color, lineWidth: 1,
          lineStyle: style ?? 0, visible: false });
        s.setData(data); return s;
      };
      if (ind.ema20) emaS = mkLine(ind.ema20, "#38BDF8");
      if (ind.bb_upper) bbU = mkLine(ind.bb_upper, "#A855F7", 2);
      if (ind.bb_lower) bbL = mkLine(ind.bb_lower, "#A855F7", 2);
      $("#tgVol").onchange = e => volS && volS.applyOptions({ visible: e.target.checked });
      $("#tgEma").onchange = e => emaS && emaS.applyOptions({ visible: e.target.checked });
      $("#tgBb").onchange = e => { [bbU, bbL].forEach(s => s && s.applyOptions({ visible: e.target.checked })); };
      $("#tgMacd").onchange = e => {
        $("#macdChart").classList.toggle("hidden", !e.target.checked);
        if (e.target.checked && !macdChart && ind.macd) {
          macdChart = LightweightCharts.createChart($("#macdChart"), CHART_OPTS);
          macdChart.addLineSeries({ color: "#2563EB", lineWidth: 1 }).setData(ind.macd);
          macdChart.addLineSeries({ color: "#F59E0B", lineWidth: 1 }).setData(ind.macd_signal);
          macdChart.timeScale().fitContent(); drawerCharts.push(macdChart);
        }
      };
      pc.timeScale().fitContent(); drawerCharts.push(pc);
      const rc = LightweightCharts.createChart($("#rsiChart"), CHART_OPTS);
      rc.addLineSeries({ color: "#D9B45B", lineWidth: 1 }).setData(d.rsi);
      rc.timeScale().fitContent(); drawerCharts.push(rc);
    }
  } catch (e) {
    if (/No stored data/i.test(e.message)) {
      /* newly-added ticker: give it a way to fetch its own history
         instead of a dead-end error box */
      body.innerHTML = `
        <div class="dl-empty">
          <svg class="dl-ico" viewBox="0 0 24 24">
            <path d="M3.5 3.5V20.5H20.5"/>
            <path d="M6 16.5l4-4.5 3 2.5 6-7" stroke-dasharray="3 3" opacity="0.45"/>
            <path d="M12 7v6M12 13l-2.5-2.5M12 13l2.5-2.5" class="dl-arrow"/>
          </svg>
          <h4>No price history yet</h4>
          <p>${item.label} is on your watchlist, but its candles haven't been
             downloaded. Pull ~10 years of history for just this stock —
             it takes a few seconds.</p>
          <button id="dlOne" class="btn btn-primary btn-ico">
            <svg class="ico ico-refresh"><use href="#i-refresh"/></svg>
            Download history</button>
          <div class="hint">Or run <b>Refresh data</b> to update the whole
            watchlist at once.</div>
        </div>`;
      $("#dlOne").onclick = async () => {
        const b = $("#dlOne");
        b.classList.add("busy"); b.disabled = true;
        try {
          const r = await api(`/api/download/${item.symbol}`, { method: "POST" });
          if (r.shallow) {
            /* honest dead-end: explain WHY instead of looping the
               same empty state */
            b.classList.remove("busy"); b.disabled = false;
            $("#drawerBody").querySelector(".dl-empty p").innerHTML = r.note;
            toast(`Only ${r.rows} rows available for ${r.symbol}.`, "info", 7000);
            return;
          }
          if (r.swapped) {
            toast(`Yahoo's ${item.symbol} listing was empty — switched to `
              + `${r.symbol} (${r.rows} rows).`, "success", 7000);
            item.symbol = r.symbol;
            item.label = r.symbol.split(".")[0];
          } else {
            toast(`Downloaded ${r.rows} rows for ${item.label}.`, "success");
          }
          await loadWatchlist();
          const fresh = WL.find(w => w.symbol === r.symbol) || item;
          openDrawer(fresh);           /* re-render with real data */
        } catch (err) {
          b.classList.remove("busy"); b.disabled = false;
          toast(err.message, "error", 9000);
        }
      };
    } else {
      body.innerHTML = `<div class="inline-msg err">${e.message}</div>`;
    }
  }
}
const closeDrawer = () => {
  $("#drawer").classList.remove("open");
  $("#drawerScrim").classList.add("hidden");
  clearCharts();
};
$("#drawerClose").addEventListener("click", closeDrawer);
$("#drawerScrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

/* ------------------------------------------------ tables */
function tableHTML(rows, numeric = []) {
  if (!rows || !rows.length) return `<div class="empty">No rows.</div>`;
  const cols = Object.keys(rows[0]);
  return `<table><thead><tr>${cols.map(c =>
      `<th class="${numeric.includes(c) ? "num" : ""}">${c}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => {
      const v = r[c];
      const isNum = numeric.includes(c);
      return `<td class="${isNum ? "num" : ""}">${v == null ? "—" : (isNum && typeof v === "number" ? fmt(v) : v)}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table>`;
}

/* ------------------------------------------------ screener */
/* ---- screener universes ---- */
window.switchUniverse = (name) => {
  $("#uniSelect").value = name;
  updateUniverseUI();
  $("#uniMsg").scrollIntoView({ behavior: "smooth", block: "center" });
};
let UNI_STATUS = {};
async function refreshUniverses() {
  try {
    const d = await api("/api/universes");
    UNI_STATUS = Object.fromEntries(d.universes.map(u => [u.name, u]));
  } catch (e) { UNI_STATUS = {}; }
  updateUniverseUI();
}
function updateUniverseUI() {
  const name = $("#uniSelect").value;
  const u = UNI_STATUS[name], msg = $("#uniMsg"), btn = $("#uniPrep");
  msg.classList.remove("hidden");
  if (!u) { msg.textContent = ""; btn.classList.add("hidden"); return; }
  if (u.error) {
    msg.textContent = u.error; btn.classList.add("hidden"); return;
  }
  if (name === "watchlist" || u.missing === 0) {
    msg.textContent = `${u.total} stocks · ${u.with_fundamentals} with fundamentals — ready.`;
    btn.classList.add("hidden");
  } else {
    msg.textContent = `${u.total} constituents · ${u.missing} still need price history downloaded before queries can see them.`;
    btn.textContent = `Download data for ${u.missing} stocks`;
    btn.classList.remove("hidden");
  }
}
$("#uniSelect").addEventListener("change", updateUniverseUI);
$("#uniPrep").addEventListener("click", async () => {
  const name = $("#uniSelect").value;
  await api(`/api/universe/${name}/prepare`, { method: "POST" });
  const log = $("#uniLog"); log.classList.remove("hidden");
  const t = setInterval(async () => {
    const s = await api("/api/universe/status");
    log.textContent = s.log.join("\n") || "starting…";
    if (!s.running) { clearInterval(t); refreshUniverses(); }
  }, 2000);
});

async function runQuery(q) {
  const msg = $("#qMsg"); msg.classList.add("hidden");
  try {
    const uni = $("#uniSelect").value;
    const d = await api(`/api/query?q=${encodeURIComponent(q)}&universe=${uni}`);
    if (!d.rows.length && d.diagnostics) {
      const g = d.diagnostics;
      $("#qResults").innerHTML = `<div class="empty">
        <p>No matches — here's why:</p>
        <p class="hint">Universe: ${g.universe_size} stocks
          (${g.with_fundamentals} with fundamentals,
          ${g.with_technicals} with enough price history)</p>
        ${g.conditions.map(c =>
          `<p class="hint">· "${c.condition}" matched <b>${c.matched}</b> of ${g.universe_size}${
            c.available ? `<br><span class="muted">Sectors in this universe: ${c.available.join(", ")}</span>` : ""}</p>`).join("")}
        ${g.near_misses && g.near_misses.length ? `
          <p class="hint" style="margin-top:10px"><b>So close:</b> these pass everything except one condition —</p>
          ${g.near_misses.map(n =>
            `<p class="hint">· <b>${n.name}</b> fails only "${n.failed}"${n.value != null ? ` (its value: ${n.value})` : ""}</p>`).join("")}` : ""}
        <p class="hint">${g.conditions.some(c => !c.matched)
          ? "A condition matching 0 is the blocker — loosen it, or search the whole index instead:"
          : "Each condition matches some stocks, but no stock passes all of them together. Loosen one, or search the whole index:"}</p>
        <p><button class="btn" onclick="switchUniverse('nifty500')">Switch to NIFTY 500</button></p>
      </div>`;
      return;
    }
    $("#qResults").innerHTML = tableHTML(d.rows,
      ["Mkt cap (₹Cr)", "Close", "P/E", "P/B", "ROE %", "Margin %", "Div yield %", "D/E", "EPS", "Beta", "RSI", "1M %", "6M %", "1Y %"]);
  } catch (e) {
    msg.className = "inline-msg err"; msg.textContent = e.message;
    msg.classList.remove("hidden");
  }
}
$("#qInput").addEventListener("keydown", e => { if (e.key === "Enter") runQuery(e.target.value); });
$("#nlqInput").addEventListener("keydown", async e => {
  if (e.key !== "Enter" || !e.target.value.trim()) return;
  const gen = $("#nlqGen");
  gen.classList.remove("hidden"); gen.textContent = "Translating via Groq…";
  try {
    const d = await api(`/api/nlq?text=${encodeURIComponent(e.target.value)}`);
    gen.textContent = `Generated query: ${d.generated_query}`;
    $("#qInput").value = d.generated_query;
    await runQuery(d.generated_query);
  } catch (err) { gen.textContent = err.message; }
});

/* ------------------------------------------------ AI lab & backtest */
async function loadEligible() {
  const d = await api("/api/eligible");
  const opts = d.eligible.map(s => `<option value="${s.symbol}">${s.label} (${s.symbol})</option>`).join("");
  $("#mlSymbol").innerHTML = opts || `<option>none eligible</option>`;
  $("#btSymbol").innerHTML = opts || `<option>none eligible</option>`;
}
$("#rankBtn").addEventListener("click", async () => {
  $("#rankOut").innerHTML = skeleton(5);
  const d = await api("/api/rankings");
  $("#rankOut").innerHTML = tableHTML(d.rows,
    ["Close", "P/E", "ROE %", "6M %", "RSI", "Momentum z", "Value z", "Quality z", "Trend z", "Score"]);
});
$("#mlBtn").addEventListener("click", async () => {
  const out = $("#mlOut");
  out.innerHTML = skeleton(3);
  try {
    const d = await api(`/api/predict/${$("#mlSymbol").value}`);
    const edge = (d.edge * 100).toFixed(1);
    out.innerHTML = `
      <div class="summary-row">
        <div class="metric"><div class="k">P(up tomorrow)</div><div class="v">${(d.prob_up * 100).toFixed(0)}%</div></div>
        <div class="metric"><div class="k">Test accuracy</div><div class="v">${(d.test_accuracy * 100).toFixed(1)}%</div></div>
        <div class="metric"><div class="k">Naive baseline</div><div class="v">${(d.baseline_accuracy * 100).toFixed(1)}%</div></div>
        <div class="metric"><div class="k">Edge</div><div class="v ${d.edge > 0.005 ? "pos" : "neg"}">${edge > 0 ? "+" : ""}${edge} pts</div></div>
      </div>
      <div class="inline-msg ${d.verdict === "no_edge" ? "err" : "warn"}">${d.verdict_text}</div>
      <div class="hint">Trained on ${d.n_train} days, tested on ${d.n_test} unseen days (${d.test_period}).</div>
      <div class="section-label">What the model paid attention to</div>
      <div class="hint">Permutation importance on unseen test data. Bars near
        zero (or negative, red) mean the feature carried no real signal —
        which, for daily prices, is the usual truth.</div>
      <div class="hbar-list hbar-wide">` +
      hbarRows(
        d.importances.map(([f, v]) => ({ label: f, value: v })),
        { diverging: true, fmtVal: v => (v >= 0 ? "+" : "") + v.toFixed(3) }
      ) + `</div>`;
  } catch (e) { out.innerHTML = `<div class="inline-msg err">${e.message}</div>`; }
});
let btChartObj = null;
async function loadStrategies() {
  if ($("#btStrategy").options.length) return;
  try {
    const d = await api("/api/strategies");
    $("#btStrategy").innerHTML = d.strategies.map(s =>
      `<option value="${s.key}" data-desc="${s.desc}">${s.label}</option>`).join("");
    updateBtDesc();
  } catch (e) {}
}
function updateBtDesc() {
  const opt = $("#btStrategy").selectedOptions[0];
  const el = $("#btDesc");
  if (opt) { el.textContent = opt.dataset.desc; el.classList.remove("hidden"); }
}
$("#btStrategy").addEventListener("change", updateBtDesc);

$("#btAllBtn").addEventListener("click", async () => {
  $("#btBoard").innerHTML = skeleton(4);
  try {
    const d = await api(`/api/backtest-all/${$("#btSymbol").value}?cost=${$("#btCost").value}`);
    const hold = d.rows[0];
    $("#btBoard").innerHTML = `
      <div class="section-label">Every rule on ${d.symbol.split(".")[0]} — vs holding at ${hold.hold_cagr}% CAGR (max fall ${hold.hold_dd}%)</div>
      <table><thead><tr><th>Rule</th><th class="num">CAGR %</th>
        <th class="num">Max fall %</th><th class="num">Trades</th>
        <th class="num">Win rate</th><th>Historical result</th>
        <th>Rule today</th></tr></thead><tbody>
      ${d.rows.map(r => `<tr>
        <td>${r.label}</td>
        <td class="num ${pctCls(r.cagr)}">${r.cagr}</td>
        <td class="num">${r.max_dd}</td>
        <td class="num">${r.trades}</td>
        <td class="num">${r.win_rate ?? "—"}%</td>
        <td class="${r.beat_hold ? "pos" : ""}">${r.beat_hold
          ? "beat holding" : "holding won"}</td>
        <td class="${r.now.invested ? "pos" : "neg"}">${r.now.invested
          ? "invested" : "out"}${r.now.since ? ` <span class="muted">since ${r.now.since}</span>` : ""}</td>
      </tr>`).join("")}
      </tbody></table>
      ${d.held ? `<div class="ck-frame">You hold this stock. "Rule today" is
        what each rule's own logic currently says — and notice they usually
        disagree with each other. That disagreement is the honest picture:
        pick a rule because its historical numbers above convince you, not
        because it currently says what you want to hear.</div>` : ""}
      <div class="hint">A scoreboard of the past, not a menu of futures: a rule
      that won here has NOT been shown to work on other stocks or from
      tomorrow. If one rule wins everywhere, that's interesting; if it wins
      once, that's luck. The decision layer is yours — see the stock's own
      base rates in its dialog.</div>`;
  } catch (e) {
    $("#btBoard").innerHTML = `<div class="inline-msg err">${e.message}</div>`;
  }
});

$("#btBtn").addEventListener("click", async () => {
  $("#btStats").innerHTML = skeleton(2);
  try {
    const d = await api(`/api/backtest/${$("#btSymbol").value}?cost=${$("#btCost").value}&strategy=${$("#btStrategy").value}`);
    const s = d.strategy, h = d.buy_hold;
    $("#btStats").innerHTML = `
      <div class="metric"><div class="k">Strategy CAGR</div><div class="v">${s.cagr}%</div>
        <div class="d ${s.cagr - h.cagr >= 0 ? "pos" : "neg"}">${(s.cagr - h.cagr).toFixed(2)} vs hold</div></div>
      <div class="metric"><div class="k">Buy &amp; hold CAGR</div><div class="v">${h.cagr}%</div></div>
      <div class="metric"><div class="k">Strategy max DD</div><div class="v">${s.max_dd}%</div></div>
      <div class="metric"><div class="k">Hold max DD</div><div class="v">${h.max_dd}%</div></div>
      <div class="metric"><div class="k">Trades / win rate</div>
        <div class="v">${d.n_trades} / ${d.win_rate ?? "—"}%</div></div>
    <div class="metric"><div class="k">Rule today</div>
      <div class="v ${d.now.invested ? "pos" : "neg"}">${d.now.invested ? "invested" : "out"}</div>
      ${d.now.since ? `<div class="d">since ${d.now.since}</div>` : ""}</div>`;
    if (btChartObj) { btChartObj.remove(); btChartObj = null; }
    $("#btChart").innerHTML = "";
    btChartObj = LightweightCharts.createChart($("#btChart"), CHART_OPTS);
    btChartObj.addLineSeries({ color: "#7E8290", lineWidth: 1 })
      .setData(d.curves.map(c => ({ time: c.time, value: c.hold })));
    btChartObj.addLineSeries({ color: "#D9B45B", lineWidth: 2 })
      .setData(d.curves.map(c => ({ time: c.time, value: c.strategy })));
    btChartObj.timeScale().fitContent();
    const sm = $("#btSummary");
    sm.className = "inline-msg"; sm.textContent = d.summary;
  } catch (e) {
    $("#btStats").innerHTML = `<div class="inline-msg err">${e.message}</div>`;
  }
});

/* ------------------------------------------------ portfolio */
let pfCharts = [];
const PALETTE = ["#2563EB", "#22C55E", "#F59E0B", "#A855F7", "#14B8A6",
                 "#F97316", "#EC4899", "#84CC16", "#38BDF8", "#E11D48"];

function donutSVG(items, size = 150, stroke = 20) {
  const total = items.reduce((a, x) => a + x.value, 0);
  if (!total) return "";
  const r = (size - stroke) / 2, C = 2 * Math.PI * r;
  let off = 0, segs = "";
  items.forEach((x, i) => {
    const frac = x.value / total;
    segs += `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
      stroke="${PALETTE[i % PALETTE.length]}" stroke-width="${stroke}"
      stroke-dasharray="${(frac * C).toFixed(2)} ${C.toFixed(2)}"
      stroke-dashoffset="${(-off * C).toFixed(2)}"
      transform="rotate(-90 ${size / 2} ${size / 2})"/>`;
    off += frac;
  });
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${segs}</svg>`;
}

function hbarRows(items, { diverging = false, fmtVal } = {}) {
  const max = Math.max(...items.map(x => Math.abs(x.value)), 1e-9);
  return items.map((x, i) => {
    const w = Math.abs(x.value) / max * (diverging ? 50 : 100);
    const color = diverging
      ? (x.value >= 0 ? "var(--up)" : "var(--down)")
      : PALETTE[i % PALETTE.length];
    const pos = diverging
      ? (x.value >= 0 ? `left:50%;width:${w}%` : `right:50%;width:${w}%`)
      : `left:0;width:${w}%`;
    return `<div class="hbar${diverging ? " div" : ""}">
      <span class="lbl" title="${x.label}">${x.label}</span>
      <span class="track"><span class="fill" style="${pos};background:${color}"></span></span>
      <span class="val ${diverging ? pctCls(x.value) : ""}">${fmtVal(x.value)}</span>
    </div>`;
  }).join("");
}

let PF = null;                     /* last /api/portfolio payload */
async function loadPortfolio() {
  const d = await api("/api/portfolio");
  PF = d;
  loadTape();
  const hPrev = $("#hSymbol").value;
  $("#hSymbol").innerHTML = WL.filter(i => i.type !== "mf")
    .map(i => `<option value="${i.symbol}">${i.label}</option>`).join("");
  if (hPrev) $("#hSymbol").value = hPrev;
  pfCharts.forEach(c => c.remove()); pfCharts = [];
  const has = d.holdings.length > 0;
  const t = d.totals;

  $("#pfTotals").innerHTML = !has ? "" : `
    <div class="metric"><div class="k">Invested</div><div class="v">₹${fmt(t.invested, 0)}</div></div>
    <div class="metric"><div class="k">Current value</div><div class="v">₹${fmt(t.current, 0)}</div></div>
    <div class="metric"><div class="k">Total P&amp;L</div>
      <div class="v ${pctCls(t.pnl)}">₹${fmt(t.pnl, 0)}</div>
      <div class="d ${pctCls(t.pnl_pct)}">${t.pnl_pct >= 0 ? "+" : ""}${t.pnl_pct.toFixed(2)}%</div></div>
    <div class="metric"><div class="k">Dividends</div>
      <div class="v">₹${fmt(t.dividends, 0)}</div>
      <div class="d ${pctCls(t.pnl_incl_div)}">incl: ₹${fmt(t.pnl_incl_div, 0)} (${t.pnl_incl_div_pct >= 0 ? "+" : ""}${t.pnl_incl_div_pct.toFixed(2)}%)</div></div>
    <div class="metric"><div class="k">Today</div>
      <div class="v ${pctCls(t.day_pnl)}">₹${fmt(t.day_pnl, 0)}</div>
      <div class="d ${pctCls(t.day_pct)}">${pctTxt(t.day_pct)}</div></div>
    <div class="metric"><div class="k">Holdings</div>
      <div class="v">${d.holdings.length}</div>
      ${t.unpriced ? `<div class="d">${t.unpriced} without price data</div>` : ""}</div>`;
  if (has) renderXirr(d);
  initWhatIf(d);
  loadSips();
  renderRebalance();

  /* holdings table — formatted, colored, scrolls inside its card */
  if (!has) {
    $("#pfTable").innerHTML =
      `<div class="empty">No holdings yet — add your first on the right.</div>`;
  } else {
    const cols = ["Symbol", "Check", "Qty", "Avg cost", "Since", "Lots",
                  "Last", "Invested", "Current", "P&L", "P&L %", "Day %",
                  "Weight %", ""];
    const money = new Set(["Avg cost", "Last", "Invested", "Current", "P&L"]);
    const body = d.holdings.map(h => {
      const cells = cols.map(c => {
        if (c === "") return h.Lots === 1
          ? `<td><button class="rm-btn" style="opacity:1" data-hrm="${h.ids[0]}" title="Remove holding">✕</button></td>`
          : `<td><span class="lots-note" title="Multiple lots — open the row to manage them">◱</span></td>`;
        if (c === "Check") return h.tier
          ? `<td><span class="tier-chip tier-${h.tier}" title="Research checklist tier — open the row for the full read">${h.tier}</span></td>`
          : `<td class="num muted">—</td>`;
        let v = h[c], cls = "num";
        if (c === "Symbol") return `<td>${(h.Symbol || "").split(".")[0]}</td>`;
        if (c === "Since") return `<td class="num">${v || "—"}</td>`;
        if (c === "Lots") return `<td class="num">${v > 1 ? v : ""}</td>`;
        if (v == null) return `<td class="num">—</td>`;
        if (c === "Qty") v = fmt(v, v % 1 ? 2 : 0);
        else if (money.has(c)) v = fmt(v, 2);
        else if (/%/.test(c)) { v = (h[c] >= 0 ? "+" : "") + fmt(h[c], c === "Weight %" ? 1 : 2); }
        if (c === "P&L" || c === "P&L %" || c === "Day %") cls += " " + pctCls(h[c]);
        return `<td class="${cls}">${v}</td>`;
      }).join("");
      return `<tr class="pf-row" data-sym="${h.Symbol}">${cells}</tr>`;
    }).join("");
    $("#pfTable").innerHTML = `<table><thead><tr>${cols.map(c =>
      `<th class="${c === "Symbol" || c === "" ? "" : "num"}">${c}</th>`).join("")}
      </tr></thead><tbody>${body}</tbody></table>`;
  }
  document.querySelectorAll("[data-hrm]").forEach(b =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const hrow = ((window.PF && PF.holdings) || []).find(
        (h) => h.ids && h.ids[0] == b.dataset.hrm);
      if (hrow && hrow.thesis) {
        const ok = await dlgForm(
          `You bought ${hrow.Symbol.split(".")[0]} because: “${hrow.thesis}” — ` +
          `has that thesis actually broken?`, [], "Remove anyway");
        if (ok === null) return;
      }
      await api(`/api/portfolio/${b.dataset.hrm}`, { method: "DELETE" });
      loadPortfolio();
    }));
  document.querySelectorAll(".pf-row").forEach(r =>
    r.addEventListener("click", () => openSymbol(r.dataset.sym)));

  /* value-over-time chart */
  $("#pfCurveCard").classList.toggle("hidden", !(d.curve && d.curve.length > 1));
  if (d.curve && d.curve.length > 1) {
    $("#pfCurve").innerHTML = "";
    const c = LightweightCharts.createChart($("#pfCurve"), CHART_OPTS);
    c.addAreaSeries({
      lineColor: "#2563EB", lineWidth: 2,
      topColor: "rgba(37,99,235,0.28)", bottomColor: "rgba(37,99,235,0.02)",
    }).setData(d.curve.map(p => ({ time: p.time, value: p.value })));
    c.addLineSeries({ color: "#71717A", lineWidth: 1, lineStyle: 1 })
      .setData(d.curve.map(p => ({ time: p.time, value: p.invested })));
    const bm = d.curve.filter(p => p.benchmark != null);
    $("#bmLegend").classList.toggle("hidden", bm.length < 2);
    if (bm.length > 1) {
      c.addLineSeries({ color: "#D9B45B", lineWidth: 1 })
        .setData(bm.map(p => ({ time: p.time, value: p.benchmark })));
    }
    c.timeScale().fitContent(); pfCharts.push(c);
  }

  /* realized P&L */
  const rz = d.realized;
  $("#pfRealizedCard").classList.toggle("hidden", !rz);
  if (rz) {
    $("#pfRealized").innerHTML = `
      <div class="hint">Total <b class="${pctCls(rz.total)}">₹${fmt(rz.total, 0)}</b>
        · short-term <b class="${pctCls(rz.short_term)}">₹${fmt(rz.short_term, 0)}</b>
        · long-term <b class="${pctCls(rz.long_term)}">₹${fmt(rz.long_term, 0)}</b></div>
      ${rz.fy.map(f => `<div class="hint">· ${f.fy}: ₹${fmt(f.total, 0)}
        (ST ₹${fmt(f.st, 0)} / LT ₹${fmt(f.lt, 0)})</div>`).join("")}
      <div class="div-list">${rz.rows.slice(0, 6).map(r => `
        <div class="div-row">
          <span>${r.symbol} <span class="tag-chip">${r.term}</span></span>
          <span class="num">${r.qty} @ ₹${fmt(r.sell_price)}</span>
          <span class="num ${pctCls(r.pnl)}">₹${fmt(r.pnl, 0)}</span>
          <span class="muted">${r.sell_date}</span>
        </div>`).join("")}</div>
      <div class="hint">ST/LT uses the 365-day equity rule from each lot's
      buy date — the split that matters at tax time.</div>`;
  }

  /* dividends card */
  const dPrev = $("#dSymbol").value;
  $("#dSymbol").innerHTML = [...new Set(d.holdings.map(h => h.Symbol))]
    .map(s => `<option value="${s}">${(s || "").split(".")[0]}</option>`).join("");
  if (dPrev) $("#dSymbol").value = dPrev;
  $("#dList").innerHTML = (d.dividends || []).slice(0, 8).map(v => `
    <div class="div-row">
      <span>${v.symbol.split(".")[0]}</span>
      <span class="num">₹${fmt(v.amount, 2)}</span>
      <span class="muted">${v.date || ""}</span>
      <button class="rm-btn" style="opacity:1" data-drm="${v.id}">✕</button>
    </div>`).join("");
  document.querySelectorAll("[data-drm]").forEach(b =>
    b.addEventListener("click", async () => {
      await api(`/api/dividends/${b.dataset.drm}`, { method: "DELETE" });
      loadPortfolio();
    }));

  /* allocation donut */
  const alloc = (d.allocation || []).slice().sort((a, b) => b.value - a.value);
  $("#pfAllocCard").classList.toggle("hidden", alloc.length < 1);
  if (alloc.length) {
    const total = alloc.reduce((a, x) => a + x.value, 0);
    $("#pfDonut").innerHTML = donutSVG(alloc);
    $("#pfDonutLegend").innerHTML = alloc.map((x, i) => `
      <div class="row">
        <span class="sw" style="background:${PALETTE[i % PALETTE.length]}"></span>
        <span class="lbl">${x.label}</span>
        <span class="val">${(x.value / total * 100).toFixed(1)}%</span>
      </div>`).join("");
  }

  /* sector exposure bars */
  const secs = d.sectors || [];
  $("#pfSectorCard").classList.toggle("hidden", secs.length < 1);
  if (secs.length) {
    const total = secs.reduce((a, x) => a + x.value, 0);
    $("#pfSectors").innerHTML =
      hbarRows(secs, { fmtVal: v => (v / total * 100).toFixed(1) + "%" });
  }

  /* P&L per holding — diverging bars */
  const pnl = (d.holdings || [])
    .filter(h => h["P&L"] != null)
    .map(h => ({ label: (h.Symbol || "").split(".")[0], value: h["P&L"] }))
    .sort((a, b) => b.value - a.value);
  $("#pfPnlCard").classList.toggle("hidden", pnl.length < 2);
  if (pnl.length >= 2) {
    $("#pfPnlBars").innerHTML =
      hbarRows(pnl, { diverging: true, fmtVal: v => "₹" + fmt(v, 0) });
  }
  if (d.correlation) {
    const { labels, matrix } = d.correlation;
    const n = labels.length;
    let cells = `<div class="corr-cell corr-label"></div>` +
      labels.map(l => `<div class="corr-cell corr-label">${l}</div>`).join("");
    matrix.forEach((row, i) => {
      cells += `<div class="corr-cell corr-label">${labels[i]}</div>`;
      row.forEach(v => {
        if (v == null) {             // no overlapping history for this pair
          cells += `<div class="corr-cell">—</div>`;
          return;
        }
        const c = v >= 0
          ? `rgba(52,211,153,${Math.abs(v) * 0.55})`
          : `rgba(248,113,113,${Math.abs(v) * 0.55})`;
        cells += `<div class="corr-cell" style="background:${c}">${v.toFixed(2)}</div>`;
      });
    });
    $("#pfCorr").innerHTML = `<h3>Correlation (1y)</h3>
      <p class="hint">Deep green pairs move together — closer to one bet than two.</p>
      <div class="corr-grid" style="grid-template-columns:repeat(${n + 1},1fr)">${cells}</div>`;
  } else { $("#pfCorr").innerHTML = ""; }
}
$("#hAdd").addEventListener("click", async () => {
  const msg = $("#hMsg");
  const qty = +$("#hQty").value, price = +$("#hPrice").value;
  if (!(qty > 0) || !(price > 0)) {
    msg.className = "inline-msg err";
    msg.textContent = "Quantity and buy price must both be above zero.";
    return;
  }
  try {
    await api("/api/portfolio", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: $("#hSymbol").value, qty,
        buy_price: price, buy_date: $("#hDate").value || null,
        thesis: ($("#hThesis") ? $("#hThesis").value.trim() : "") || null,
      }),
    });
    msg.classList.add("hidden");
    $("#hQty").value = ""; $("#hPrice").value = ""; $("#hDate").value = "";
    if ($("#hThesis")) $("#hThesis").value = "";
    loadPortfolio();
  } catch (e) {
    msg.className = "inline-msg err";
    msg.textContent = e.message;
  }
});
["psCap", "psRisk", "psEntry", "psStop"].forEach(id =>
  $(`#${id}`).addEventListener("input", async () => {
    const [c, r, e, s] = [+$("#psCap").value, +$("#psRisk").value, +$("#psEntry").value, +$("#psStop").value];
    const out = $("#psOut");
    if (!(c && r && e && s)) { out.classList.add("hidden"); return; }
    out.classList.remove("hidden");
    try {
      const d = await api(`/api/position-size?capital=${c}&risk_pct=${r}&entry=${e}&stop=${s}`);
      out.className = "inline-msg ok";
      out.innerHTML = d.shares === 0 ? d.note :
        `Buy up to <b class="mono">${d.shares}</b> shares (₹${fmt(d.outlay, 0)}, ${d.outlay_pct}% of capital).
         Stop at ${d.stop_pct}% costs ₹${fmt(d.risk_amount, 0)} — your chosen ${r}%.`;
    } catch (err) { out.className = "inline-msg err"; out.textContent = err.message; }
  }));

/* ------------------------------------------------ journal */
async function loadJournal() {
  const d = await api("/api/journal");
  $("#jList").innerHTML = tableHTML(d.rows, ["price"]);
}

$("#dAdd").addEventListener("click", async () => {
  const msg = $("#dMsg"), amt = +$("#dAmount").value;
  if (!(amt > 0)) {
    msg.className = "inline-msg err";
    msg.textContent = "Dividend amount must be above zero.";
    return;
  }
  try {
    await api("/api/dividends", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: $("#dSymbol").value, amount: amt,
                             date: $("#dDate").value || null }),
    });
    msg.classList.add("hidden");
    $("#dAmount").value = ""; $("#dDate").value = "";
    loadPortfolio();
  } catch (e) { msg.className = "inline-msg err"; msg.textContent = e.message; }
});

/* open a symbol's dialog even if it isn't in the watchlist */
function openSymbol(symbol) {
  const item = WL.find(i => i.symbol === symbol)
    || { symbol, label: symbol.split(".")[0], type: "stock", id: null };
  openDrawer(item);
}

/* ------------------------------------------------ keyboard: / to search */
document.addEventListener("keydown", e => {
  const tag = (document.activeElement || {}).tagName;
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  if (e.key === "/" && !typing && !$("#drawer").classList.contains("open")) {
    e.preventDefault();
    document.querySelector('.rail-link[data-page="watchlist"]').click();
    $("#search").focus(); $("#search").select();
  }
});
$("#search").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const row = document.querySelector(".wl-row");
    if (row) { const it = WL.find(i => i.id == row.dataset.id); if (it) openDrawer(it); }
  } else if (e.key === "Escape") {
    e.stopPropagation();
    $("#search").value = ""; renderWatchlist(); $("#search").blur();
  }
});

/* ------------------------------------------------ ticker tape */


/* ---------- watchlist heatmap ---------- */
function renderHeatmap() {
  const stocks = WL.filter(i => i.type === "stock" && i.pct != null);
  if (!stocks.length) {
    $("#wlHeatmap").innerHTML = `<div class="empty">Refresh data first.</div>`;
    return;
  }
  const mcaps = stocks.map(s => s.mcap || 0);
  const maxM = Math.max(...mcaps, 1);
  $("#wlHeatmap").innerHTML = stocks
    .slice().sort((a, b) => (b.mcap || 0) - (a.mcap || 0))
    .map(s => {
      const w = 70 + Math.sqrt((s.mcap || maxM * 0.01) / maxM) * 140;
      /* colour ramp: sqrt curve so small moves stay readable and big
         moves saturate, instead of everything looking equally muddy */
      const mag = Math.sqrt(Math.min(Math.abs(s.pct) / 4, 1));
      const up = s.pct >= 0;
      const bg = up
        ? `linear-gradient(160deg, rgba(34,197,94,${0.10 + mag * 0.42}), rgba(34,197,94,${0.05 + mag * 0.30}))`
        : `linear-gradient(160deg, rgba(239,68,68,${0.10 + mag * 0.42}), rgba(239,68,68,${0.05 + mag * 0.30}))`;
      return `<div class="heat-tile ${up ? "ht-up" : "ht-down"}" data-id="${s.id}"
        style="width:${w.toFixed(0)}px;background:${bg}"
        title="${s.label} · ${pctTxt(s.pct)}">
        <span class="heat-sym">${(s.symbol || "").split(".")[0]}${tierChip(s.symbol, true)}</span>
        <span class="heat-pct">${up ? "▲" : "▼"} ${Math.abs(s.pct).toFixed(2)}%</span></div>`;
    }).join("");
  document.querySelectorAll(".heat-tile").forEach(t =>
    t.addEventListener("click", () => {
      const it = WL.find(i => i.id == t.dataset.id);
      if (it) openDrawer(it);
    }));
}
on("#viewHeat", "click", () => {
  $("#wlHeatmap")?.classList.remove("hidden");
  $("#wlList")?.classList.add("hidden");
  $("#viewHeat").classList.add("active-view");
  $("#viewList")?.classList.remove("active-view");
  renderHeatmap();
});
on("#viewList", "click", () => {
  $("#wlHeatmap")?.classList.add("hidden");
  $("#wlList")?.classList.remove("hidden");
  $("#viewList").classList.add("active-view");
  $("#viewHeat")?.classList.remove("active-view");
});

/* ---------- alerts card ---------- */
async function loadAlerts() {
  try {
    const d = await api("/api/alerts");
    setAlertBadge((d.alerts || d || []).length);
    $("#alSymbol").innerHTML = WL.filter(i => i.type !== "mf")
      .map(i => `<option value="${i.symbol}">${(i.symbol || "").split(".")[0]}</option>`).join("");
    $("#alKind").innerHTML = Object.entries(d.kinds)
      .map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    $("#alList").innerHTML = d.alerts.map(a => `
      <div class="div-row">
        <span>${a.symbol.split(".")[0]} <span class="tag-chip">${a.kind}</span></span>
        <span class="num">${a.value || ""}</span>
        <span class="${a.active ? "pos" : "muted"}">${a.active ? "armed" : "fired"}</span>
        <button class="rm-btn" style="opacity:1" data-alrm="${a.id}">✕</button>
      </div>`).join("") || `<div class="hint">No alerts yet.</div>`;
    document.querySelectorAll("[data-alrm]").forEach(b =>
      b.addEventListener("click", async () => {
        await api(`/api/alerts/${b.dataset.alrm}`, { method: "DELETE" });
        loadAlerts();
      }));
  } catch (e) {}
}
$("#alAdd").addEventListener("click", async () => {
  const msg = $("#alMsg");
  try {
    await api("/api/alerts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: $("#alSymbol").value,
        kind: $("#alKind").value, value: +$("#alValue").value || 0 }),
    });
    msg.classList.add("hidden"); $("#alValue").value = "";
    loadAlerts();
  } catch (e) { msg.className = "inline-msg err"; msg.textContent = e.message; }
});

/* ---------- dialog research sections (lazy) ---------- */
function crores(v) {
  if (v == null) return "—";
  const cr = v / 1e7;
  return cr >= 1000 ? (cr / 1000).toFixed(1) + "k Cr" : cr.toFixed(0) + " Cr";
}
function pairBars(items, k1, k2, l1, l2) {
  const max = Math.max(...items.map(x => Math.max(Math.abs(x[k1] || 0), Math.abs(x[k2] || 0))), 1);
  return `<div class="fin-bars">` + items.map(x => `
    <div class="fin-col" title="${x.period}">
      <div class="fin-bar-wrap">
        <div class="fin-bar b1" style="height:${Math.abs(x[k1] || 0) / max * 100}%"></div>
        <div class="fin-bar b2 ${(x[k2] || 0) < 0 ? "neg-bar" : ""}" style="height:${Math.abs(x[k2] || 0) / max * 100}%"></div>
      </div>
      <div class="fin-period">${x.period.slice(2, 7)}</div>
    </div>`).join("") + `</div>
    <div class="chart-legend"><span><i class="dot" style="background:var(--primary)"></i>${l1}</span>
    <span><i class="dot" style="background:var(--up)"></i>${l2}</span></div>`;
}
async function loadResearch(kind, symbol) {
  const out = $("#rsOut");
  out.innerHTML = skeleton(2);
  try {
    if (kind === "patterns") {
      const d = await api(`/api/patterns/${symbol}`);
      const st = d.structure, rg = d.regime, bl = d.baseline_1m;
      const stat = (c) => c.n < 5
        ? `${c.n}× — too few to summarize`
        : `${c.n}× · 1m later: median <b class="${pctCls(c.median)}">${c.median >= 0 ? "+" : ""}${c.median}%</b> · positive ${c.hit_rate}%`;
      out.innerHTML = `
        <div class="section-label">Regime</div>
        <div class="hint">${rg.read} (annualized vol ${rg.ann_vol_pct ?? "—"}%)</div>
        <div class="section-label">Structure</div>
        <div class="hint">
          ${st.near_support ? `At/near support ~₹${fmt(st.near_support)}. ` : ""}
          ${st.near_resistance ? `At/near resistance ~₹${fmt(st.near_resistance)}. ` : ""}
          Next support ${st.next_support ? "₹" + fmt(st.next_support) : "—"} ·
          next resistance ${st.next_resistance ? "₹" + fmt(st.next_resistance) : "—"} ·
          ${st.off_52w_high_pct}% off 52w high · +${st.off_52w_low_pct}% off 52w low.
          Levels are swing-point clusters (touched 2+ times in the last year), not prophecy.
        </div>
        <div class="section-label">Candle patterns — this stock's own record</div>
        <div class="hint">Baseline: any day, 1m later median ${bl.median >= 0 ? "+" : ""}${bl.median ?? "—"}% · positive ${bl.hit_rate ?? "—"}%</div>
        ${d.candles.map(c => `<div class="br-block ${c.active_today ? "br-active" : ""}">
          <div class="br-title">${c.name}
            ${c.active_today ? `<span class="tag-chip gold">on today's candle</span>` : ""}
            <span class="br-n">${c.desc}</span></div>
          <div class="hint">${stat(c)}</div>
        </div>`).join("")}
        <div class="hint">${d.note}</div>`;
    } else if (kind === "financials") {
      const d = await api(`/api/financials/${symbol}`);
      let html = "";
      if (d.quarterly && d.quarterly.length)
        html += `<div class="section-label">Quarterly revenue & net profit</div>`
          + pairBars(d.quarterly, "revenue", "net_income", "Revenue", "Net profit")
          + `<div class="hint">Latest quarter margin: ${d.quarterly.at(-1).net_margin ?? "—"}%</div>`;
      if (d.annual && d.annual.length)
        html += `<div class="section-label">Annual revenue & net profit</div>`
          + pairBars(d.annual, "revenue", "net_income", "Revenue", "Net profit");
      if (d.balance && d.balance.length) {
        const b = d.balance.at(-1);
        html += `<div class="section-label">Balance sheet (latest)</div>
          <div class="hint">Equity ₹${crores(b.equity)} · Debt ₹${crores(b.debt)} · Cash ₹${crores(b.cash)}</div>`;
      }
      if (d.cashflow && d.cashflow.length) {
        const c = d.cashflow.at(-1);
        html += `<div class="section-label">Cash flow (latest FY)</div>
          <div class="hint">Operating ₹${crores(c.operating)} · Free ₹${crores(c.free)}
          ${c.operating != null && c.free != null && c.free < 0 ? " — negative FCF: check why in the annual report" : ""}</div>`;
      }
      out.innerHTML = html || `<div class="hint">Statements came back empty.</div>`;
    } else if (kind === "peers") {
      const d = await api(`/api/peers/${symbol}`);
      out.innerHTML = `<div class="section-label">${d.sector} peers (median P/E ${d.median_pe ?? "—"})</div>
        <div class="table-card"><table><thead><tr><th>Stock</th>
        <th class="num">MCap ₹Cr</th><th class="num">P/E</th><th class="num">ROE %</th>
        <th class="num">Margin %</th><th class="num">1Y %</th></tr></thead><tbody>
        ${d.rows.map(r => `<tr class="${r.is_subject ? "peer-me" : ""}">
          <td>${r.symbol}${r.is_subject ? " ◀" : ""}</td>
          <td class="num">${r.mcap_cr ? fmt(r.mcap_cr, 0) : "—"}</td>
          <td class="num">${r.pe ?? "—"}</td><td class="num">${r.roe ?? "—"}</td>
          <td class="num">${r.margin ?? "—"}</td>
          <td class="num ${r.ret1y != null ? pctCls(r.ret1y) : ""}">${r.ret1y ?? "—"}</td>
        </tr>`).join("")}</tbody></table></div>`;
    } else if (kind === "events") {
      const d = await api(`/api/events/${symbol}`);
      out.innerHTML = `<div class="section-label">Corporate events</div>
        <div class="hint">Next results: <b>${d.next_earnings ? d.next_earnings.slice(0, 10) : "no date on Yahoo"}</b></div>
        ${d.dividends.length ? `<div class="hint">Recent dividends: ${d.dividends.map(v => `₹${v.amount} (${v.date})`).join(" · ")}</div>` : ""}
        ${d.splits.length ? `<div class="hint">Splits/bonus: ${d.splits.map(s => `${s.ratio}:1 on ${s.date}`).join(" · ")}
          — remember: raw (SmartAPI) price history around these dates won't match adjusted charts.</div>` : ""}`;
    } else if (kind === "delivery") {
      const d = await api(`/api/delivery/${symbol}`);
      out.innerHTML = `<div class="section-label">Delivery % (NSE)</div>
        <div id="delivChart" class="chart-box small"></div>
        <div class="hint">Share of traded quantity actually taken home.
        Rising delivery on up-days reads as real accumulation; price spikes
        on low delivery are intraday churn.</div>`;
      const c = LightweightCharts.createChart($("#delivChart"), CHART_OPTS);
      c.addLineSeries({ color: "#D9B45B", lineWidth: 1 }).setData(d.series);
      c.timeScale().fitContent(); drawerCharts.push(c);
    } else if (kind === "depth") {
      const d = await api(`/api/depth/${symbol}`);
      const row = (b, a) => `<tr>
        <td class="num pos">${b ? fmt(b.qty, 0) : ""}</td>
        <td class="num pos">${b ? fmt(b.price) : ""}</td>
        <td class="num neg">${a ? fmt(a.price) : ""}</td>
        <td class="num neg">${a ? fmt(a.qty, 0) : ""}</td></tr>`;
      out.innerHTML = `<div class="section-label">Market depth · LTP ${fmt(d.ltp)}</div>
        <div class="table-card"><table><thead><tr><th class="num">Bid qty</th>
        <th class="num">Bid</th><th class="num">Ask</th><th class="num">Ask qty</th></tr></thead>
        <tbody>${[0,1,2,3,4].map(i => row(d.bids[i], d.asks[i])).join("")}</tbody></table></div>
        <div class="hint">Totals: buy ${fmt(d.total_buy_qty, 0)} vs sell ${fmt(d.total_sell_qty, 0)}.
        Meaningful only during market hours.</div>`;
    }
  } catch (e) { out.innerHTML = `<div class="inline-msg err">${e.message}</div>`; }
}

async function loadTape() {
  try {
    const d = await api("/api/tape");
    const wrap = $("#tapeWrap");
    if (!d.items.length) { wrap.classList.add("hidden"); return; }
    const half = d.items.map(i => `<span class="item tape-click" data-sym="${i.symbol}">${
      i.held ? `<span class="held-dot" title="In portfolio">◆</span>` : ""
    }<span class="sym">${i.label}</span><span class="px">${fmt(i.last)}</span>${
      i.pct != null ? `<span class="chg ${pctCls(i.pct)}">${pctTxt(i.pct)}</span>` : ""
    }<span class="sep">·</span></span>`).join("");
    const tape = $("#tape");
    tape.innerHTML = half + half;            /* 2x for a seamless loop */
    tape.querySelectorAll(".tape-click").forEach(el =>
      el.addEventListener("click", () => openSymbol(el.dataset.sym)));
    tape.style.setProperty("--tape-duration",
      `${Math.max(30, d.items.length * 3)}s`);
    wrap.classList.remove("hidden");
  } catch (e) { $("#tapeWrap").classList.add("hidden"); }
}


/* ---------------- More page: quarantined extras ---------------- */
function moreSymbolOptions() {
  return WL.filter(i => i.type !== "mf")
    .map(i => `<option value="${i.symbol}">${(i.symbol || "").split(".")[0]}</option>`).join("");
}
async function loadShareholding() {
  const sym = $("#shSymbol").value, out = $("#shOut");
  if (!sym) return;
  try {
    const d = await api(`/api/shareholding/${sym}`);
    const rows = d.series;
    const bars = (key, color) => rows.map(r => r[key] == null ? "" :
      `<div class="sh-bar" style="height:${r[key]}%;background:${color}" title="${r.quarter}: ${r[key]}%"></div>`).join("");
    out.innerHTML = `
      ${d.notes.map(n => `<div class="inline-msg warn">${n}</div>`).join("")}
      <div class="table-card"><table><thead><tr><th>Quarter</th>
        <th class="num">Promoter</th><th class="num">Pledged</th>
        <th class="num">FII</th><th class="num">DII</th><th></th></tr></thead><tbody>
        ${rows.map(r => `<tr>
          <td class="num">${r.quarter}</td>
          <td class="num">${r.promoter ?? "—"}</td>
          <td class="num ${r.pledged ? "neg" : ""}">${r.pledged ?? "—"}</td>
          <td class="num">${r.fii ?? "—"}</td><td class="num">${r.dii ?? "—"}</td>
          <td><button class="rm-btn" style="opacity:1" data-shrm="${r.quarter}">✕</button></td>
        </tr>`).join("")}</tbody></table></div>`;
    document.querySelectorAll("[data-shrm]").forEach(b =>
      b.addEventListener("click", async () => {
        await api(`/api/shareholding/${sym}/${b.dataset.shrm}`, { method: "DELETE" });
        loadShareholding();
      }));
  } catch (e) { out.innerHTML = `<div class="hint">${e.message}</div>`; }
}
function loadMore() {
  const opts = moreSymbolOptions();
  const shPrev = $("#shSymbol").value, nwPrev = $("#nwSymbol").value;
  $("#shSymbol").innerHTML = opts; if (shPrev) $("#shSymbol").value = shPrev;
  $("#nwSymbol").innerHTML = opts; if (nwPrev) $("#nwSymbol").value = nwPrev;
  loadShareholding(); renderNewsLinks();
}
$("#shSymbol").addEventListener("change", loadShareholding);
$("#shAdd").addEventListener("click", async () => {
  const msg = $("#shMsg");
  const num = id => $(id).value === "" ? null : +$(id).value;
  try {
    await api("/api/shareholding", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: $("#shSymbol").value, quarter: $("#shQuarter").value.trim(),
        promoter: num("#shPromoter"), pledged: num("#shPledged"),
        fii: num("#shFii"), dii: num("#shDii"),
      }),
    });
    msg.classList.add("hidden");
    ["#shQuarter", "#shPromoter", "#shPledged", "#shFii", "#shDii"]
      .forEach(id => $(id).value = "");
    loadShareholding();
  } catch (e) { msg.className = "inline-msg err"; msg.textContent = e.message; }
});

function renderNewsLinks() {
  const sym = $("#nwSymbol").value;
  if (!sym) { $("#nwLinks").innerHTML = ""; return; }
  const base = sym.split(".")[0];
  const links = [
    ["Google News", `https://news.google.com/search?q=${encodeURIComponent(base + " stock NSE")}`],
    ["Screener.in", `https://www.screener.in/company/${base}/`],
    ["NSE announcements", `https://www.nseindia.com/get-quotes/equity?symbol=${base}`],
    ["TradingView", `https://www.tradingview.com/symbols/NSE-${base}/`],
  ];
  $("#nwLinks").innerHTML = links.map(([label, url]) =>
    `<a class="btn" href="${url}" target="_blank" rel="noopener">${label} ↗</a>`).join("");
}
$("#nwSymbol").addEventListener("change", renderNewsLinks);

$("#opBtn").addEventListener("click", async () => {
  const out = $("#opOut");
  const sym = $("#opSymbol").value.trim().toUpperCase();
  if (!sym) return;
  out.innerHTML = skeleton(2);
  try {
    const d = await api(`/api/option-sentiment/${sym}`);
    out.innerHTML = `
      <div class="summary-row">
        <div class="metric"><div class="k">PCR (OI)</div><div class="v">${d.pcr ?? "—"}</div></div>
        <div class="metric"><div class="k">Max pain</div><div class="v">${fmt(d.max_pain, 0)}</div>
          <div class="d">spot ${fmt(d.underlying)}</div></div>
        <div class="metric"><div class="k">Expiry</div><div class="v" style="font-size:0.95rem">${d.expiry}</div></div>
      </div>
      <div class="hint">Put OI ${fmt(d.put_oi, 0)} · Call OI ${fmt(d.call_oi, 0)}</div>
      <div class="ck-frame">${d.read}</div>`;
  } catch (e) { out.innerHTML = `<div class="inline-msg err">${e.message}</div>`; }
});

/* ------------------------------------------------ home */
function goto(page) {
  document.querySelector(`.rail-link[data-page="${page}"]`).click();
}
document.querySelectorAll("[data-goto]").forEach(b =>
  b.addEventListener("click", () => goto(b.dataset.goto)));
$("#brandHome").addEventListener("click", () => goto("home"));
$("#brandHome").addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") goto("home");
});
$("#homeRefresh").addEventListener("click", () => {
  goto("watchlist"); $("#refreshBtn").click();
});

async function loadHome() {
  try {
    const d = await api("/api/home");
    const p = d.portfolio;
    $("#homeCards").innerHTML = `
      <div class="metric"><div class="k">Advancing / declining</div>
        <div class="v"><span class="pos">${d.advancing}</span> / <span class="neg">${d.declining}</span></div></div>
      ${p && p.current ? `<div class="metric"><div class="k">Portfolio</div>
        <div class="v">₹${fmt(p.current, 0)}</div>
        <div class="d ${pctCls(p.day_pnl)}">today ${p.day_pnl >= 0 ? "+" : ""}₹${fmt(p.day_pnl, 0)} (${pctTxt(p.day_pct)})</div></div>
      <div class="metric"><div class="k">Total P&amp;L</div>
        <div class="v ${pctCls(p.pnl_incl_div)}">₹${fmt(p.pnl_incl_div, 0)}</div>
        <div class="d ${pctCls(p.pnl_incl_div_pct)}">${p.pnl_incl_div_pct >= 0 ? "+" : ""}${p.pnl_incl_div_pct}% incl. dividends</div></div>` : ""}
      <div class="metric"><div class="k">Signals today</div>
        <div class="v">${d.signals_today}</div></div>
      <div class="metric"><div class="k">Data through</div>
        <div class="v" style="font-size:1rem">${d.data_through || "—"}</div></div>`;
    $("#homeMovers").innerHTML = d.movers.map(m => `
      <div class="home-row" data-open="${m.symbol}">
        <span class="mono">${m.symbol}</span>
        <span class="num">${fmt(m.last)}</span>
        <span class="num ${pctCls(m.pct)}">${pctTxt(m.pct)}</span>
      </div>`).join("") || `<div class="empty">Refresh data to see today's moves.</div>`;
    $("#homeEarnCard").classList.toggle("hidden", !(d.earnings_week && d.earnings_week.length));
    if (d.earnings_week && d.earnings_week.length) {
      $("#homeEarnings").innerHTML = d.earnings_week.map(e => `
        <div class="home-row"><span class="mono">${e.symbol}</span>
        <span>results due</span><span class="num">${e.date}</span></div>`).join("");
    }
    $("#homeJournal").innerHTML = d.journal.map(j => `
      <div class="home-row">
        <span class="mono">${(j.symbol || "").split(".")[0]}</span>
        <span>${j.signal}</span>
        <span class="num muted">${(j.created || "").slice(0, 10)}</span>
      </div>`).join("") || `<div class="empty">Signals will appear here after a refresh + scan.</div>`;
    $("#homePf").innerHTML = p && p.current ? `
      <div class="home-pf-line">Invested <b>₹${fmt(p.invested, 0)}</b> · now
        <b>₹${fmt(p.current, 0)}</b> · dividends <b>₹${fmt(p.dividends, 0)}</b></div>
      <div class="hint">Open the Portfolio tab for the value-vs-index chart,
        allocation, and per-stock research.</div>`
      : `<div class="empty">No holdings yet — add your first in the Portfolio tab.</div>`;
    document.querySelectorAll("#homeMovers [data-open]").forEach(r =>
      r.addEventListener("click", () => {
        const it = WL.find(i => (i.symbol || "").split(".")[0] === r.dataset.open);
        if (it) openDrawer(it);
      }));
  } catch (e) {}
}

/* ------------------------------------------------ auth chrome */
api("/api/auth/me").then(d => {
  if (d.user) $("#railUser").textContent = d.user;
}).catch(() => {});
on("#logoutBtn", "click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.href = "/login";
});
on("#addUserBtn", "click", async () => {
  const vals = await dlgForm("Create account", [
    { name: "username", label: "Username", placeholder: "e.g. priya" },
    { name: "password", label: "Password (8+ characters)", type: "password" },
  ], "Create");
  if (!vals || !vals.username || !vals.password) return;
  try {
    await api("/api/auth/add-user", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: vals.username,
                             password: vals.password }),
    });
    toast(`Account "${vals.username.trim().toLowerCase()}" created — it `
      + "starts with a fresh, empty portfolio. Watchlist and market data "
      + "are shared.", "success", 6000);
  } catch (e) { toast(e.message, "error"); }
});

/* ------------------------------------------------ boot */
loadTape();
loadWatchlist().then(loadHome);
/* ====================================================================
   FEATURE PACK — command palette · theme · drag reorder · alert badge
   · XIRR · what-if · CSV import/export · compare overlay · pattern
   markers · in-app digest
   ==================================================================== */

/* ------------------------------------------------ theme toggle */
(function initTheme() {
  const btn = $("#themeBtn");
  if (!btn) return;
  const cur = () => document.documentElement.dataset.theme || "dark";
  const paint = () => { btn.textContent = cur() === "light" ? "☾" : "☀"; };
  paint();
  btn.addEventListener("click", () => {
    const next = cur() === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("wt-theme", next); } catch (e) {}
    paint();
    toast(next === "light"
      ? "Light theme. Charts keep their own colors for now."
      : "Back to the terminal look.", "info", 2500);
  });
})();

/* ------------------------------------------------ alert badge */
function setAlertBadge(n) {
  const link = document.querySelector('.rail-link[data-page="watchlist"]');
  if (!link) return;
  let b = link.querySelector(".rail-badge");
  if (!n) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement("span"); b.className = "rail-badge"; link.appendChild(b); }
  b.textContent = n;
  b.title = `${n} armed alert${n > 1 ? "s" : ""}`;
}

/* ------------------------------------------------ drag-to-reorder */
function wireDragReorder() {
  const list = $("#wlList");
  let dragEl = null;
  list.querySelectorAll(".wl-row").forEach(row => {
    row.addEventListener("dragstart", (e) => {
      dragEl = row; row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    row.addEventListener("dragend", async () => {
      row.classList.remove("dragging"); dragEl = null;
      const ids = [...list.querySelectorAll(".wl-row")].map(r => +r.dataset.id);
      /* keep WL in the new order so heatmap/selects agree */
      WL.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
      try { await api("/api/watchlist/reorder", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }) });
      } catch (e) { toast("Order not saved: " + e.message, "error"); }
    });
    row.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (!dragEl || dragEl === row) return;
      const r = row.getBoundingClientRect();
      const before = e.clientY < r.top + r.height / 2;
      row.parentNode.insertBefore(dragEl, before ? row : row.nextSibling);
    });
  });
}

/* ------------------------------------------------ XIRR (approx) */
function xirr(flows) {
  /* flows: [{date: Date, amount: negative for money in}] + final value.
     Newton's method on the annualized rate. */
  if (flows.length < 2) return null;
  const t0 = flows[0].date;
  const yrs = f => (f.date - t0) / (365.25 * 864e5);
  const npv = r => flows.reduce((s, f) => s + f.amount / Math.pow(1 + r, yrs(f)), 0);
  const dnpv = r => flows.reduce((s, f) =>
    s - yrs(f) * f.amount / Math.pow(1 + r, yrs(f) + 1), 0);
  let r = 0.1;
  for (let i = 0; i < 60; i++) {
    const f = npv(r), d = dnpv(r);
    if (Math.abs(d) < 1e-10) break;
    const nr = r - f / d;
    if (!isFinite(nr) || nr <= -0.999) break;
    if (Math.abs(nr - r) < 1e-7) { r = nr; break; }
    r = nr;
  }
  return isFinite(r) && Math.abs(npv(r)) < 1 ? r * 100 : null;
}
function renderXirr(d) {
  try {
    const flows = [];
    for (const h of d.holdings) {
      const since = h["Since"] || h.since;
      const inv = h["Invested"];
      if (inv && since) flows.push({ date: new Date(since), amount: -inv });
    }
    for (const dv of d.dividends || [])
      if (dv.date) flows.push({ date: new Date(dv.date), amount: +dv.amount });
    const cur = d.totals.current;
    if (!flows.length || !cur) return;
    flows.sort((a, b) => a.date - b.date);
    flows.push({ date: new Date(), amount: cur });
    const r = xirr(flows);
    if (r == null) return;
    $("#pfTotals").insertAdjacentHTML("beforeend", `
      <div class="metric"><div class="k">XIRR (approx)</div>
        <div class="v ${r >= 0 ? "pos" : "neg"}">${r >= 0 ? "+" : ""}${r.toFixed(2)}%</div>
        <div class="d">annualized · lots collapsed to first-buy dates</div></div>`);
  } catch (e) { /* cosmetic metric — never break the page for it */ }
}

/* ------------------------------------------------ what-if simulator */
function initWhatIf(d) {
  const sel = $("#wiSymbol");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = WL.filter(i => i.type !== "mf")
    .map(i => `<option value="${i.symbol}">${i.label}</option>`).join("");
  if (prev) sel.value = prev;
  $("#wiRun").onclick = () => {
    const sym = sel.value;
    const qty = +$("#wiQty").value;
    const it = WL.find(w => w.symbol === sym);
    const price = +$("#wiPrice").value || (it && it.last);
    if (!(qty > 0) || !(price > 0))
      return toast("Enter a quantity (and a price if there's no last close).", "error");
    const add = qty * price;
    const curTotal = (PF && PF.totals && PF.totals.current) || 0;
    const newTotal = curTotal + add;
    const base = sym.split(".")[0];
    const alloc = ((PF && PF.allocation) || []).map(a => ({ ...a }));
    const mine = alloc.find(a => a.label === base);
    if (mine) mine.value += add; else alloc.push({ label: base, value: add });
    alloc.sort((a, b) => b.value - a.value);
    const top = alloc.slice(0, 6);
    const maxW = top.length ? top[0].value / newTotal * 100 : 0;
    $("#wiOut").innerHTML = `
      <div class="inline-msg">
        Buying <b>${qty} × ${base}</b> @ ₹${fmt(price)} = <b>₹${fmt(add, 0)}</b>
        → portfolio ₹${fmt(newTotal, 0)}.
        ${maxW > 30 ? `<span class="warn">Largest position would be
          ${maxW.toFixed(1)}% — concentrated.</span>` : ""}
      </div>
      <div class="hbar-list">${top.map(a => {
        const w = a.value / newTotal * 100;
        return `<div class="hbar">
          <span class="lbl">${a.label}${a.label === base ? " ←" : ""}</span>
          <span class="track"><span class="fill" style="left:0;width:${w}%;
            background:${a.label === base ? "var(--primary)" : "var(--muted)"}"></span></span>
          <span class="val">${w.toFixed(1)}%</span></div>`;
      }).join("")}</div>`;
  };
}

/* ------------------------------------------------ CSV export / import */
on("#pfExport", "click", () => {
  if (!PF || !PF.holdings.length) return toast("No holdings to export.", "info");
  const rows = [["symbol", "qty", "avg_cost", "first_buy", "invested",
                 "current", "pnl"]];
  for (const h of PF.holdings)
    rows.push([h["Symbol"], h["Qty"], h["Avg cost"], h["Since"] || "",
               h["Invested"], h["Current"] ?? "", h["P&L"] ?? ""]);
  const csv = rows.map(r => r.join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `holdings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(a.href);
});
on("#pfImport", "change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  let added = 0, failed = 0;
  for (const line of lines) {
    const [symRaw, qty, price, date] = line.split(",").map(x => (x || "").trim());
    if (!symRaw || /symbol/i.test(symRaw)) continue;        /* header row */
    if (!(+qty > 0) || !(+price > 0)) { failed++; continue; }
    try {
      await api("/api/portfolio", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: symRaw.toUpperCase(),
          qty: +qty, buy_price: +price, buy_date: date || null }),
      });
      added++;
    } catch (err) { failed++; }
  }
  e.target.value = "";
  toast(`Imported ${added} holding${added !== 1 ? "s" : ""}` +
        (failed ? ` · ${failed} row${failed > 1 ? "s" : ""} skipped` : "") +
        ". Rows: symbol,qty,buy_price,buy_date", failed ? "info" : "success");
  loadPortfolio();
});

/* ------------------------------------------------ compare overlay */
function wireCompare(item, candles) {
  const sel = $("#cmpSel");
  if (!sel) return;
  sel.onchange = async () => {
    const other = sel.value;
    const box = $("#cmpChart"), note = $("#cmpNote");
    if (!other) { box.classList.add("hidden"); note.classList.add("hidden"); return; }
    note.classList.remove("hidden");
    note.textContent = "Loading…";
    try {
      const od = await api(`/api/detail/${other}`);
      box.classList.remove("hidden"); box.innerHTML = "";
      /* both series rebased to 100 at the later of the two start dates */
      const a = candles.map(c => ({ time: c.time, value: c.close }));
      const b = od.candles.map(c => ({ time: c.time, value: c.close }));
      const start = a[0].time > b[0].time ? a[0].time : b[0].time;
      const cut = s => s.filter(p => p.time >= start);
      const rebase = s => { const f = s[0].value; return s.map(p =>
        ({ time: p.time, value: +(p.value / f * 100).toFixed(2) })); };
      const A = rebase(cut(a)), B = rebase(cut(b));
      const c = LightweightCharts.createChart(box, CHART_OPTS);
      c.addLineSeries({ color: "#2563EB", lineWidth: 2 }).setData(A);
      c.addLineSeries({ color: "#D9B45B", lineWidth: 2 }).setData(B);
      c.timeScale().fitContent(); drawerCharts.push(c);
      const la = A[A.length - 1].value - 100, lb = B[B.length - 1].value - 100;
      note.innerHTML = `Both start at 100 on ${start}. Since then:
        <b style="color:#2563EB">${item.label} ${la >= 0 ? "+" : ""}${la.toFixed(1)}%</b> ·
        <b style="color:#D9B45B">${other.split(".")[0]} ${lb >= 0 ? "+" : ""}${lb.toFixed(1)}%</b>`;
    } catch (e) { note.textContent = e.message; }
  };
}

/* ------------------------------------------------ today's pattern markers */
async function markActivePatterns(series, candles, symbol) {
  try {
    const d = await api(`/api/patterns/${symbol}`);
    const active = (d.candles || []).filter(c => c.active_today);
    if (!active.length || !candles.length) return;
    series.setMarkers([{
      time: candles[candles.length - 1].time,
      position: "aboveBar", color: "#F59E0B", shape: "arrowDown",
      text: active.map(c => c.name || c.label || c.key).join(" · "),
    }]);
  } catch (e) { /* patterns are optional garnish on the chart */ }
}

/* ------------------------------------------------ in-app digest */
on("#dgBtn", "click", async () => {
  const btn = $("#dgBtn"), out = $("#dgOut");
  btn.disabled = true; btn.textContent = "Building…";
  try {
    const d = await api("/api/digest");
    out.textContent = d.text;
    out.classList.remove("hidden");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "Generate"; }
});

/* ------------------------------------------------ command palette (Ctrl+K) */
(function cmdk() {
  const PAGES = [
    ["home", "Home"], ["watchlist", "Watchlist"], ["portfolio", "Portfolio"],
    ["screener", "Screener"], ["ailab", "AI Lab"], ["backtest", "Backtest"],
    ["journal", "Journal"], ["more", "More"],
  ];
  let ov = null, sel = 0, items = [];

  function build() {
    ov = document.createElement("div");
    ov.className = "ck-overlay hidden";
    ov.innerHTML = `<div class="ck-box">
      <input id="ckInput" placeholder="Jump to a page or stock…  (Esc closes)" autocomplete="off">
      <div id="ckList" class="ck-items"></div></div>`;
    document.body.appendChild(ov);
    ov.addEventListener("mousedown", (e) => { if (e.target === ov) hide(); });
    $("#ckInput").addEventListener("input", render);
    $("#ckInput").addEventListener("keydown", (e) => {
      if (e.key === "Escape") hide();
      else if (e.key === "ArrowDown") { sel = Math.min(sel + 1, items.length - 1); paint(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
      else if (e.key === "Enter") { const it = items[sel]; if (it) { hide(); it.go(); } }
    });
  }
  function render() {
    const q = $("#ckInput").value.toLowerCase().trim();
    const pages = PAGES
      .filter(([_, l]) => !q || l.toLowerCase().includes(q))
      .map(([id, l]) => ({ kind: "Page", label: l, sub: "", go: () => goto(id) }));
    const stocks = WL
      .filter(i => i.label.toLowerCase().includes(q) ||
                   (i.symbol || "").toLowerCase().includes(q))
      .slice(0, q ? 8 : 5)
      .map(i => ({ kind: i.type.toUpperCase(), label: i.label,
        sub: i.pct != null ? pctTxt(i.pct) : "",
        cls: i.pct != null ? pctCls(i.pct) : "",
        go: () => openDrawer(i) }));
    items = q ? [...stocks, ...pages] : [...pages, ...stocks];
    sel = 0; paint();
  }
  function paint() {
    $("#ckList").innerHTML = items.map((it, i) => `
      <div class="ck-item ${i === sel ? "sel" : ""}" data-i="${i}">
        <span class="ck-kind">${it.kind}</span>
        <span class="ck-label">${it.label}</span>
        <span class="ck-sub ${it.cls || ""}">${it.sub || ""}</span>
      </div>`).join("") ||
      `<div class="ck-item">Nothing matches.</div>`;
    $("#ckList").querySelectorAll(".ck-item[data-i]").forEach(el =>
      el.addEventListener("click", () => { const it = items[+el.dataset.i];
        if (it) { hide(); it.go(); } }));
  }
  function show() {
    if (!ov) build();
    ov.classList.remove("hidden");
    $("#ckInput").value = ""; render();
    $("#ckInput").focus();
  }
  function hide() { if (ov) ov.classList.add("hidden"); }
  const goto = (id) =>
    document.querySelector(`.rail-link[data-page="${id}"]`)?.click();
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      (ov && !ov.classList.contains("hidden")) ? hide() : show();
    }
  });
})();

/* ====================================================================
   FEATURE PACK 2 — tier chips & changes · data doctor · SIP · tax ·
   rebalance · notes · PWA registration
   ==================================================================== */

/* ------------------------------------------------ checklist tiers */
let TIERS_MAP = {};
function tierChip(symbol, tiny = false) {
  const t = TIERS_MAP[symbol];
  if (!t) return "";
  const short = { strong: "S", mixed: "M", weak: "W" }[t] || "?";
  return ` <span class="tier-chip t-${t} ${tiny ? "tiny" : ""}"
    title="Research checklist: ${t} — an assessment aid, never a call">${
    tiny ? short : t.toUpperCase()}</span>`;
}
let tiersTimer = null;
async function loadTiers() {
  try {
    const d = await api("/api/tiers");
    if (d.ready) {
      const had = Object.keys(TIERS_MAP).length;
      TIERS_MAP = d.tiers || {};
      if (!had) {                    /* first arrival: paint the chips in */
        renderWatchlist();
        if (!$("#wlHeatmap").classList.contains("hidden")) renderHeatmap();
      }
      renderTierChanges(d.changes || []);
    } else if (d.computing && !tiersTimer) {
      tiersTimer = setTimeout(() => { tiersTimer = null; loadTiers(); }, 4000);
    }
  } catch (e) { /* chips are garnish — never block the list */ }
}
function renderTierChanges(changes) {
  const card = $("#homeTierCard");
  if (!card) return;
  if (!changes.length) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  const arrow = (a, b) => {
    const rank = { weak: 0, mixed: 1, strong: 2 };
    return rank[b] > rank[a] ? "▲" : "▼";
  };
  $("#homeTiers").innerHTML = changes.slice(0, 8).map(c => `
    <div class="tier-row" data-sym="${c.symbol}">
      <span class="wl-name">${c.symbol.split(".")[0]}</span>
      <span class="tier-chip t-${c.from}">${c.from}</span>
      <span class="tc-arrow ${arrow(c.from, c.to) === "▲" ? "pos" : "neg"}">${arrow(c.from, c.to)}</span>
      <span class="tier-chip t-${c.to}">${c.to}</span>
      <span class="muted mono" style="margin-left:auto;font-size:.68rem">${c.date}</span>
    </div>`).join("");
  $("#homeTiers").querySelectorAll(".tier-row").forEach(r =>
    r.addEventListener("click", () => {
      const it = WL.find(i => i.symbol === r.dataset.sym);
      if (it) openDrawer(it);
    }));
}

/* ------------------------------------------------ data doctor */
async function drScan() {
  const d = await api("/api/doctor/report");
  $("#drSummary").classList.remove("hidden");
  $("#drSummary").innerHTML = `
    <div class="metric"><div class="k">Symbols</div><div class="v">${d.symbols.length}</div></div>
    <div class="metric"><div class="k">Broken (&lt;30 rows)</div>
      <div class="v ${d.broken ? "neg" : "pos"}">${d.broken}</div></div>
    <div class="metric"><div class="k">Thin (&lt;250 rows)</div>
      <div class="v ${d.thin ? "warn" : "pos"}">${d.thin}</div></div>`;
  const bad = d.symbols.filter(s => !s.ok);
  $("#drTable").innerHTML = !bad.length
    ? `<div class="empty">Every symbol has healthy history. 🎉</div>`
    : `<table><thead><tr><th>Symbol</th><th class="num">Rows</th>
        <th>Source</th><th>State</th></tr></thead><tbody>${
        bad.map(s => `<tr><td>${s.symbol}</td>
          <td class="num">${s.rows}</td>
          <td>${s.source || "—"}</td>
          <td>${s.empty ? '<span class="tier-chip t-weak">EMPTY</span>'
              : s.thin ? '<span class="tier-chip t-mixed">THIN</span>' : ""}
          </td></tr>`).join("")}</tbody></table>`;
}
on("#drScan", "click", drScan);
on("#drFix", "click", async () => {
  $("#drFix").classList.add("busy");
  await api("/api/doctor/repair", { method: "POST" });
  $("#drLog").classList.remove("hidden");
  const t = setInterval(async () => {
    const s = await api("/api/doctor/status");
    $("#drLog").textContent = s.log.join("\n") || "starting…";
    $("#drLog").scrollTop = $("#drLog").scrollHeight;
    if (!s.running && s.done) {
      clearInterval(t);
      $("#drFix").classList.remove("busy");
      toast("Data repair finished.", "success");
      drScan(); loadWatchlist();
    }
  }, 1500);
});

/* ------------------------------------------------ SIPs */
async function loadSips() {
  const sel = $("#spScheme");
  if (!sel) return;
  sel.innerHTML = WL.filter(i => i.type === "mf")
    .map(i => `<option value="${i.scheme_code}">${i.label}</option>`).join("")
    || `<option value="">No MFs on watchlist</option>`;
  try {
    const d = await api("/api/sips");
    $("#spList").innerHTML = !d.sips.length ? "" : d.sips.map(s => {
      const e = s.eval;
      return `<div class="div-row">
        <span>${s.label}<br><span class="muted">₹${fmt(s.amount, 0)}/mo ·
          day ${s.day} · since ${s.start}</span></span>
        <span class="num">${e ? "₹" + fmt(e.value, 0) : "—"}</span>
        <span class="num ${e && e.xirr_pct >= 0 ? "pos" : "neg"}">${
          e ? (e.xirr_pct >= 0 ? "+" : "") + e.xirr_pct.toFixed(1) + "% XIRR" : "no NAVs yet"}</span>
        <button class="rm-btn" style="opacity:1" data-sprm="${s.id}">✕</button>
      </div>`;
    }).join("");
    $("#spList").querySelectorAll("[data-sprm]").forEach(b =>
      b.addEventListener("click", async () => {
        await api(`/api/sips/${b.dataset.sprm}`, { method: "DELETE" });
        loadSips();
      }));
  } catch (e) { /* sip card is optional */ }
}
on("#spAdd", "click", async () => {
  try {
    await api("/api/sips", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheme_code: +$("#spScheme").value,
        amount: +$("#spAmount").value, day_of_month: +$("#spDay").value,
        start_date: $("#spStart").value }),
    });
    toast("SIP added — simulated against real NAV history.", "success");
    loadSips();
  } catch (e) { toast(e.message, "error"); }
});

/* ------------------------------------------------ rebalance helper */
function renderRebalance() {
  const box = $("#rbBody");
  if (!box) return;
  if (!PF || !PF.holdings || !PF.holdings.length) {
    box.innerHTML = `<div class="empty">Add holdings first — the helper
      works off your live portfolio.</div>`;
    return;
  }
  const hs = PF.holdings.filter(h => h["Current"] != null);
  const skipped = PF.holdings.length - hs.length;
  if (!hs.length) {
    box.innerHTML = `<div class="empty">Your holdings have no price data
      yet — run Refresh data (or the Data doctor) first.</div>`;
    return;
  }
  const total = PF.totals.current || 1;
  box.innerHTML = `
    <div class="rb-row rb-head">
      <span class="lbl">Holding</span><span class="mono">Now</span>
      <span>Target %</span><span style="text-align:right">Trade</span>
    </div>` + hs.map(h => {
    const w = (h["Current"] / total * 100);
    return `<div class="rb-row" data-sym="${h["Symbol"]}" data-cur="${h["Current"]}">
      <span class="lbl">${h["Symbol"].split(".")[0]}</span>
      <span class="mono muted">${w.toFixed(1)}%</span>
      <input type="number" class="rb-target" value="${w.toFixed(1)}"
        step="0.5" min="0" title="Target weight %">
      <span class="rb-delta mono muted">—</span>
    </div>`;
  }).join("") +
  (skipped ? `<div class="hint">${skipped} holding(s) without price data
     excluded.</div>` : "") +
  `<div class="hint" id="rbSum"></div>`;
  const compute = () => {
    let sumT = 0;
    box.querySelectorAll(".rb-row[data-sym]").forEach(r =>
      sumT += +r.querySelector(".rb-target").value || 0);
    let buys = 0, sells = 0;
    box.querySelectorAll(".rb-row[data-sym]").forEach(r => {
      const target = (+r.querySelector(".rb-target").value || 0)
        / (sumT || 100) * 100;
      const delta = target / 100 * total - (+r.dataset.cur);
      const el = r.querySelector(".rb-delta");
      if (Math.abs(delta) < total * 0.005) {
        el.textContent = "≈ hold"; el.className = "rb-delta mono muted";
      } else {
        el.textContent = `${delta > 0 ? "BUY" : "SELL"} ₹${fmt(Math.abs(delta), 0)}`;
        el.className = "rb-delta mono " + (delta > 0 ? "pos" : "neg");
        delta > 0 ? buys += delta : sells -= delta;
      }
    });
    $("#rbSum").innerHTML = `Targets sum to <b>${sumT.toFixed(1)}%</b>`
      + (Math.abs(sumT - 100) > 0.5 ? " (normalized to 100% for the math)" : "")
      + ` · total to buy ₹${fmt(buys, 0)} · to sell ₹${fmt(sells, 0)}.
      Check the Tax report before selling — rebalances can realize STCG.`;
  };
  box.querySelectorAll(".rb-target").forEach(inp =>
    inp.addEventListener("input", compute));
  compute();                          /* live from the first paint */
}
on("#rbEq", "click", () => {
  const rows = document.querySelectorAll("#rbBody .rb-row[data-sym]");
  if (!rows.length) return toast("Open Portfolio with holdings first.", "info");
  const eq = (100 / rows.length).toFixed(1);
  rows.forEach(r => {
    const inp = r.querySelector(".rb-target");
    inp.value = eq;
    inp.dispatchEvent(new Event("input"));
  });
});

/* ------------------------------------------------ tax report */
on("#txBtn", "click", async () => {
  try {
    const d = await api("/api/taxreport");
    $("#txOut").innerHTML = !d.years.length
      ? `<div class="empty">No recorded sells yet — record sales from a
         stock's dialog and they'll show up here.</div>`
      : `<table><thead><tr><th>FY</th><th class="num">STCG ₹</th>
          <th class="num">LTCG ₹</th><th class="num">Trades</th></tr></thead>
        <tbody>${d.years.map(y => `<tr><td>${y.fy}</td>
          <td class="num ${y.stcg >= 0 ? "pos" : "neg"}">${fmt(y.stcg, 0)}</td>
          <td class="num ${y.ltcg >= 0 ? "pos" : "neg"}">${fmt(y.ltcg, 0)}</td>
          <td class="num">${y.trades}${y.unknown_period
            ? ` <span class="warn" title="Sells with no buy date counted as STCG">⚠${y.unknown_period}</span>` : ""}</td>
        </tr>`).join("")}</tbody></table>
        <p class="hint">Sells missing a buy date are counted as STCG
          (conservative). Verify against your broker's statement.</p>`;
  } catch (e) { toast(e.message, "error"); }
});

/* ------------------------------------------------ notes */
async function wireNotes(symbol) {
  const list = $("#ntList");
  if (!list) return;
  async function paint() {
    try {
      const d = await api(`/api/notes/${symbol}`);
      list.innerHTML = !d.notes.length
        ? `<div class="hint">Nothing yet — future-you will thank present-you
           for writing the thesis down.</div>`
        : d.notes.map(n => `<div class="nt-row">
            <span>${n.text}</span>
            <span class="muted mono">${(n.created || "").slice(0, 10)}</span>
            <button class="rm-btn" style="opacity:1" data-ntrm="${n.id}">✕</button>
          </div>`).join("");
      list.querySelectorAll("[data-ntrm]").forEach(b =>
        b.addEventListener("click", async () => {
          await api(`/api/notes/${b.dataset.ntrm}`, { method: "DELETE" });
          paint();
        }));
    } catch (e) { list.innerHTML = ""; }
  }
  $("#ntAdd").onclick = async () => {
    const text = $("#ntInput").value.trim();
    if (!text) return;
    await api("/api/notes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, text }),
    });
    $("#ntInput").value = "";
    paint();
  };
  $("#ntInput").onkeydown = (e) => { if (e.key === "Enter") $("#ntAdd").click(); };
  paint();
}

/* ------------------------------------------------ page-load hookups */
document.querySelector('.rail-link[data-page="more"]')
  ?.addEventListener("click", () => { if (!$("#drSummary").innerHTML) drScan(); });

/* ------------------------------------------------ PWA */
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/static/js/sw.js").catch(() => {});

/* ====================================================================
   DESIGN v4 hooks — per-page accent + home greeting
   ==================================================================== */
(function pageAccent() {
  const set = (p) => { document.body.dataset.page = p; };
  document.querySelectorAll(".rail-link").forEach(b =>
    b.addEventListener("click", () => set(b.dataset.page)));
  set("home");
  /* greeting under the Home title */
  const head = document.querySelector("#page-home .page-head");
  if (head && !head.querySelector(".hero-sub")) {
    const h = new Date().getHours();
    const word = h < 5 ? "Late night" : h < 12 ? "Good morning"
               : h < 17 ? "Good afternoon" : "Good evening";
    const el = document.createElement("div");
    el.className = "hero-sub";
    el.textContent = `${word} — ${new Date().toLocaleDateString("en-IN",
      { weekday: "long", day: "numeric", month: "long" })}`;
    head.appendChild(el);
  }
})();
