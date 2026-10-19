/* AI Analyst page — self-injecting drop-in.
 *
 * Install: put this file in static/ and add ONE line to index.html,
 * just before </body> (after the app.js script tag):
 *
 *     <script src="/static/js/analyst.js"></script>
 *
 * It injects its own rail button + page section at runtime, so app.js
 * and index.html need no other edits. The button mimics the app's own
 * rail-link behaviour (active state, hide all .page, show this one),
 * because app.js binds its click handlers before this script runs.
 */
(function () {
  "use strict";

  /* ---------------------------------------- markdown -> safe HTML */
  const css = document.createElement("style");
  css.textContent = `
    .ana-md { white-space: normal; line-height: 1.55; }
    .ana-md p { margin: 0 0 8px; }
    .ana-md h4 { margin: 14px 0 6px; font-size: 14px; letter-spacing: .2px; }
    .ana-md ul { margin: 4px 0 8px 18px; padding: 0; }
    .ana-md li { margin: 2px 0; }
    .ana-md code { background: rgba(127,127,127,.15); padding: 1px 5px;
                   border-radius: 4px; font-size: 12.5px; }
    .ana-md table { border-collapse: collapse; margin: 8px 0; width: 100%;
                    font-size: 12.5px; display: block; overflow-x: auto; }
    .ana-md th, .ana-md td { border: 1px solid rgba(127,127,127,.3);
                             padding: 4px 8px; text-align: left; }`;
  document.head.appendChild(css);

  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                      .replace(/>/g, "&gt;");

  function mdInline(s) {
    return s.replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  }

  function mdRender(text) {
    const lines = esc(text).split("\n");
    const out = [];
    let list = null, para = [];
    const flushPara = () => { if (para.length)
      out.push("<p>" + mdInline(para.join(" ")) + "</p>"); para = []; };
    const flushList = () => { if (list)
      out.push("<ul>" + list.join("") + "</ul>"); list = null; };
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      const t = ln.trim();
      if (!t) { flushPara(); flushList(); continue; }
      if (/^#{1,6}\s+/.test(t)) { flushPara(); flushList();
        out.push("<h4>" + mdInline(t.replace(/^#{1,6}\s+/, "")) + "</h4>");
        continue; }
      if (/^[-•]\s+/.test(t)) { flushPara();
        (list = list || []).push("<li>" +
          mdInline(t.replace(/^[-•]\s+/, "")) + "</li>");
        continue; }
      if (t.startsWith("|") && t.endsWith("|")) {   // table block
        flushPara(); flushList();
        const rows = [];
        while (i < lines.length) {
          const r = lines[i].trim();
          if (!(r.startsWith("|") && r.endsWith("|"))) { i--; break; }
          if (!/^\|[\s|:-]+\|$/.test(r))           // skip |---|---|
            rows.push(r.slice(1, -1).split("|").map((c) => c.trim()));
          i++;
        }
        if (rows.length) {
          const tr = (cells, tag) => "<tr>" + cells.map((c) =>
            `<${tag}>` + mdInline(c) + `</${tag}>`).join("") + "</tr>";
          out.push("<table>" + tr(rows[0], "th") +
            rows.slice(1).map((r) => tr(r, "td")).join("") + "</table>");
        }
        continue;
      }
      para.push(t);
    }
    flushPara(); flushList();
    return out.join("");
  }

  /* ------------------------------------------------ inject nav button */
  const rail = document.querySelector(".rail-links");
  const main = document.querySelector("main.main");
  if (!rail || !main) { console.warn("[analyst] rail/main not found"); return; }

  const btn = document.createElement("button");
  btn.className = "rail-link";
  btn.dataset.page = "analyst";
  btn.innerHTML =
    '<svg class="ico ico-spark"><use href="#i-spark"/></svg><span>Analyst</span>';
  // place before "More" so it reads as a first-class page
  const moreBtn = rail.querySelector('[data-page="more"]');
  rail.insertBefore(btn, moreBtn || null);

  /* ------------------------------------------------ inject page section */
  const page = document.createElement("section");
  page.id = "page-analyst";
  page.className = "page hidden";
  page.innerHTML = `
    <div class="page-head">
      <h1 class="h1-ico"><svg class="ico ico-spark"><use href="#i-spark"/></svg>Analyst</h1>
      <button id="anaReset" class="btn btn-small" title="Forget this conversation">New chat</button>
    </div>

    <div class="card" id="anaDocsCard">
      <div class="card-head">Filings for a stock (feeds the analyst)</div>
      <div class="hint">Auto-fetch pulls annual reports / concall transcripts /
        presentations from BSE public filings. For Screener.in data use its
        official “Export to Excel” and upload the file — don't scrape.</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <input id="anaSym" placeholder="Symbol e.g. TATAPOWER.BO"
               style="width:190px" autocomplete="off">
        <input id="anaScrip" placeholder="BSE scrip code e.g. 500400"
               style="width:190px" autocomplete="off">
        <button id="anaFetchBse" class="btn">Fetch from BSE</button>
        <label class="btn" style="cursor:pointer">Upload PDF/XLSX
          <input id="anaFile" type="file" accept=".pdf,.xlsx,.xls,.txt,.md" hidden>
        </label>
        <button id="anaDocsList" class="btn btn-small">List stored</button>
      </div>
      <div id="anaDocsOut" class="hint" style="white-space:pre-wrap"></div>
    </div>

    <div id="anaLog" style="display:flex;flex-direction:column;gap:12px;
         max-width:840px;margin:14px auto 0;padding-bottom:96px"></div>

    <form id="anaForm" style="position:sticky;bottom:0;display:flex;gap:8px;
         max-width:840px;margin:0 auto;padding:12px 0;
         background:var(--bg, #09090B)">
      <input id="anaInput" style="flex:1" autocomplete="off"
        placeholder="Tear apart TATAPOWER.BO… / which stock to buy from my watchlist / same from nifty500">
      <button class="btn btn-primary" type="submit" id="anaSend">Ask</button>
    </form>`;
  main.appendChild(page);

  /* --------------------------------------- page switching (mimic app.js) */
  function showAnalyst() {
    document.querySelectorAll(".rail-link").forEach(x => x.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
    page.classList.remove("hidden");
    document.getElementById("anaInput").focus();
  }
  btn.addEventListener("click", showAnalyst);

  /* ------------------------------------------------------------- helpers */
  const log = page.querySelector("#anaLog");

  function bubble(role, text) {
    const d = document.createElement("div");
    d.className = "card";
    d.style.cssText = role === "user"
      ? "align-self:flex-end;max-width:85%"
      : "align-self:flex-start;max-width:96%;white-space:pre-wrap";
    if (role === "user") { d.style.borderColor = "var(--primary, #2F6BFF)"; }
    if (role === "user") d.textContent = text;
    else { d.classList.add("ana-md"); d.innerHTML = mdRender(text); }
    log.appendChild(d);
    d.scrollIntoView({ behavior: "smooth", block: "end" });
    return d;
  }

  async function post(url, body, isJson = true) {
    const opt = { method: "POST" };
    if (isJson) {
      opt.headers = { "Content-Type": "application/json" };
      opt.body = JSON.stringify(body);
    } else opt.body = body;                       // FormData
    const r = await fetch(url, opt);
    let j = {};
    try { j = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    return j;
  }

  /* ---------------------------------------------------------------- chat */
  let busy = false;
  page.querySelector("#anaForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    const inp = page.querySelector("#anaInput");
    const text = inp.value.trim();
    if (!text) return;
    inp.value = "";
    bubble("user", text);
    const wait = bubble("ai", "Analysing — pulling data from the app…");
    busy = true;
    page.querySelector("#anaSend").disabled = true;
    try {
      const j = await post("/api/analyst/chat", { text });
      wait.innerHTML = mdRender(j.reply || "(empty reply)");
      if (j.tools_used && j.tools_used.length) {
        const src = document.createElement("div");
        src.className = "hint";
        src.style.marginTop = "8px";
        src.textContent = "Data: " +
          [...new Set(j.tools_used.map(t => t.tool))].join(", ") +
          " · decision aid, not advice — verify before acting.";
        wait.appendChild(src);
      }
    } catch (err) {
      wait.textContent = "Analyst error: " + err.message;
    } finally {
      busy = false;
      page.querySelector("#anaSend").disabled = false;
    }
  });

  page.querySelector("#anaReset").addEventListener("click", async () => {
    try { await post("/api/analyst/reset", {}); } catch (_) {}
    log.innerHTML = "";
    bubble("ai", "New conversation. Ask me to analyse a stock, screen your " +
                 "watchlist or NIFTY universes, review your portfolio, or " +
                 "search stored filings.");
  });

  /* ----------------------------------------------------------- documents */
  const docsOut = page.querySelector("#anaDocsOut");
  const symOf = () => page.querySelector("#anaSym").value.trim().toUpperCase();

  page.querySelector("#anaFetchBse").addEventListener("click", async () => {
    const symbol = symOf();
    const scrip = page.querySelector("#anaScrip").value.trim();
    if (!symbol || !scrip) { docsOut.textContent = "Need symbol + BSE scrip code."; return; }
    docsOut.textContent = "Fetching BSE filings… (rate-limited, ~30–60s)";
    try {
      const j = await post("/api/docs/fetch-bse", { symbol, scrip_code: scrip });
      if (j.error) { docsOut.textContent = j.error; return; }
      docsOut.textContent =
        `Matched ${j.matched} filings, ingested ${j.ingested.length}:\n` +
        j.ingested.map(d => `• [${d.type}] ${d.title} (${d.filed}, ${d.chunks} chunks)`).join("\n") +
        (j.errors.length ? "\nErrors:\n" + j.errors.join("\n") : "");
    } catch (e) { docsOut.textContent = "Fetch failed: " + e.message; }
  });

  page.querySelector("#anaFile").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    const symbol = symOf();
    if (!f) return;
    if (!symbol) { docsOut.textContent = "Enter the symbol first, then upload."; return; }
    docsOut.textContent = `Uploading ${f.name}…`;
    const fd = new FormData();
    fd.append("symbol", symbol);
    fd.append("file", f);
    try {
      const j = await post("/api/docs/upload", fd, false);
      docsOut.textContent =
        `Stored as ${j.doc_type} (${j.chunks} chunks). The analyst can now ` +
        `search it — try: "what did ${symbol} management say about capex?"`;
    } catch (err) { docsOut.textContent = "Upload failed: " + err.message; }
    e.target.value = "";
  });

  page.querySelector("#anaDocsList").addEventListener("click", async () => {
    const symbol = symOf();
    if (!symbol) { docsOut.textContent = "Enter a symbol first."; return; }
    try {
      const r = await fetch(`/api/docs/${encodeURIComponent(symbol)}`);
      const j = await r.json();
      const docs = j.documents || [];
      docsOut.textContent = docs.length
        ? docs.map(d => `• [${d.doc_type}] ${d.title} — ${d.filed_date || d.added_at}`).join("\n")
        : `No filings stored for ${symbol} yet.`;
    } catch (e) { docsOut.textContent = "List failed: " + e.message; }
  });

  /* ------------------------------------------------------------ greeting */
  fetch("/api/analyst/status").then(r => r.json()).then(s => {
    const parts = [];
    if (!s.llm_ready) parts.push("No LLM key — add OPENROUTER_API_KEY (free at openrouter.ai/keys) or GROQ_API_KEY to .env to enable the analyst.");
    if (!s.web_search) parts.push("Web search off (optional: TAVILY_API_KEY for live news).");
    if (s.providers && s.providers.length) {
      const chain = s.providers.map(p => p.name + (p.daily_limit
        ? ` (${p.used_today}/${p.daily_limit} requests today)` : "")).join(" → ");
      parts.push("Providers: " + chain + ".");
    }
    bubble("ai", "Ask me to tear apart a stock, screen your watchlist / NIFTY 50 / 100 / 500, " +
                 "review your portfolio, or search stored filings." +
                 (parts.length ? "\n\n⚠ " + parts.join(" ") : ""));
  }).catch(() => {});
})();
