"""One verdict per IPO: apply for listing gains, consider for the long
term, both, or ignore — with the evidence on each side.

Same philosophy as analysis/verdict.py for stocks: never a bare "BUY".
Two scores are kept apart because they answer different questions:

  listing   how likely is a pop on day one? Driven by demand
            (subscription, grey-market premium), issue size and market mood.
  long_term is this a business worth holding? Driven by valuation (P/E),
            where the money goes (fresh issue vs promoters selling) and
            promoter skin in the game afterwards.

Inputs come from the ipos table. Subscription figures are auto-filled from
NSE while an issue is open; the rest is typed in from the RHP or a news
report. When too little is filled in, the verdict says so instead of
guessing — a confident call on no data is worse than none.
"""
from app.core import database as db

BENCHMARK = "NIFTYBEES.NS"

# What the inputs mean and where to find them. The UI shows this next to
# the empty fields so filling them in is a two-minute job.
INPUT_HELP = {
    "sub_total": "Total subscription (times). NSE shows it while the issue is open.",
    "sub_qib": "QIB subscription (times) — institutions, the smart money.",
    "sub_nii": "NII / HNI subscription (times).",
    "sub_retail": "Retail subscription (times).",
    "gmp_pct": "Grey-market premium as % of the upper band. Unofficial; treat as a mood gauge.",
    "pe": "P/E at the upper band on latest annual profit. From the RHP or a broker note. Leave blank if loss-making and tick 'loss-making' instead (enter -1).",
    "fresh_pct": "Share of the issue that is fresh capital (goes to the company) vs offer for sale (goes to sellers). 0 to 100.",
    "promoter_post": "Promoter holding after the issue, %.",
}


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _issue_size_cr(text, price_high=None):
    """Issue size in crore rupees from the free-text field.
    '1,200 Cr' / '₹450.5 crore' -> as written. '3,779,440 shares' (what
    NSE sends) -> shares x upper band / 1e7, or None without a price.
    A bare large number with no unit is treated as shares too, since no
    Indian IPO is a million crore."""
    import re
    if not text:
        return None
    t = str(text).lower()
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", t)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if "cr" in t:
        return n
    if "lakh" in t or "lac" in t:
        return n / 100
    if "share" in t or n >= 100_000:
        return round(n * price_high / 1e7, 1) if price_high else None
    return n


def market_mood():
    """Is the market above its 200-day average? IPO listings do markedly
    better in uptrends. Uses the app's benchmark ETF when it has data."""
    try:
        closes = db.recent_closes(BENCHMARK, 220)
    except Exception:
        return None
    if len(closes) < 200:
        return None
    last, avg = closes[-1], sum(closes[-200:]) / 200
    return {"above_200": last > avg, "pct_vs_200": (last / avg - 1) * 100}


