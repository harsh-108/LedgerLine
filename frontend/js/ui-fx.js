/* ============================================================
   ui-fx.js — visual layer: info ("i") tooltips, smooth scroll,
   scroll-reveal, and stat count-ups. Purely additive: the app
   works identically if this file is deleted.

   Design language adapted from Metric Flow (designmd.ai/chef/
   metric-flow, MIT): restrained chrome, vibrancy reserved for
   data, subtle elevation. Smooth scrolling via Lenis (lenis.dev,
   MIT) when the CDN loads; graceful no-op offline.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------------------------------------- knowledge base
     Every strategy / signal / metric the UI shows, explained:
     what it is, and why it matters for a decision. Keys match
     backend names (backtest.STRATEGIES, signal types, metric
     column labels). */
  const INFO = {
    /* -------- backtest strategies (keys = /api/strategies) */
    golden_cross: {
      t: "Golden cross (SMA 50/200)",
      d: "Holds the stock while the average price of its last 50 " +
         "days is above the average of its last 200 days — in " +
         "plain words: while the recent trend is stronger than the " +
         "long-term one.\n\nIt will never catch a bottom and " +
         "always exits late, but it keeps you out of long " +
         "declines. In a sideways stock it buys and sells " +
         "repeatedly, losing a little each time — if the backtest " +
         "shows many small losing trades, that's this stock " +
         "telling you it chops too much for the rule.",
    },
    price_above_200: {
      t: "200-day filter",
      d: "Own the stock only while its price is above the average " +
         "of its last 200 trading days (roughly one year); step " +
         "aside when it's below.\n\nOne idea, honestly held: most " +
         "disasters happen below that line. It reacts faster than " +
         "the golden cross but also gets faked out more often. If " +
         "plain buy-and-hold still beat it after costs, timing " +
         "added nothing on this stock.",
    },
    rsi_reversion: {
      t: "RSI mean reversion (30/60)",
      d: "RSI is a 0–100 gauge of recent buying and selling " +
         "pressure. This rule buys when RSI drops under 30 (the " +
         "stock has been sold hard for ~2 weeks) and sells once it " +
         "recovers past 60 — betting that panic gets " +
         "corrected.\n\nWorks on steady stocks that bounce back. " +
         "Dangerous on genuinely sinking ones, where 'sold hard' " +
         "just keeps getting harder and the bounce never comes. " +
         "Only trust it where the equity curve rose steadily, not " +
         "in one lucky spike.",
    },
    macd: {
      t: "MACD signal cross (12-26-9)",
      d: "MACD compares the stock's recent average pace with a " +
         "slower one; when the fast line crosses above its own " +
         "smoothed average, the price is accelerating upward. This " +
         "rule stays invested during those stretches.\n\nQuicker " +
         "to react than the 50/200 cross — but it trades far more " +
         "often, and every round trip pays brokerage. Check " +
         "whether the shown return survived those costs.",
    },
    breakout: {
      t: "20/10 channel breakout",
      d: "Buy when today's close is the highest close of the last " +
         "20 days; sell when it's the lowest of the last " +
         "10.\n\nThe bet: a stock strong enough to make new highs " +
         "tends to keep going. Works beautifully in long rallies. " +
         "In a sideways market it keeps buying small peaks and " +
         "selling small dips, losing a little each time — judge it " +
         "by the equity curve after costs, not by the idea.",
    },

    /* -------- signal names used on Home / alerts */
    GOLDEN_CROSS: {
      t: "Golden cross signal",
      d: "The 50-day average just crossed ABOVE the 200-day — the " +
         "medium-term trend has officially turned up. Historically " +
         "bullish, but check this stock's own base rate in the " +
         "Watchlist detail: on some names it fires late enough to " +
         "mark tops.",
    },
    DEATH_CROSS: {
      t: "Death cross signal",
      d: "The 50-day average just crossed BELOW the 200-day. The " +
         "medium-term trend has turned down. Not always a sell — but " +
         "adding to a position after one deserves an explicit reason.",
    },
    RSI_OVERSOLD: {
      t: "RSI oversold (<30)",
      d: "Selling pressure has been extreme for ~2 weeks. Either an " +
         "over-reaction (opportunity on quality names) or the start " +
         "of something worse (on leveraged/news-driven ones). Look at " +
         "the base-rate panel: what happened the last N times THIS " +
         "stock went under 30?",
    },
    RSI_OVERBOUGHT: {
      t: "RSI overbought (>70)",
      d: "Buying has been one-sided for ~2 weeks. In strong uptrends " +
         "RSI can stay overbought for months — it's a caution flag " +
         "for fresh entries, not an automatic sell.",
    },
    PRICE_ALERT: {
      t: "Price alert",
      d: "Price crossed a level you set yourself on this stock. Your " +
         "past self thought this level mattered — re-read the note " +
         "you attached before acting.",
    },

    /* -------- screener / metric columns */
    "P/E": {
      t: "Price to Earnings",
      d: "Price divided by last year's earnings per share — how many " +
         "years of current profit you pay for. Only comparable " +
         "WITHIN a sector: banks at 15 and FMCG at 55 can both be " +
         "'fair'. A P/E far below sector median is either a bargain " +
         "or a warning; the other columns decide which.",
    },
    "P/B": {
      t: "Price to Book",
      d: "Price versus accounting net worth. The go-to multiple for " +
         "banks and financials (their book value is mostly real, " +
         "marked-to-market assets). Under ~1× means the market " +
         "expects the book to shrink — ask why.",
    },
    "ROE %": {
      t: "Return on Equity",
      d: "Profit generated per rupee shareholders have in the " +
         "business. The single best one-number quality test: " +
         "sustained 15%+ compounds wealth, sub-10% usually destroys " +
         "it after inflation. Check it's not propped up by debt — " +
         "high ROE + high D/E is leverage, not quality.",
    },
    "D/E": {
      t: "Debt to Equity",
      d: "Borrowed money versus owners' money. Above ~1 for a " +
         "non-financial company means creditors have more at stake " +
         "than shareholders — fine in infra/utilities, dangerous in " +
         "cyclicals. (Ignore for banks: leverage IS their business " +
         "model.)",
    },
    "Div yield %": {
      t: "Dividend yield",
      d: "Cash paid out yearly as a % of price. A 4%+ yield on a " +
         "stable business is real return you don't need the market's " +
         "mood for; a suspiciously high yield often means the price " +
         "crashed and a cut is coming.",
    },
    Beta: {
      t: "Beta",
      d: "How violently the stock moves versus the index. 1.5 = " +
         "amplifies every swing by half again; 0.6 = sleeps through " +
         "drama. Not good or bad — it sizes positions: high-beta " +
         "names deserve smaller allocations for the same conviction.",
    },
    RSI: {
      t: "RSI 14",
      d: "A 0–100 gauge of how hard the stock has been bought or " +
         "sold over the last 14 days. Under 30 = heavy selling; " +
         "over 70 = heavy buying; 40–60 = nothing notable.\n\nBest " +
         "used with the base-rate panel in the stock's dialog, " +
         "which shows what RSI extremes actually led to on this " +
         "specific stock — not in general.",
    },
    "Momentum z": {
      t: "Momentum score",
      d: "How this stock's recent returns compare with everything " +
         "else on your list, on a simple scale: 0 = average for " +
         "your list, +2 ≈ near the top, −2 ≈ near the " +
         "bottom.\n\nWinners tend to keep winning for months at a " +
         "time — but they also fall hardest when the mood turns. " +
         "That's why this is one input of four, not a verdict.",
    },
    "Value z": {
      t: "Value score",
      d: "How cheap this stock looks (P/E and P/B blended) versus " +
         "your list: 0 = average, positive = cheaper than most, " +
         "negative = pricier.\n\nCheap alone is a trap. Pair it " +
         "with the Quality score: cheap AND high-quality is the " +
         "classic bargain; cheap and low-quality is usually cheap " +
         "for a reason.",
    },
    "Quality z": {
      t: "Quality score",
      d: "Business strength versus your list — profitability, " +
         "margins, low debt — on the same scale: 0 = average, +2 ≈ " +
         "best in list.\n\nHigh quality is what lets you hold " +
         "through bad months without panicking. High momentum on a " +
         "low-quality name is a rented rocket — fun until the fuel " +
         "runs out.",
    },
    "Trend z": {
      t: "Trend score",
      d: "Whether the price sits above or below its own recent " +
         "averages, compared across your list: 0 = average, " +
         "positive = an established uptrend.\n\nBuying a " +
         "negative-trend stock means betting that everyone selling " +
         "it is wrong — sometimes correct, always harder. The " +
         "score just tells you which fight you're picking.",
    },
    "Golden cross (SMA50 above SMA200)": {
      t: "Golden cross — this stock's own record",
      d: "The 50-day average crossed above the 200-day. The table " +
         "shows every time it happened on THIS stock and what returns " +
         "followed. Compare each row against the baseline block above " +
         "— the signal only earned its keep where it beat 'any period'.",
    },
    "Death cross (SMA50 below SMA200)": {
      t: "Death cross — this stock's own record",
      d: "The 50-day average crossed below the 200-day. Folklore says " +
         "bearish; the table shows what ACTUALLY followed on this " +
         "stock. If median returns after death crosses beat the " +
         "baseline here, the market has been buying this dip.",
    },
    "RSI dropped below 30": {
      t: "RSI oversold events",
      d: "RSI is a 0–100 gauge of recent selling pressure; under " +
         "30 means the stock has been dumped hard for about two " +
         "weeks.\n\nOn steady stocks, the months after are usually " +
         "green — the panic passes. On genuinely declining ones, " +
         "'oversold' just stays oversold while the price keeps " +
         "falling. This table shows which kind of stock you're " +
         "holding.",
    },
    "RSI rose above 70": {
      t: "RSI overbought events",
      d: "Over 70 on the 0–100 pressure gauge means about two " +
         "weeks of one-sided buying.\n\nTextbooks say 'overbought " +
         "— expect a pullback'. But in strong uptrends, stocks sit " +
         "above 70 for months while still rising. Check whether " +
         "the months after were green HERE before treating 70 as a " +
         "sell trigger.",
    },
    "Any period (baseline)": {
      t: "Baseline — the bar to clear",
      d: "Forward returns from EVERY day in the sample, signal or no " +
         "signal. This is what buying at random got you. Any signal " +
         "block below must beat these numbers to mean anything — " +
         "that's the whole discipline of base rates.",
    },
    "Checklist verdict": {
      t: "Checklist verdict",
      d: "A fixed rule-set graded on this stock: trend, RSI zone, " +
         "valuation sanity, drawdown state. STRONG/MIXED/WEAK is just " +
         "the pass-rate tier — the pros/cons list below it is the " +
         "actual content. Rules are deliberately dumb and consistent: " +
         "same bar for every stock, no story-telling.",
    },
    Median: {
      t: "Median outcome",
      d: "Line up every outcome from worst to best and take the " +
         "middle one — half the times were better, half " +
         "worse.\n\nUsed instead of the average so one freak +900% " +
         "month can't flatter the number. Read it as the realistic " +
         "middle expectation, not the dream case.",
    },
    Positive: {
      t: "Hit rate",
      d: "Out of all the times this happened, the percentage where " +
         "the stock was HIGHER afterwards.\n\n50–55% is coin-flip " +
         "territory. Well below that, together with a negative " +
         "median, means this 'signal' has actually been bad news " +
         "on this stock — whatever the textbook says.",
    },
    Best: {
      t: "Best case seen",
      d: "The single luckiest outcome in the sample. Shown to frame " +
         "the range — never anchor a decision on it; someone always " +
         "wins the lottery.",
    },
    Worst: {
      t: "Worst case seen",
      d: "The most painful outcome in the sample. Your position size " +
         "should survive this repeating — that's what the sizer " +
         "below the checklist is for.",
    },
    __verdict: {
      t: "How this verdict is built",
      d: "A synthesis of four independent checks: checklist tier, " +
         "composite-score rank on your watchlist, trend vs the " +
         "200-DMA, and any active signals weighted by their own " +
         "historical base rates. It never says BUY — its job is to " +
         "put the strongest evidence for AND against in one place. " +
         "Disagreement between the two lists is the interesting part.",
    },
    __sizer: {
      t: "Position sizing",
      d: "shares = (capital × risk%) ÷ (entry − stop). You choose " +
         "how much a failed idea costs BEFORE entering; the formula " +
         "converts that into share count. Risking 1% per idea means " +
         "surviving 20 straight mistakes — sizing, not stock-picking, " +
         "is what keeps accounts alive.",
    },
    /* -------- candle patterns (names come from patterns.py) */
    Doji: {
      t: "Doji",
      d: "One candle = one day of trading: the thick body " +
         "stretches from the day's opening price to its closing " +
         "price. A Doji is a day where the stock closed almost " +
         "exactly where it opened — however much it moved in " +
         "between, buyers and sellers ended in a tie.\n\nChart " +
         "books read that tie as 'indecision — the trend might be " +
         "about to turn'. The numbers beside it are the reality " +
         "check: what this stock actually did in the month after " +
         "each Doji. Seen 200+ times, it's basically an ordinary " +
         "day here — if its numbers match the baseline at the top, " +
         "this shape told you nothing.",
    },
    Hammer: {
      t: "Hammer",
      d: "A day where the price fell a long way during the session " +
         "but climbed back to close near the top. On the chart " +
         "that leaves a thin line (the 'wick') hanging below a " +
         "small body — shaped like a hammer.\n\nThe story: sellers " +
         "pushed hard, buyers won by the close, so maybe the " +
         "decline is ending. The numbers beside it show what this " +
         "stock really did in the month after each hammer. Also " +
         "glance at the count — a shape seen only ~30 times can " +
         "look good or bad by pure luck.",
    },
    "Shooting star": {
      t: "Shooting star",
      d: "The upside-down hammer: price shot UP during the day but " +
         "fell back to close near the bottom, leaving a thin line " +
         "sticking up from a small body.\n\nThe story: buyers " +
         "tried, sellers won — maybe the rise is ending. Now read " +
         "the numbers: if this stock's record shows it mostly ROSE " +
         "in the month after (it often does), then this 'bearish' " +
         "shape simply hasn't worked here. Believe the record, not " +
         "the story.",
    },
    "Bullish engulfing": {
      t: "Bullish engulfing",
      d: "Two days read together: yesterday closed down; today " +
         "closed up by so much that today's candle body completely " +
         "covers yesterday's.\n\nThe story: buyers just " +
         "overpowered the sellers — momentum may be turning up. " +
         "The numbers beside it show what actually followed on " +
         "this stock. If its month-after median is no better than " +
         "the baseline at the top of this panel, the shape added " +
         "nothing.",
    },
    "Bearish engulfing": {
      t: "Bearish engulfing",
      d: "The reverse pair: yesterday closed up; today fell so " +
         "hard that today's candle swallows yesterday's entire " +
         "gain.\n\nThe story: sellers took control — a warning. " +
         "But check this stock's own record first: on stocks in " +
         "long rises, scary red days like this were often just " +
         "pauses, and the month after was still green. That gap " +
         "between the story and the record is exactly what this " +
         "panel exists to show.",
    },
    /* -------- backtest rules table (labels from STRATEGIES) */
    "Golden cross (SMA 50/200)": {
      t: "Golden cross rule",
      d: "In the market while the 50-day average is above the " +
         "200-day, in cash otherwise. Trend-following: exits late, " +
         "enters late, but skips long bear phases. Few trades means " +
         "low costs — and also that its CAGR here rests on a handful " +
         "of decisions, so treat an outperformance as fragile.",
    },
    "200-day filter": {
      t: "200-day filter rule",
      d: "Hold only when price closes above its 200-day average. " +
         "Simplest regime filter there is; most crashes happen below " +
         "the line. More trades than the golden cross = more " +
         "whipsaw cost. Compare its Max fall column against holding — " +
         "drawdown reduction is this rule's real product, not CAGR.",
    },
    "RSI mean reversion (30/60)": {
      t: "RSI mean reversion rule",
      d: "Buys after heavy selling (RSI under 30 on the 0–100 " +
         "pressure gauge), exits once things normalise (past " +
         "60).\n\nIf the table shows a decent win rate but a " +
         "NEGATIVE CAGR, read it as: many small wins, a few huge " +
         "losses — the rule kept buying real declines thinking " +
         "they were panics. That combination is the classic way " +
         "this style fails, and it's visible right in the row.",
    },
    "MACD signal cross (12-26-9)": {
      t: "MACD cross rule",
      d: "Invested while the stock's price momentum is " +
         "accelerating upward (the MACD line above its smoothed " +
         "average), in cash otherwise.\n\nFast and busy: 50+ round " +
         "trips in the Trades column means costs took a real bite. " +
         "A win rate under 40% beside a high CAGR means a few big " +
         "trends paid for many small stop-outs — normal for this " +
         "style, but know that's the deal before following it.",
    },
    "20/10 channel breakout": {
      t: "Channel breakout rule",
      d: "Buys whenever today's close is the highest of the past " +
         "20 days, sells whenever it's the lowest of the past 10 — " +
         "chasing strength, cutting weakness.\n\nA low win rate " +
         "next to a decent CAGR is normal for this style: many " +
         "small losses, paid for by a few big rides. In a stock " +
         "that goes sideways, it mostly donates money to brokerage " +
         "— the Trades column shows how often it paid.",
    },
    "CAGR %": {
      t: "Compound annual growth rate",
      d: "The rule's whole equity curve compressed to one yearly " +
         "growth number, AFTER per-trade costs. Always read it " +
         "against the buy-and-hold CAGR in the header — beating cash " +
         "is easy, beating holding is the actual bar.",
    },
    "Max fall %": {
      t: "Maximum drawdown",
      d: "The deepest peak-to-trough fall you'd have sat through " +
         "following this rule. The psychological price of the CAGR: " +
         "a 70% CAGR with a -49% drawdown was only earned by whoever " +
         "didn't quit at the bottom. Size positions to survive this " +
         "number repeating.",
    },
    Trades: {
      t: "Round trips",
      d: "How many entry+exit pairs the rule generated. Every trade " +
         "pays brokerage twice and slippage always. Under ~10 trades " +
         "the stats are anecdotes; over ~50, verify costs were " +
         "modelled honestly (this backtest charges per side).",
    },
    "Win rate": {
      t: "Win rate",
      d: "Share of trades that closed green. Alone it's a vanity " +
         "metric: trend rules win 35-45% of trades and still " +
         "compound, because winners run and losers are cut. Read it " +
         "WITH CAGR — never rank rules by win rate.",
    },
    "Historical result": {
      t: "Verdict vs holding",
      d: "'Beat holding' means the rule outgrew simply buying and " +
         "keeping the stock, after costs, over this sample. One " +
         "stock, one decade, one result — check the same rule on " +
         "your other stocks before believing an edge exists.",
    },
    "Rule today": {
      t: "Current rule state",
      d: "Whether the rule is invested or in cash RIGHT NOW, and " +
         "since when. If you hold the stock while its best " +
         "historical rule sits in cash, you're implicitly claiming " +
         "you know better — sometimes true, worth saying out loud.",
    },
    /* -------- AI Lab (next-day model) */
    "P(up tomorrow)": {
      t: "Model probability",
      d: "The model's probability that tomorrow closes higher. " +
         "ONLY meaningful if Edge is positive — a confident number " +
         "from a model that failed its test is noise wearing a suit. " +
         "The banner below the cards is the honest verdict.",
    },
    "Test accuracy": {
      t: "Out-of-sample accuracy",
      d: "Accuracy on the most recent ~30% of days the model never " +
         "trained on — the only number that counts. Training " +
         "accuracy is always flattering; unseen-data accuracy is " +
         "where daily-price models routinely collapse to a coin flip.",
    },
    "Naive baseline": {
      t: "The dumb benchmark",
      d: "Accuracy of always guessing the majority class (e.g. " +
         "'always up' in a rising sample). Any model must clear " +
         "THIS, not 50% — a stock that rose 55% of days makes 55% " +
         "the real zero line.",
    },
    Edge: {
      t: "Model edge",
      d: "Test accuracy minus the naive baseline, in points. " +
         "Negative = the model knows less than a constant guess — " +
         "the expected result for next-day prediction from daily " +
         "prices, and the honest lesson this page exists to teach. " +
         "Positive edges under ~3 pts are usually luck; re-train and " +
         "watch them vanish.",
    },
    Score: {
      t: "Composite score",
      d: "Equal-weight blend of the four z-scores. A ranking device, " +
         "NOT a buy list — its job is to push the best 5-10 " +
         "candidates to the top so your research time goes where it " +
         "matters. Always read the AI analyst teardown before " +
         "acting on a high score.",
    },
  };

  /* ---------------------------------------------- tooltip engine */
  let tipEl = null;

  function hideTip() {
    if (tipEl) { tipEl.remove(); tipEl = null; }
  }

  function showTip(anchor, title, body) {
    hideTip();
    tipEl = document.createElement("div");
    tipEl.className = "ifx-tip";
    const h = document.createElement("div");
    h.className = "ifx-tip-t"; h.textContent = title;
    const b = document.createElement("div");
    b.className = "ifx-tip-b"; b.textContent = body;
    tipEl.append(h, b);
    document.body.appendChild(tipEl);
    const r = anchor.getBoundingClientRect();
    const tw = Math.min(340, window.innerWidth - 24);
    tipEl.style.maxWidth = tw + "px";
    const tr = tipEl.getBoundingClientRect();
    let x = Math.min(Math.max(12, r.left + r.width / 2 - tr.width / 2),
                     window.innerWidth - tr.width - 12);
    let y = r.bottom + 8;
    if (y + tr.height > window.innerHeight - 12)
      y = Math.max(12, r.top - tr.height - 8);
    tipEl.style.left = x + "px";
    tipEl.style.top = y + "px";
    requestAnimationFrame(() => tipEl && tipEl.classList.add("on"));
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".ifx-i");
    if (!btn) { hideTip(); return; }
    e.preventDefault(); e.stopPropagation();
    if (tipEl && tipEl.dataset.for === btn.dataset.key) { hideTip(); return; }
    const info = INFO[btn.dataset.key];
    if (info) { showTip(btn, info.t, info.d); tipEl.dataset.for = btn.dataset.key; }
  });
  window.addEventListener("scroll", hideTip, true);
  window.addEventListener("resize", hideTip);

  function makeI(key) {
    const b = document.createElement("button");
    b.className = "ifx-i"; b.type = "button";
    b.dataset.key = key;
    b.setAttribute("aria-label", "What is this?");
    b.textContent = "i";
    return b;
  }

  /* ---------------------------------------------- auto-attachment
     1) Backtest strategy <select>: one "i" that follows selection.
     2) Any table header / element whose trimmed text matches an
        INFO key gets an "i" appended.
     A MutationObserver re-runs on dynamic renders. */
  function enhance(root) {
    const sel = document.getElementById("btStrategy");
    if (sel && !sel.dataset.ifx) {
      sel.dataset.ifx = "1";
      const b = makeI(sel.value || "golden_cross");
      sel.insertAdjacentElement("afterend", b);
      sel.addEventListener("change", () => { b.dataset.key = sel.value; hideTip(); });
    }
    (root.querySelectorAll ? root : document)
      .querySelectorAll("th, .stat .k, .section-label, .chip, " +
                        ".br-title, .metric .k, .ck-tier, td:first-child")
      .forEach((el) => {
        if (el.dataset.ifx) return;
        /* .br-title has trailing chips — match on its first text node */
        const key = (el.classList.contains("br-title")
          ? (el.firstChild && el.firstChild.textContent || "")
          : el.textContent).trim();
        if (INFO[key]) { el.dataset.ifx = "1"; el.appendChild(makeI(key)); }
      });
  }

  const mo = new MutationObserver((muts) => {
    for (const m of muts)
      for (const n of m.addedNodes)
        if (n.nodeType === 1) enhance(n);
  });

  /* ---------------------------------------------- scroll reveal */
  const seen = new WeakSet();
  const io = ("IntersectionObserver" in window) &&
    new IntersectionObserver((entries) => {
      for (const en of entries)
        if (en.isIntersecting) {
          en.target.classList.add("ifx-in");
          io.unobserve(en.target);
        }
    }, { threshold: 0.06 });

  function watchReveals(root) {
    if (!io) return;
    (root.querySelectorAll ? root : document)
      .querySelectorAll(".card, .stat, .page-head, table")
      .forEach((el) => {
        if (seen.has(el)) return;
        seen.add(el);
        el.classList.add("ifx-reveal");
        io.observe(el);
      });
  }

  const mo2 = new MutationObserver((muts) => {
    for (const m of muts)
      for (const n of m.addedNodes)
        if (n.nodeType === 1) watchReveals(n);
  });

  /* ---------------------------------------------- stat count-up */
  function countUp(el) {
    const raw = el.textContent.trim();
    const m = raw.match(/^([₹$]?)(-?[\d,]+(?:\.\d+)?)(%?)$/);
    if (!m) return;
    const target = parseFloat(m[2].replace(/,/g, ""));
    if (!isFinite(target) || Math.abs(target) > 1e9) return;
    const dec = (m[2].split(".")[1] || "").length;
    const t0 = performance.now(), dur = 600;
    function frame(t) {
      const p = Math.min(1, (t - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = m[1] +
        (target * eased).toLocaleString("en-IN",
          { minimumFractionDigits: dec, maximumFractionDigits: dec }) + m[3];
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  const seenStats = new WeakSet();
  const mo3 = new MutationObserver(() => {
    document.querySelectorAll(".stat .v").forEach((el) => {
      if (seenStats.has(el)) return;
      seenStats.add(el); countUp(el);
    });
  });

  /* ---------------------------------------------- lenis (optional) */
  function initLenis() {
    if (!window.Lenis) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    try {
      const lenis = new window.Lenis({
        duration: 0.9, smoothWheel: true,
        /* modals & overlays scroll themselves — Lenis must not eat
           their wheel events (bug: stock popup scrolled the page) */
        prevent: (node) => !!(node.closest && node.closest(
          "#drawer, .dlg-overlay, .ck-overlay, .suggest-box, " +
          "#anaLog, .ifx-tip, .rail")),
      });
      function raf(time) { lenis.raf(time); requestAnimationFrame(raf); }
      requestAnimationFrame(raf);
    } catch (_) { /* cosmetic — never break the app */ }
  }

  /* ---------------------------------------------- boot */
  function boot() {
    enhance(document);
    watchReveals(document);
    /* observe body, not <main>: the stock dialog (#drawer), form
       dialogs, and command palette are all siblings of <main>. */
    mo.observe(document.body, { childList: true, subtree: true });
    mo2.observe(document.body, { childList: true, subtree: true });
    mo3.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll(".stat .v").forEach((el) => {
      seenStats.add(el); countUp(el);
    });
    initLenis();
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
