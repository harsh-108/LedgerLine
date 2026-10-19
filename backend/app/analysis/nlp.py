"""
Natural-language screener queries via the shared LLM chain
(app.core.llm: OpenRouter -> Groq -> Gemini, whichever keys are set).

The LLM's ONLY job is translating an English sentence into the app's own
query language; the whitelist parser in query_engine then validates and
executes it. The model never sees your data and cannot invent results —
worst case it writes an invalid query and you get a clear error.
"""

from app.core import llm
from app.analysis import query_engine as qe

_SYSTEM = """You translate English requests about stocks into a strict query language. Output ONLY the query, no explanation, no quotes.

Fields (numeric): mcap (market cap in ₹ crore), pe, pb, roe (%), margin (%), divyield (%), de (debt/equity), eps, beta, close, rsi, ret1m, ret6m, ret1y (returns in %)
Fields (text): trend (up/down), sector, name. Sector matching is SUBSTRING-based against Yahoo's sector+industry strings, so use words that appear in that taxonomy: technology, financial, bank, insurance, energy, oil, utilities, healthcare, pharmaceutical, materials, chemicals, steel, metals, gold, mining, auto, consumer, retail, beverages, tobacco, cement, construction, industrials, telecom, real estate, transportation. Prefer the specific industry word the user implies ("gold stocks" -> gold, "steel makers" -> steel) over broad buckets.
Operators: > < >= <= = != ; combine with and/or; optional: sort by FIELD asc|desc ; top N

Examples:
"cheap stocks with good returns on equity" -> pe < 20 and roe > 15
"IT companies that fell this month but are in an uptrend" -> sector = information technology and ret1m < 0 and trend = up
"5 biggest dividend payers" -> divyield > 0 sort by divyield desc top 5
"banks under book value" -> sector = bank and pb < 1
"safe large companies, not overbought" -> mcap > 100000 and de < 100 and rsi < 70

If the request is not about screening stocks, output exactly: NOT_A_QUERY"""


def available():
    return llm.available()


def translate(text, timeout=20):
    """English -> query string. Returns (query|None, error|None)."""
    # the user's own words reach a model here too: same gate as the
    # analyst chat, checked before any AI call
    from app.analyst import injection_guard
    verdict = injection_guard.check(text)
    if verdict.blocked:
        return None, verdict.block_message
    if not llm.available():
        return None, llm.setup_hint()
    try:
        # 1024, not 120: reasoning models think before answering and the
        # thinking counts against max_tokens. At 120 the query came back
        # cut off ("sector = technology" with "and mcap > 2000" missing).
        msg, _provider = llm.complete(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": text.strip()}],
            tools=None, temperature=0, max_tokens=1024, timeout=timeout)
        query = (msg.get("content") or "").strip()
    except Exception as e:
        return None, f"LLM unavailable: {e}"
    if msg.get("finish_reason") == "length":
        # never run half a query: a dropped condition silently widens it
        return None, ("The AI's translation was cut off before it finished, "
                      "so nothing was run. Please try again, or shorten the "
                      "request.")

    query = query.strip("`\"' \n")
    if query == "NOT_A_QUERY" or not query:
        return None, ("That doesn't look like a screening request — try "
                      "something like 'cheap IT stocks in an uptrend'.")
    return query, None


def ask(text, metrics=None):
    """Full pipeline: translate, then validate+run through the safe parser.
    Returns (result_df|None, generated_query|None, error|None)."""
    query, err = translate(text)
    if err:
        return None, None, err
    try:
        result, _expl, _diag = qe.run_query(query, metrics)
        return result, query, None
    except qe.QueryError as e:
        return None, query, (f"The model wrote an invalid query "
                             f"('{query}'): {e}")