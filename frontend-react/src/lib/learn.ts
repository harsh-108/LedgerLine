// Content for the Learn page: short guides, then a glossary grouped by topic.
// Plain words, no advice. Tax figures follow the rules in force since the
// July 2024 budget; the guide says so and points to the source of truth.

export interface Guide { id: string; title: string; minutes: number; summary: string; body: string[]; link?: { to: string; label: string } }
export interface Term { term: string; cat: Cat; def: string }
export type Cat = "Market basics" | "Charts and signals" | "Company numbers" | "Research tools" | "Mutual funds" | "Portfolio and tax";
export const CATS: Cat[] = ["Market basics", "Charts and signals", "Company numbers", "Research tools", "Mutual funds", "Portfolio and tax"];

export const GUIDES: Guide[] = [
  {
    id: "start", title: "Start here: what each part of the app does", minutes: 3,
    summary: "A quick tour, so you know where to go for what.",
    body: [
      "Watchlists hold the stocks, ETFs and funds you follow. Almost every other page works from this list, so add what you care about first.",
      "A stock's page shows its chart, the verdict card (the app's summary of the evidence for and against), the research checklist, and how this stock behaved after past signals (base rates).",
      "Screener finds stocks that match rules, like \"P/E under 20 and ROE over 15\". You can type the rule in plain English.",
      "Research has four parts. AI Lab ranks your watchlist on momentum, value, quality and trend, and runs a next-day model that teaches you how hard prediction is. Backtest replays a simple trading rule on a stock's history, costs included. Scorecard grades the app's own calls once their time is up. Journal lists every signal the app raised.",
      "Analyst is a chat that reads your stored data and the filings you upload, and shows which tools it used for each answer.",
      "Portfolio tracks what you own, your profit and loss, and how you compare with simply holding NIFTYBEES.",
    ],
  },
  {
    id: "exchanges", title: "NSE, BSE and the .NS / .BO endings", minutes: 2,
    summary: "Why the same company can show up twice, and which one to keep.",
    body: [
      "India has two main stock exchanges: the National Stock Exchange (NSE) and the Bombay Stock Exchange (BSE). Most large companies are listed on both, and the price is almost the same on each, because traders close any gap within seconds.",
      "The data source marks the exchange with an ending: RELIANCE.NS is Reliance on the NSE, RELIANCE.BO is Reliance on the BSE. The app shows this as an NSE or BSE tag next to the name.",
      "Keep one listing per company. NSE usually trades far more shares, so its price history tends to be more complete. If a stock shows very few days of prices, the Data doctor (Data and admin) can switch it to the other exchange or remove the extra copy.",
    ],
  },
  {
    id: "backtest", title: "Reading a backtest honestly", minutes: 4,
    summary: "What a backtest can tell you, what it cannot, and the three numbers to read together.",
    body: [
      "A backtest replays a fixed rule on past prices: for example, \"own the stock while its 50-day average is above its 200-day average\". The app decides each day using only what was known that day, then charges a cost on every buy and sell.",
      "Read three numbers together. CAGR is the yearly growth rate. Max fall is the worst drop from a peak you would have sat through. Win rate is the share of trades that made money. A rule with a lower CAGR than holding can still be useful if it cut the worst fall in half; a rule with a high win rate can still lose money if its few losses were large.",
      "Cost per side matters. Every buy and every sell costs brokerage, taxes and slippage. A rule that trades often can look great at 0% cost and lose to holding at a realistic 0.2%.",
      "One stock and one decade is a small sample. Before believing a rule has an edge, run Compare all, then try the same rule on your other stocks. An edge that shows up on one stock only is usually luck.",
      "\"What the rule says now\" tells you whether the rule would own the stock today. It is a fact about the rule, not advice. You can put that call on the Scorecard to see whether it turns out right.",
    ],
    link: { to: "/research/backtest", label: "Open Backtest" },
  },
  {
    id: "scorecard", title: "How the Scorecard grades the app", minutes: 3,
    summary: "Calls are written down with that day's price and checked later. Nothing can be edited.",
    body: [
      "Every time the app makes a call on a stock, it writes it down with that day's price: the verdict card (strong, mixed or weak), the checklist tier, the next-day model's up or down, and any backtest rule you add.",
      "Each call has a horizon. Verdicts and checklist tiers are checked after 30 and 90 days, next-day predictions after one trading day, and backtest rules after the tracking period you choose.",
      "A strong, up or holding call is right if the stock rose over its horizon; a weak, down or out call is right if it fell. Mixed calls make no claim, so they are kept but not scored. Each graded call is also compared with NIFTYBEES over the same days.",
      "Each account has its own Scorecard: the calls on stocks you opened or tracked, and nobody else's. Tracking keeps the record filling up. Every tracked stock gets its verdict and checklist written down each day after the data refresh, for the tracking period you pick. You can add stocks by hand, from your watchlist or portfolio, or straight from a backtest, the next-day model or the analyst.",
    ],
    link: { to: "/research/scorecard", label: "Open Scorecard" },
  },
  {
    id: "nextday", title: "Why next-day prediction is close to a coin flip", minutes: 2,
    summary: "The AI Lab model exists to show this, honestly.",
    body: [
      "Tomorrow's move is mostly driven by news nobody has seen yet. Patterns in past daily prices explain very little of it, and whatever they do explain gets traded away quickly by professionals.",
      "So the model is tested on the most recent 30% of days it never saw. Compare its test accuracy with the naive baseline: always guessing the more common outcome. If the stock rose on 54% of days, \"always up\" scores 54%, and that is the bar to clear, not 50%.",
      "Edge is test accuracy minus that baseline. Most stocks show an edge near zero or below. A small positive edge is usually luck and disappears when you re-train. That is the lesson: be wary of anyone selling short-term price predictions.",
    ],
    link: { to: "/research/ai-lab", label: "Open AI Lab" },
  },
  {
    id: "funds", title: "Mutual funds in five minutes", minutes: 4,
    summary: "Direct or regular, growth or IDCW, and what the expense ratio costs you.",
    body: [
      "A mutual fund pools money from many investors and invests it for them. Its price per unit is the NAV, calculated once a day after the market closes.",
      "Direct plans are bought straight from the fund house; regular plans pay a commission to a distributor, so their expense ratio is higher. The portfolio is identical, so a direct plan simply keeps more of the return.",
      "Growth plans reinvest the profits, so the NAV rises. IDCW plans (once called dividend plans) pay some out now and then, and those payouts are taxed as income.",
      "The expense ratio is the yearly fee, taken out of the NAV daily. A 1% difference sounds small but compounds: over 20 years it can cost a sixth or more of the final amount.",
      "A SIP invests a fixed amount every month. It does not raise returns by itself, but it spreads your buying over time and makes the habit automatic. Judge funds on rolling returns over many periods, not on last year's number.",
    ],
    link: { to: "/funds", label: "Open Mutual Funds" },
  },
  {
    id: "costs", title: "Costs and taxes on a share trade", minutes: 3,
    summary: "What you pay on each trade, and how gains are taxed.",
    body: [
      "Each delivery trade (you keep the shares overnight or longer) pays brokerage, Securities Transaction Tax (0.1% on both the buy and the sell), exchange and SEBI fees, stamp duty on the buy, and GST on the fees. Slippage, the gap between the price you saw and the price you got, comes on top.",
      "Gains on listed shares and equity funds held for 12 months or less are short-term capital gains, taxed at 20%. Held longer, they are long-term capital gains, taxed at 12.5% on gains above 1.25 lakh rupees in a year. These are the rates since the July 2024 budget.",
      "Dividends are added to your income and taxed at your slab rate.",
      "Tax rules change. Treat this as background and check the current rules, or ask a tax adviser, before acting. Reports under More lists your realised gains to help.",
    ],
    link: { to: "/more/reports", label: "Open Reports" },
  },
];

