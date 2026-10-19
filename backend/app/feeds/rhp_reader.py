"""Read the numbers the IPO verdict needs out of the RHP (red herring
prospectus) PDF, using the same LLM chain as the analyst.

Why a model and not regexes: every RHP is laid out differently, the
figures sit in prose ("...at the upper end of the Price Band, the P/E
multiple is 32.4 times...") and tables that extract as ragged text. What
is stable is the *vocabulary* — so we score pages by keyword, hand the
best few to the model with a strict JSON contract, and sanity-check the
answer. The user sees what was read and can correct any field.

Nothing here runs unless the admin presses "Read the RHP". A 500-page
PDF is downloaded once, never stored.
"""
import io
import json
import re

import requests

from app.core import llm

MAX_BYTES = 60 * 1024 * 1024
PAGE_CHARS = 2600          # per page handed to the model
MAX_PAGES = 7

# (keyword, weight). Pages that score highest across these are the ones
# with the offer structure, the valuation and the promoter holding.
KEYWORDS = [
    ("basis for offer price", 6), ("basis for the offer price", 6),
    ("price/earnings", 4), ("p/e ratio", 4), ("p/e", 2), ("earnings per share", 3),
    ("diluted eps", 3), ("fresh issue", 3), ("offer for sale", 3),
    ("the offer comprises", 4), ("offer size", 2), ("aggregating up to", 2),
    ("post-offer", 3), ("post offer", 3), ("promoter and promoter group", 3),
    ("promoters' shareholding", 3), ("promoter holding", 3),
    ("shareholding pattern", 2), ("price band", 2), ("upper end", 2),
    ("summary of the offer", 3), ("key performance indicators", 1),
]

PROMPT = """You extract facts from an Indian IPO prospectus (RHP). Using ONLY the
excerpts below, reply with JSON and nothing else, in exactly this shape:
{"company": "name or null",
 "price_high": upper end of the price band in rupees, or null,
 "pe_at_upper_band": P/E at the upper end of the band as stated, or null,
 "diluted_eps": latest full-year diluted EPS in rupees (negative if a loss), or null,
 "fresh_issue_cr": fresh issue size in crore rupees, or null,
 "ofs_cr": offer-for-sale size in crore rupees (0 if none), or null,
 "total_issue_cr": total offer size in crore rupees, or null,
 "promoter_post_pct": promoter and promoter group holding after the offer, in percent, or null,
 "loss_making": true if the latest full year shows a loss, else false,
 "source_lines": ["one short quote per number you filled, copied from the excerpts"]}
Rules: numbers only, no units, no ranges (use the upper end). If a figure
is not in the excerpts, use null — never guess. Convert lakh to crore
(divide by 100) and plain rupees to crore (divide by 1e7). Percentages as
plain numbers (61.2 not "61.2%").

EXCERPTS:
"""


def _download(url):
    r = requests.get(url, timeout=60, stream=True,
                     headers={"User-Agent": "Mozilla/5.0 (Ledgerline RHP reader)"})
    r.raise_for_status()
    buf, n = io.BytesIO(), 0
    for chunk in r.iter_content(65536):
        n += len(chunk)
        if n > MAX_BYTES:
            raise RuntimeError("PDF is over 60 MB — too large to read here.")
        buf.write(chunk)
    data = buf.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("That link did not return a PDF. Paste the direct "
                           "link to the RHP file (it usually ends in .pdf).")
    return data


