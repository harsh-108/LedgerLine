"""News feed from free sources: RSS / Atom feeds you choose, plus a Google
News search per watchlist stock.

What is stored is the headline, the publisher's short excerpt, the link and
the time. The full article stays with the publisher and opens there. An
optional plain-language summary comes from the app's own LLM chain and is
cached per article.

No new dependencies: requests + the standard library XML parser.
"""
import datetime as dt
import html
import json
import re
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from app.core import database as db

UA = {"User-Agent": "Mozilla/5.0 (personal research app; RSS reader)"}
GOOGLE_NEWS = ("https://news.google.com/rss/search?q={q}"
               "&hl=en-IN&gl=IN&ceid=IN:en")
DEFAULT_FEEDS = [
    ("Indian markets (Google News)",
     GOOGLE_NEWS.format(q=urllib.parse.quote("Indian stock market Nifty Sensex"))),
    ("Mutual funds (Google News)",
     GOOGLE_NEWS.format(q=urllib.parse.quote("mutual fund India SIP NAV"))),
]
KEEP_DAYS = 30
PER_STOCK_LIMIT = 25        # Google News queries per refresh, newest first
STATE = {"running": False, "log": [], "done": False}
_lock = threading.Lock()


# ------------------------------------------------------------------ storage
def ensure_tables():
    with db.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            url       TEXT UNIQUE NOT NULL,
            title     TEXT NOT NULL,
            excerpt   TEXT,
            source    TEXT,
            published TEXT,
            symbols   TEXT NOT NULL DEFAULT '[]',
            summary   TEXT,
            why       TEXT,
            fetched   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published);
        CREATE TABLE IF NOT EXISTS news_feeds (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT NOT NULL,
            url    TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        """)
        if conn.execute("SELECT COUNT(*) FROM news_feeds").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO news_feeds (name, url) VALUES (?,?)",
                DEFAULT_FEEDS)


def list_feeds():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, url, active FROM news_feeds ORDER BY id").fetchall()
    return [{"id": r[0], "name": r[1], "url": r[2], "active": bool(r[3])}
            for r in rows]


def add_feed(name, url):
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise ValueError("The feed address must start with http:// or https://")
    with db.get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO news_feeds (name, url) VALUES (?,?)",
                     ((name or url).strip()[:80], url))


def remove_feed(feed_id):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM news_feeds WHERE id=?", (feed_id,))


# ------------------------------------------------------------------ parsing
_TAG = re.compile(r"<[^>]+>")


def _clean(text, limit=400):
    text = html.unescape(_TAG.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _when(raw):
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)               # RSS: RFC 822
    except Exception:
        try:
            d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom
        except Exception:
            return None
    if d.tzinfo:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d.isoformat(timespec="seconds")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml_text, fallback_source=""):
    """RSS 2.0 and Atom -> [{title, url, excerpt, source, published}]."""
    root = ET.fromstring(xml_text)
    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        f = {}
        for ch in node:
            name = _local(ch.tag)
            if name == "link":
                f.setdefault("link", ch.attrib.get("href") or (ch.text or "").strip())
            elif name in ("title", "description", "summary", "pubDate",
                          "updated", "published", "source"):
                f.setdefault(name, (ch.text or "").strip())
        title = _clean(f.get("title"), 300)
        url = f.get("link")
        if not title or not url:
            continue
        source = f.get("source") or fallback_source
        # Google News titles end with " - Publisher"
        if " - " in title and not f.get("source"):
            title, _, tail = title.rpartition(" - ")
            source = tail or source
        excerpt = _clean(f.get("description") or f.get("summary"))
        if excerpt.lower().startswith(title.lower()[:40]):
            excerpt = ""                    # Google repeats the headline
        out.append({"title": title, "url": url, "excerpt": excerpt,
                    "source": source[:80],
                    "published": _when(f.get("pubDate") or f.get("published")
                                       or f.get("updated"))})
    return out


# ------------------------------------------------------------------ tagging
_STOP = {"limited", "ltd", "india", "indian", "the", "and", "company",
         "corporation", "industries", "bank", "power", "finance", "financial",
         "services", "enterprises", "holdings", "group", "motors", "steel"}


def _name_index():
    """symbol -> {"tickers": [...], "phrases": [...]} used to spot a stock in
    a headline. Tickers match case-sensitively as whole words (so TCS and ITC
    work, and the ticker IDEA does not fire on the word "idea"); tickers of 5 or
    more letters (RELIANCE) match in any case. Company-name
    phrases match case-insensitively."""
    idx = {}
    funds = db.all_fundamentals()
    for (_id, atype, symbol, _sc, label, _a) in db.get_watchlist():
        if atype == "mf" or not symbol:
            continue
        base = symbol.split(".")[0]
        tickers = [base] if len(base) >= 3 and base.isupper() else []
        phrases = set()
        for name in (label, (funds.get(symbol) or {}).get("shortName"),
                     (funds.get(symbol) or {}).get("longName")):
            if not name:
                continue
            words = [w for w in re.findall(r"[A-Za-z]+", name)
                     if w.lower() not in _STOP]
            if words and len(words[0]) >= 4 and words[0].upper() != base:
                phrases.add(" ".join(words[:2]).lower())
        idx[symbol] = {"tickers": tickers,
                       "phrases": sorted(phrases, key=len, reverse=True)}
    return idx


def tag(text, idx):
    raw = " " + re.sub(r"[^A-Za-z0-9&-]+", " ", text or "") + " "
    low = raw.lower()
    return [s for s, k in idx.items()
            if any((f" {t} " in raw) if len(t) <= 4 else (f" {t.lower()} " in low)
                   for t in k["tickers"])
            or any(f" {p} " in low for p in k["phrases"])]


# ------------------------------------------------------------------ refresh
def _store(items, forced_symbol=None, idx=None):
    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    added = 0
    with db.get_conn() as conn:
        for it in items:
            syms = set(tag(it["title"] + " " + it["excerpt"], idx or {}))
            if forced_symbol:
                syms.add(forced_symbol)
            row = conn.execute("SELECT id, symbols FROM news WHERE url=?",
                               (it["url"],)).fetchone()
            if row:                          # seen before: just merge tags
                merged = sorted(set(json.loads(row[1] or "[]")) | syms)
                conn.execute("UPDATE news SET symbols=? WHERE id=?",
                             (json.dumps(merged), row[0]))
                continue
            conn.execute(
                "INSERT INTO news (url, title, excerpt, source, published, "
                "symbols, fetched) VALUES (?,?,?,?,?,?,?)",
                (it["url"], it["title"], it["excerpt"], it["source"],
                 it["published"] or now, json.dumps(sorted(syms)), now))
            added += 1
    return added


def _fetch(url):
    r = requests.get(url, headers=UA, timeout=12)
    r.raise_for_status()
    return r.text


def refresh(progress=lambda m: None, per_stock=True):
    """Pull every active feed, then a Google News search per stock."""
    ensure_tables()
    idx = _name_index()
    total = 0
    for feed in [f for f in list_feeds() if f["active"]]:
        try:
            n = _store(parse_feed(_fetch(feed["url"]), feed["name"]), idx=idx)
            total += n
            progress(f"[news] {feed['name']}: {n} new")
        except Exception as e:                       # one bad feed never
            progress(f"[news] {feed['name']} failed: {e}")   # stops the rest
    if per_stock:
        held = [h[1] for h in db.get_holdings()]
        order = list(dict.fromkeys(held + list(idx)))[:PER_STOCK_LIMIT]
        funds = db.all_fundamentals()
        for sym in order:
            name = (funds.get(sym) or {}).get("shortName") or sym.split(".")[0]
            q = urllib.parse.quote(f'"{name}" share')
            try:
                total += _store(parse_feed(_fetch(GOOGLE_NEWS.format(q=q)))[:8],
                                forced_symbol=sym, idx=idx)
            except Exception as e:
                progress(f"[news] {sym} search failed: {e}")
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM news WHERE published < ?", (cutoff,))
    progress(f"[news] {total} new stories")
    return total


def refresh_in_background():
    with _lock:
        if STATE["running"]:
            return False
        STATE.update(running=True, done=False, log=[])

    def work():
        try:
            refresh(progress=lambda m: STATE["log"].append(str(m)))
        except Exception as e:
            STATE["log"].append(f"[news] failed: {e}")
        STATE.update(running=False, done=True)
    threading.Thread(target=work, daemon=True).start()
    return True


# ------------------------------------------------------------------ reading
def _row(r):
    return {"id": r[0], "url": r[1], "title": r[2], "excerpt": r[3],
            "source": r[4], "published": r[5],
            "symbols": json.loads(r[6] or "[]"), "summary": r[7], "why": r[8]}


def my_symbols(username):
    syms = {h[1] for h in db.get_holdings(username)}
    syms |= {w[2] for w in db.get_watchlist() if w[2]}
    return syms


def latest(scope="mine", symbol=None, limit=40, username=None):
    ensure_tables()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, url, title, excerpt, source, published, symbols, "
            "summary, why FROM news ORDER BY published DESC LIMIT 400").fetchall()
    items = [_row(r) for r in rows]
    if symbol:
        items = [i for i in items if symbol in i["symbols"]]
    elif scope == "mine":
        mine = my_symbols(username)
        items = [i for i in items if mine & set(i["symbols"])]
    held = {h[1] for h in db.get_holdings(username)}
    for i in items:
        i["held"] = sorted(held & set(i["symbols"]))
    return items[:limit]


def explain(news_id):
    """Plain-language summary + why it matters, cached on the row."""
    from app.core import llm
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT id, url, title, excerpt, source, published, symbols, "
            "summary, why FROM news WHERE id=?", (news_id,)).fetchone()
    if not r:
        raise KeyError(news_id)
    item = _row(r)
    if item["summary"]:
        return item
    if not llm.available():
        raise RuntimeError(llm.setup_hint())
    prompt = (
        "You explain financial news to a new investor in India. Using ONLY "
        "the headline and excerpt below, reply with JSON and nothing else: "
        '{"summary": "2 plain sentences on what happened", '
        '"why": "1-2 sentences on why a holder of the stock might care"}. '
        "No advice, no predictions, no buy or sell words. If the text is too "
        "thin to summarise, say so in the summary.\n\n"
        f"Headline: {item['title']}\nExcerpt: {item['excerpt'] or '(none)'}\n"
        f"Stocks: {', '.join(s.split('.')[0] for s in item['symbols']) or 'none'}")
    # room for reasoning models' thinking (it counts against max_tokens)
    msg, _provider = llm.complete([{"role": "user", "content": prompt}],
                                  temperature=0.2, max_tokens=1024)
    if msg.get("finish_reason") == "length":
        # a cut-off summary would be cached on the row and shown for good
        raise RuntimeError("The AI's summary was cut off; try again.")
    text = (msg.get("content") or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    summary = str(data.get("summary") or text)[:600]
    why = str(data.get("why") or "")[:400]
    with db.get_conn() as conn:
        conn.execute("UPDATE news SET summary=?, why=? WHERE id=?",
                     (summary, why, news_id))
    item.update(summary=summary, why=why)
    return item