export const TERMS: Term[] = [
  // Market basics
  { term: "NSE and BSE", cat: "Market basics", def: "India's two main stock exchanges. Most large companies list on both at almost the same price. In this app, .NS means NSE and .BO means BSE." },
  { term: "Ticker", cat: "Market basics", def: "The short code a stock trades under, like TCS or HDFCBANK." },
  { term: "Nifty 50", cat: "Market basics", def: "An index of 50 large companies on the NSE. The usual yardstick for the Indian market." },
  { term: "Sensex", cat: "Market basics", def: "An index of 30 large companies on the BSE." },
  { term: "ETF", cat: "Market basics", def: "Exchange-traded fund: a fund you buy and sell on the exchange like a share. NIFTYBEES, for example, tracks the Nifty 50." },
  { term: "Market cap", cat: "Market basics", def: "What the whole company is worth at today's share price: price times the number of shares." },
  { term: "Large, mid and small cap", cat: "Market basics", def: "SEBI's size groups. The 100 biggest listed companies by market cap are large caps, the next 150 are mid caps, the rest are small caps." },
  { term: "Delivery trade", cat: "Market basics", def: "Buying shares and keeping them past the end of the day, as opposed to an intraday trade that is closed the same day." },
  { term: "T+1 settlement", cat: "Market basics", def: "Shares and money change hands one trading day after the trade." },
  { term: "Circuit limit", cat: "Market basics", def: "The most a stock's price may move in one day. When it hits the limit, trading in it pauses or only one side can trade." },
  { term: "STT", cat: "Market basics", def: "Securities Transaction Tax, charged on share trades. On delivery trades it is 0.1% on the buy and 0.1% on the sell." },
  { term: "Slippage", cat: "Market basics", def: "The gap between the price you expected and the price you actually got. Larger in thinly traded stocks." },
  { term: "Volume", cat: "Market basics", def: "How many shares changed hands in a period. A big move on high volume is taken more seriously than one on low volume." },
  { term: "52-week high and low", cat: "Market basics", def: "The highest and lowest price of the last year." },
  { term: "Dividend", cat: "Market basics", def: "Cash a company pays to its shareholders out of profit. You get it if you own the shares before the ex-date." },
  { term: "Ex-date", cat: "Market basics", def: "From this day, a buyer no longer gets the declared dividend or bonus. The price usually drops by about the dividend amount." },
  { term: "Bonus and split", cat: "Market basics", def: "Both give you more shares at a lower price each; what you own is worth the same. Charts adjust past prices so the history stays comparable." },
  { term: "IPO", cat: "Market basics", def: "Initial public offering: a company selling shares to the public for the first time." },

  // Charts and signals
  { term: "Candlestick", cat: "Charts and signals", def: "One bar per day showing the open, high, low and close. A filled or red body means it closed lower than it opened." },
  { term: "Moving average", cat: "Charts and signals", def: "The average closing price of the last N days, recalculated each day. The 50-day and 200-day are the common ones." },
  { term: "Golden cross", cat: "Charts and signals", def: "The 50-day average rising above the 200-day average. Often read as the start of an uptrend." },
  { term: "Death cross", cat: "Charts and signals", def: "The 50-day average falling below the 200-day average. Often read as the start of a downtrend; the stock's own history may say otherwise." },
  { term: "RSI", cat: "Charts and signals", def: "A 0 to 100 gauge of recent buying and selling pressure over 14 days. Under 30 is called oversold, over 70 overbought." },
  { term: "MACD", cat: "Charts and signals", def: "Compares a fast and a slow average of price. When its line crosses above its signal line, momentum is picking up." },
  { term: "Breakout", cat: "Charts and signals", def: "A close above the highest price of a recent period, such as 20 days." },
  { term: "Volatility", cat: "Charts and signals", def: "How much the price swings from day to day. Higher volatility means bigger moves both ways." },
  { term: "Drawdown", cat: "Charts and signals", def: "How far the price is below its previous peak. The worst one in a period is the max drawdown." },
  { term: "Delivery %", cat: "Charts and signals", def: "The share of the day's traded shares that buyers actually kept, rather than trading in and out the same day." },
  { term: "Put-call ratio", cat: "Charts and signals", def: "Open interest in put options divided by call options. A rough read of market mood." },
  { term: "Candle patterns", cat: "Charts and signals", def: "Shapes like the hammer or engulfing candle that are said to hint at a turn. The stock page shows how this stock actually did after each one." },

  // Company numbers
  { term: "EPS", cat: "Company numbers", def: "Earnings per share: the year's profit divided by the number of shares." },
  { term: "P/E ratio", cat: "Company numbers", def: "Share price divided by earnings per share. How many years of today's profit you pay for. Compare within the same industry." },
  { term: "P/B ratio", cat: "Company numbers", def: "Share price divided by book value per share. Most useful for banks and financial companies." },
  { term: "Book value", cat: "Company numbers", def: "What the company owns minus what it owes, as per its accounts." },
  { term: "ROE", cat: "Company numbers", def: "Return on equity: profit earned on shareholders' money in a year. Higher means the business uses capital well." },
  { term: "ROCE", cat: "Company numbers", def: "Return on capital employed: profit on all the money in the business, borrowed and owned. Useful for companies with a lot of debt." },
  { term: "Debt to equity", cat: "Company numbers", def: "Borrowed money for every rupee of shareholders' money. Above about 1 for a non-financial company deserves a closer look." },
  { term: "Operating margin", cat: "Company numbers", def: "Profit from the core business as a share of sales, before interest and tax." },
  { term: "Dividend yield", cat: "Company numbers", def: "Yearly dividend as a percentage of the share price." },
  { term: "Beta", cat: "Company numbers", def: "How much the stock moves when the market moves. 1.5 means it tends to swing half as much again as the index." },
  { term: "Promoter holding", cat: "Company numbers", def: "The share of the company owned by its founders or controlling group." },
  { term: "Pledged shares", cat: "Company numbers", def: "Promoter shares given as security for a loan. A high or rising pledge is a risk sign: lenders may sell if the price falls." },
  { term: "FII and DII", cat: "Company numbers", def: "Foreign and domestic institutional investors, such as overseas funds and Indian mutual funds or insurers." },

  // Research tools
  { term: "Verdict card", cat: "Research tools", def: "The app's summary of the evidence for and against a stock: strong, mixed or weak. It is graded on the Scorecard." },
  { term: "Checklist tier", cat: "Research tools", def: "How many of a fixed set of checks a stock passes (trend, RSI zone, valuation, drawdown), grouped into strong, mixed or weak." },
  { term: "Base rate", cat: "Research tools", def: "How often something happened in the past. Here: how this stock did after a signal, across its own history." },
  { term: "z-score", cat: "Research tools", def: "How far a value sits from the group average, in standard deviations. 0 is average, +1 is clearly above, -1 clearly below." },
  { term: "Factor score", cat: "Research tools", def: "AI Lab's blend of momentum, value, quality and trend z-scores, used to rank your watchlist. A ranking, not a forecast." },
  { term: "Backtest", cat: "Research tools", def: "Replaying a fixed trading rule on past prices to see how it would have done, costs included." },
  { term: "Buy and hold", cat: "Research tools", def: "Buying once and never selling. The bar every trading rule has to beat." },
  { term: "CAGR", cat: "Research tools", def: "Compound annual growth rate: the steady yearly rate that turns the starting value into the ending value." },
  { term: "Max drawdown", cat: "Research tools", def: "The biggest fall from a peak to a later low. Called Max fall in the backtest." },
  { term: "Win rate", cat: "Research tools", def: "The share of trades that made money. Never judge a rule on this alone; read it with CAGR." },
  { term: "Cost per side", cat: "Research tools", def: "The trading cost charged once on each buy and once on each sell, as a % of the amount. 0.15 to 0.25 is realistic for Indian delivery trades." },
  { term: "Look-ahead bias", cat: "Research tools", def: "A backtest mistake: using information that was not known on the day of the decision. This app trades the day after a signal to avoid it." },
  { term: "Overfitting", cat: "Research tools", def: "Tuning a rule until it fits the past perfectly. It then usually fails on new data." },
  { term: "Survivorship bias", cat: "Research tools", def: "Testing only on companies that still exist today, which leaves out the ones that failed and flatters the results." },
  { term: "Test accuracy", cat: "Research tools", def: "How often the next-day model was right on days it never trained on. The only accuracy that counts." },
  { term: "Naive baseline", cat: "Research tools", def: "The accuracy of always guessing the more common outcome. Any model has to beat this, not 50%." },
  { term: "Edge", cat: "Research tools", def: "Test accuracy minus the naive baseline. Near zero or negative is normal for next-day prediction." },
  { term: "Scorecard horizon", cat: "Research tools", def: "How long after a call it is graded: 1 trading day for next-day predictions, 30 and 90 days for verdicts and checklist tiers, your chosen period for backtest rules." },
  { term: "Tracking period", cat: "Research tools", def: "How long the Scorecard writes down a stock's verdict and checklist each day. When it ends, recorded calls stay and are still graded." },

  // Mutual funds
  { term: "NAV", cat: "Mutual funds", def: "Net asset value: the price of one unit of a fund, set once a day after the market closes." },
  { term: "Expense ratio", cat: "Mutual funds", def: "The yearly fee a fund takes, as a percentage of your money. Deducted from the NAV every day." },
  { term: "Direct and regular plans", cat: "Mutual funds", def: "Same fund, same holdings. Regular plans pay a distributor commission, so their expense ratio is higher." },
  { term: "Growth and IDCW", cat: "Mutual funds", def: "Growth plans reinvest profits. IDCW plans pay some out from time to time, and those payouts are taxed as income." },
  { term: "SIP", cat: "Mutual funds", def: "Systematic investment plan: investing a fixed amount in a fund every month, automatically." },
  { term: "Lump sum", cat: "Mutual funds", def: "Investing a large amount in one go rather than spreading it out." },
  { term: "Exit load", cat: "Mutual funds", def: "A fee for selling units within a set time, often 1% within a year for equity funds." },
  { term: "AUM", cat: "Mutual funds", def: "Assets under management: the total money a fund manages." },
  { term: "Index fund", cat: "Mutual funds", def: "A fund that simply copies an index such as the Nifty 50. Low fees, no stock picking." },
  { term: "Tracking error", cat: "Mutual funds", def: "How far an index fund's return drifts from its index. Lower is better." },
  { term: "ELSS", cat: "Mutual funds", def: "Equity-linked savings scheme: an equity fund with a 3-year lock-in that qualifies for a tax deduction under the old tax regime." },
  { term: "Rolling return", cat: "Mutual funds", def: "The return over every possible period of a set length (say every 3-year stretch), not just the latest one. Shows how steady a fund has been." },

  // Portfolio and tax
  { term: "Absolute return", cat: "Portfolio and tax", def: "Total gain as a percentage of what you put in, ignoring how long it took." },
  { term: "XIRR", cat: "Portfolio and tax", def: "Your yearly return when money went in and out at different times, as with a SIP." },
  { term: "Asset allocation", cat: "Portfolio and tax", def: "How your money is split between shares, funds, gold, debt and cash. Drives most of your risk." },
  { term: "Rebalancing", cat: "Portfolio and tax", def: "Selling some of what grew and buying what lagged, to get back to your target split." },
  { term: "Diversification", cat: "Portfolio and tax", def: "Spreading money across companies and sectors so one bad outcome does not sink the whole portfolio." },
  { term: "Position sizing", cat: "Portfolio and tax", def: "Deciding how much to put in one stock, usually from how much you are willing to lose if it goes wrong." },
  { term: "STCG", cat: "Portfolio and tax", def: "Short-term capital gains: profit on listed shares or equity funds held 12 months or less. Taxed at 20% since July 2024." },
  { term: "LTCG", cat: "Portfolio and tax", def: "Long-term capital gains: profit on listed shares or equity funds held over 12 months. Taxed at 12.5% on gains above 1.25 lakh rupees a year, since July 2024." },
  { term: "Tax-loss harvesting", cat: "Portfolio and tax", def: "Selling a loss-making holding to set the loss against gains and lower the tax bill." },
  { term: "Benchmark", cat: "Portfolio and tax", def: "What you compare your returns with. This app uses NIFTYBEES, a Nifty 50 index fund." },
];