def _pages(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pip install pypdf (needed to read the RHP), then restart.")
    reader = PdfReader(io.BytesIO(data))
    out = []
    for i, p in enumerate(reader.pages):
        try:
            out.append((i + 1, p.extract_text() or ""))
        except Exception:
            out.append((i + 1, ""))
    return out


def pick_pages(pages):
    """Score every page by keyword hits; return the best few in document
    order, each trimmed. Pure function so it can be tested without a PDF."""
    scored = []
    for no, text in pages:
        low = text.lower()
        if len(low) < 200:
            continue
        score = sum(w * min(low.count(k), 3) for k, w in KEYWORDS)
        # an actual number next to "P/E" or "%" is what we're after
        if re.search(r"p/e[^\n]{0,40}\d", low):
            score += 4
        if score:
            scored.append((score, no, text))
    scored.sort(key=lambda x: -x[0])
    best = sorted(scored[:MAX_PAGES], key=lambda x: x[1])
    return [(no, text[:PAGE_CHARS]) for _s, no, text in best]


def _parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def derive_inputs(found, price_high=None):
    """Turn the model's JSON into verdict inputs, with the arithmetic and
    sanity checks done here rather than trusted from the model.
    Returns (inputs_dict, human_note)."""
    out, notes = {}, []
    hi = _num(found.get("price_high")) or price_high
    pe = _num(found.get("pe_at_upper_band"))
    eps = _num(found.get("diluted_eps"))
    if found.get("loss_making") or (eps is not None and eps < 0):
        out["pe"] = -1
        notes.append("loss-making in the latest full year")
    elif pe and 0 < pe < 1000:
        out["pe"] = round(pe, 1)
        notes.append(f"P/E {pe:.1f}x at the upper band")
    elif eps and hi and eps > 0:
        out["pe"] = round(hi / eps, 1)
        notes.append(f"P/E {hi / eps:.1f}x from EPS ₹{eps:.2f} at ₹{hi:.0f}")
    fresh, ofs = _num(found.get("fresh_issue_cr")), _num(found.get("ofs_cr"))
    total = _num(found.get("total_issue_cr"))
    if fresh is not None and (ofs is not None or total):
        denom = (fresh + ofs) if ofs is not None else total
        if denom and denom > 0 and 0 <= fresh <= denom * 1.001:
            out["fresh_pct"] = round(min(100.0, fresh / denom * 100), 1)
            notes.append(f"fresh issue {out['fresh_pct']:.0f}% of "
                         f"₹{denom:,.0f} Cr")
    if total and total > 0:
        out["issue_size"] = f"{total:,.0f} Cr"
    elif fresh is not None and ofs is not None and fresh + ofs > 0:
        out["issue_size"] = f"{fresh + ofs:,.0f} Cr"
    prom = _num(found.get("promoter_post_pct"))
    if prom is not None and 0 <= prom <= 100:
        out["promoter_post"] = round(prom, 1)
        notes.append(f"promoters {prom:.1f}% after the offer")
    if hi and not price_high:
        out["price_high"] = hi
    return out, ("Read from the RHP: " + "; ".join(notes) + "."
                 if notes else "Read the RHP but found none of the figures "
                               "— the excerpts may not cover them. Enter "
                               "them by hand.")


def read(url, price_high=None):
    """Download, pick pages, ask the model. Returns (inputs, note)."""
    if not llm.available():
        raise RuntimeError(llm.setup_hint())
    pages = pick_pages(_pages(_download(url)))
    if not pages:
        raise RuntimeError("No page in that PDF mentions the offer price, "
                           "P/E or promoter holding. Is it the RHP, or a "
                           "notice / form?")
    excerpts = "\n\n".join(f"--- page {no} ---\n{t}" for no, t in pages)
    # room for reasoning models' thinking (it counts against max_tokens)
    msg, _provider = llm.complete(
        [{"role": "user", "content": PROMPT + excerpts}],
        temperature=0.0, max_tokens=2048)
    if msg.get("finish_reason") == "length":
        raise RuntimeError("The model's answer was cut off before it "
                           "finished. Try again, or enter the figures by hand.")
    found = _parse_json(msg.get("content") or "")
    if not found:
        raise RuntimeError("The model did not return usable JSON. Try again, "
                           "or enter the figures by hand.")
    inputs, note = derive_inputs(found, price_high)
    quotes = [q for q in (found.get("source_lines") or []) if isinstance(q, str)][:4]
    if quotes:
        note += " Quoted: " + " | ".join(q[:120] for q in quotes)
    return inputs, note[:900]