def assess(row, mood=None):
    """row: a dict from ipos.all_rows(). Returns the verdict card."""
    if row.get("kind") != "ipo":
        return None
    pros, cons, missing = [], [], []
    listing, long_term = 0, 0
    signals = 0                                        # how much we know

    sme = "sme" in str(row.get("detail") or "").lower()
    sub_total = _num(row.get("sub_total"))
    sub_qib = _num(row.get("sub_qib"))
    sub_nii = _num(row.get("sub_nii"))
    sub_retail = _num(row.get("sub_retail"))
    gmp = _num(row.get("gmp_pct"))
    pe = _num(row.get("pe"))
    fresh = _num(row.get("fresh_pct"))
    promoter = _num(row.get("promoter_post"))
    size_cr = _issue_size_cr(row.get("issue_size"), _num(row.get("price_high")))

    # ---------------------------------------------------- listing gains
    demand = sub_total if sub_total is not None else (
        max(x for x in (sub_qib, sub_nii, sub_retail) if x is not None)
        if any(x is not None for x in (sub_qib, sub_nii, sub_retail)) else None)
    if demand is not None:
        signals += 1
        if demand >= 30:
            listing += 3
            pros.append({"text": f"Subscribed {demand:.0f}x — very heavy demand, "
                                 "allotment will be a lottery", "source": "Demand"})
        elif demand >= 10:
            listing += 2
            pros.append({"text": f"Subscribed {demand:.1f}x — strong demand",
                         "source": "Demand"})
        elif demand >= 2:
            listing += 1
            pros.append({"text": f"Subscribed {demand:.1f}x — decent demand",
                         "source": "Demand"})
        elif demand < 1:
            listing -= 3
            cons.append({"text": f"Undersubscribed ({demand:.2f}x) — weak "
                                 "demand, listings like this often open flat "
                                 "or below the band", "source": "Demand"})
        else:
            cons.append({"text": f"Only {demand:.1f}x subscribed — lukewarm",
                         "source": "Demand"})
    else:
        missing.append("sub_total")
    if sub_qib is not None:
        if sub_qib >= 20:
            listing += 1
            pros.append({"text": f"QIBs bid {sub_qib:.0f}x — institutions "
                                 "want it", "source": "Demand"})
        elif sub_qib < 1:
            listing -= 1
            cons.append({"text": f"QIB book only {sub_qib:.2f}x — institutions "
                                 "stayed away", "source": "Demand"})

    if gmp is not None:
        signals += 1
        if gmp >= 25:
            listing += 2
            pros.append({"text": f"Grey-market premium about {gmp:.0f}% — the "
                                 "unofficial market expects a strong opening",
                         "source": "Grey market"})
        elif gmp >= 8:
            listing += 1
            pros.append({"text": f"Grey-market premium about {gmp:.0f}%",
                         "source": "Grey market"})
        elif gmp <= 0:
            listing -= 2
            cons.append({"text": "No grey-market premium (or a discount) — "
                                 "little appetite for a listing pop",
                         "source": "Grey market"})
    else:
        missing.append("gmp_pct")

    if size_cr is not None:
        if size_cr >= 5000:
            listing -= 1
            cons.append({"text": f"Large issue ({size_cr:,.0f} Cr) — big "
                                 "floats rarely pop on day one",
                         "source": "Issue size"})
        elif size_cr <= 500 and demand is not None and demand >= 10:
            listing += 1
            pros.append({"text": "Small float with heavy demand — listing "
                                 "day is often volatile upward",
                         "source": "Issue size"})

    if sme:
        listing -= 1
        cons.append({"text": "SME issue: thin trading after listing, a large "
                             "minimum lot, and swings both ways",
                     "source": "Segment"})

    mood = market_mood() if mood is None else mood
    if mood:
        if mood["above_200"]:
            listing += 1
            pros.append({"text": "Market above its 200-day average — "
                                 "listings do better in uptrends",
                         "source": "Market"})
        else:
            listing -= 1
            cons.append({"text": "Market below its 200-day average — "
                                 "listing gains fade in weak markets",
                         "source": "Market"})

    # --------------------------------------------------------- long term
    if pe is not None:
        signals += 1
        if pe < 0:
            long_term -= 2
            cons.append({"text": "Loss-making at the time of the issue",
                         "source": "Valuation"})
        elif pe <= 25:
            long_term += 2
            pros.append({"text": f"P/E about {pe:.0f}x at the upper band — "
                                 "not demanding", "source": "Valuation"})
        elif pe <= 45:
            long_term += 1
            pros.append({"text": f"P/E about {pe:.0f}x — fair if growth holds",
                         "source": "Valuation"})
        elif pe <= 70:
            long_term -= 1
            cons.append({"text": f"P/E about {pe:.0f}x — priced for a lot of "
                                 "growth", "source": "Valuation"})
        else:
            long_term -= 2
            cons.append({"text": f"P/E about {pe:.0f}x — very expensive; "
                                 "little margin for error", "source": "Valuation"})
    else:
        missing.append("pe")

    if fresh is not None:
        signals += 1
        if fresh >= 70:
            long_term += 1
            pros.append({"text": f"{fresh:.0f}% fresh issue — most of the money "
                                 "goes into the business", "source": "Use of funds"})
        elif fresh <= 30:
            long_term -= 1
            cons.append({"text": f"Only {fresh:.0f}% fresh issue — mostly "
                                 "existing holders cashing out",
                         "source": "Use of funds"})
    else:
        missing.append("fresh_pct")

    if promoter is not None:
        signals += 1
        if promoter >= 50:
            long_term += 1
            pros.append({"text": f"Promoters keep {promoter:.0f}% after the "
                                 "issue — skin in the game", "source": "Ownership"})
        elif promoter < 30:
            long_term -= 1
            cons.append({"text": f"Promoters hold only {promoter:.0f}% after "
                                 "the issue", "source": "Ownership"})
    else:
        missing.append("promoter_post")

    if sme:
        long_term -= 1

    # ------------------------------------------------------------ verdict
    have_listing = demand is not None or gmp is not None
    have_long = any(x is not None for x in (pe, fresh, promoter))
    if signals == 0:
        tier, label = "unknown", "Needs inputs"
        summary = ("Nothing to judge yet. Fill in subscription, GMP or "
                   "valuation figures and the verdict updates.")
    else:
        good_listing = have_listing and listing >= 4
        good_long = have_long and long_term >= 2
        bad_listing = have_listing and listing <= -1
        bad_long = have_long and long_term <= -2
        if good_listing and good_long:
            tier, label = "both", "Listing gains and long term"
            summary = ("Demand points to a strong opening and the business "
                       "case reads well too. Apply, and decide on listing "
                       "day whether to keep it.")
        elif good_listing:
            tier, label = "listing", "Listing gains"
            summary = ("Demand points to a strong opening. The long-term "
                       "case is " + ("unclear — sell on listing unless the "
                                     "numbers below change your mind."
                                     if not have_long else
                                     "unconvincing — treat it as a listing "
                                     "trade, not a holding."))
        elif good_long:
            tier, label = "longterm", "Long term"
            if bad_listing:
                summary = ("The business case reads well but demand is weak, "
                           "so the listing may be flat or below the band. No "
                           "rush — it may be cheaper after listing.")
            else:
                summary = ("Sensibly priced with money going into the "
                           "business. Listing-day demand is "
                           + ("unknown — apply for the business, not the pop."
                              if not have_listing else
                              "modest, so don't expect a pop; hold if "
                              "allotted."))
        elif bad_listing or bad_long:
            tier, label = "ignore", "Ignore"
            summary = ("The case against outweighs the case for. Let it list "
                       "and revisit once there is a price history.")
        else:
            tier, label = "mixed", "Wait and see"
            summary = ("Evidence is mixed. There is no penalty for skipping "
                       "an IPO — it can be bought after listing.")
    return {
        "tier": tier, "label": label, "summary": summary,
        "listing_score": listing, "long_term_score": long_term,
        "for": pros[:4], "against": cons[:4],
        "missing": missing, "help": {k: INPUT_HELP[k] for k in missing},
        "note": "A synthesis of the numbers entered — read the evidence, not "
                "just the label. Allotment is not guaranteed. Not investment "
                "advice.",
    }
