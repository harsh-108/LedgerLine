"""
Documents — annual reports, concall transcripts, Screener exports.

Two ingestion paths, chosen by what each source actually permits:

MANUAL (the reliable path — Screener.in / Tijori):
    Screener and Tijori are login-walled products whose terms prohibit
    scraping, and their HTML changes constantly. But Screener gives every
    logged-in user an official "Export to Excel" button per company, and
    both link the actual filing PDFs. So: download by hand, then feed the
    file to ingest_file(). Annual report PDF, transcript PDF, Screener
    XLSX — all parsed, chunked, stored in SQLite, searchable by the
    AI analyst.

AUTO (legitimate — BSE public filings):
    Concall transcripts and annual reports are REGULATORY FILINGS —
    companies file them to the exchanges, and BSE serves them publicly.
    fetch_bse() pulls recent announcements for a scrip code, downloads
    matching PDFs (transcript / annual report / investor presentation)
    and ingests them. Same honesty rules as nse_source.py: public
    endpoints break when BSE redesigns; everything degrades to a clear
    error, never a crash, and calls are rate-limited politely.

Storage: two tables created on first use —
    documents(id, symbol, doc_type, title, source, filed_date, added_at)
    doc_chunks(doc_id, chunk_no, text)
Search is BM25 over an SQLite FTS5 index with Porter stemming, a finance
synonym list (debt ~ borrowings, capex ~ capital expenditure) and
structure-aware chunks that keep their pages and section heading for
citations. No embedding model: it runs offline on the phone, nothing is
sent anywhere to index a filing, and exact figures and terms ("Q2 FY26",
"₹1,240 crore") are where keyword ranking beats vectors anyway.

Dependencies:  pip install pypdf openpyxl     (both tiny; pandas exists)
"""

import datetime as dt
import io
import json
import os
import re
import time

import requests

from app.core import database as db

CHUNK_CHARS = 1400
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_DOC = 400          # ~350 pages of text; ARs fit
BSE_SLEEP = 1.5

_BSE_LIST = ("https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
             "?pageno=1&strCat=-1&strPrevDate={frm}&strScrip={scrip}"
             "&strSearch=P&strToDate={to}&strType=C")
_BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.bseindia.com/",
            "Accept": "application/json, text/plain, */*"}

_DOC_KEYWORDS = {          # BSE announcement title -> doc_type
    "transcript": "transcript",
    "annual report": "annual_report",
    "investor presentation": "presentation",
    "earnings presentation": "presentation",
    "press release": "press_release",
}


# =================================================================== schema
# Full-text index: SQLite FTS5 with BM25 ranking and Porter stemming
# (borrowings ~ borrowing, margins ~ margin). It holds its own copy of each
# chunk's text, keyed by a fixed rowid (doc_id * _KEY + chunk_no) so rows
# can be found again without a scan, and triggers on doc_chunks keep it in
# step with every insert and delete in the app (re-uploads, account
# deletion). Builds of SQLite without FTS5 fall back to the same BM25
# formula computed in Python (see _search_python).
_KEY = 10_000                     # > MAX_CHUNKS_PER_DOC, so keys never clash
_fts = {"ok": None}               # None = not checked yet, per process


def _ensure_tables():
    with db.get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, doc_type TEXT, title TEXT,
            source TEXT, filed_date TEXT, added_at TEXT,
            UNIQUE(symbol, title, filed_date))""")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
        if "username" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN username TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS doc_chunks (
            doc_id INTEGER NOT NULL, chunk_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (doc_id, chunk_no))""")
        # where a chunk came from, for citations ("annual report, p. 112");
        # NULL for chunks stored before 2026-10
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(doc_chunks)")]
        for col in ("page_from", "page_to"):
            if col not in ccols:
                conn.execute(f"ALTER TABLE doc_chunks ADD COLUMN {col} INTEGER")
        if "section" not in ccols:
            conn.execute("ALTER TABLE doc_chunks ADD COLUMN section TEXT")
    if _fts["ok"] is None:
        _fts["ok"] = _ensure_fts()


def _ensure_fts():
    """Create the FTS5 index and its sync triggers; fill it from existing
    chunks the first time. False when this SQLite has no FTS5."""
    try:
        with db.get_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='doc_fts'").fetchone()
            if not exists:
                conn.execute("CREATE VIRTUAL TABLE doc_fts USING fts5("
                             "body, tokenize='porter unicode61')")
                conn.execute(f"INSERT INTO doc_fts(rowid, body) SELECT "
                             f"doc_id * {_KEY} + chunk_no, "
                             "coalesce(section || char(10), '') || text "
                             "FROM doc_chunks")
            conn.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS doc_chunks_fts_ins
            AFTER INSERT ON doc_chunks BEGIN
              INSERT INTO doc_fts(rowid, body) VALUES (
                new.doc_id * {_KEY} + new.chunk_no,
                coalesce(new.section || char(10), '') || new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS doc_chunks_fts_del
            AFTER DELETE ON doc_chunks BEGIN
              DELETE FROM doc_fts WHERE rowid = old.doc_id * {_KEY} + old.chunk_no;
            END;
            CREATE TRIGGER IF NOT EXISTS doc_chunks_fts_upd
            AFTER UPDATE ON doc_chunks BEGIN
              DELETE FROM doc_fts WHERE rowid = old.doc_id * {_KEY} + old.chunk_no;
              INSERT INTO doc_fts(rowid, body) VALUES (
                new.doc_id * {_KEY} + new.chunk_no,
                coalesce(new.section || char(10), '') || new.text);
            END;
            """)
        return True
    except Exception:
        return False                       # no FTS5 in this SQLite build


# ================================================================== parsing
# Each parser returns pages: [(page_no or None, text)], so chunks can say
# which pages they came from.
def _pdf_pages(data: bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pip install pypdf  (needed for PDF parsing)")
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, p in enumerate(reader.pages, start=1):
        try:
            pages.append((i, p.extract_text() or ""))
        except Exception:
            pages.append((i, ""))
    # scanned PDFs extract to almost nothing — be honest about it
    if len(re.sub(r"\s", "", "".join(t for _, t in pages))) < 500:
        raise RuntimeError("PDF has no extractable text layer (likely a "
                           "scanned image) — OCR is out of scope here; "
                           "try the exchange copy, which is usually "
                           "text-based.")
    return pages


def _xlsx_pages(data: bytes):
    """Screener 'Export to Excel' → readable text tables, one per sheet."""
    import pandas as pd
    out = []
    xls = pd.ExcelFile(io.BytesIO(data))
    for sheet in xls.sheet_names:
        try:
            frame = xls.parse(sheet, header=None)
        except Exception:
            continue
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if frame.empty:
            continue
        out.append((None, f"### Sheet: {sheet}\n\n"
                    + frame.to_string(index=False, header=False,
                                      max_colwidth=28)))
    if not out:
        raise RuntimeError("No readable sheets in this Excel file.")
    return out


# ================================================================= chunking
# Chunks follow the document's own structure: paragraphs stay whole, a new
# heading starts a new chunk, and each chunk remembers its pages and the
# heading it sits under. Fixed 1,400-character slices used to cut tables
# and sentences in half and lost where the text came from.
_HEADING = re.compile(
    r"^(?:#{1,4}\s+\S.*"                          # markdown / sheet titles
    r"|(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,5}\.)\s+[A-Z].{2,70}"  # 1.2 Title
    r"|[A-Z][A-Z0-9&,'()/ -]{3,70})$")            # ALL-CAPS line


def _is_heading(line):
    line = line.strip()
    if not (4 <= len(line) <= 80) or line.endswith((".", ",", ";", ":")):
        return False
    if not _HEADING.match(line) or re.search(r"www\.|@|https?:", line):
        return False
    # filings are full of numbered form rows and table lines that look
    # like headings ("8. Website ...", "3. Asian Paints Ltd Subsidiary
    # 100"): after any leading number, a heading has no digits and is short
    rest = re.sub(r"^(?:#{1,4}\s+|(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,5}\.)"
                  r"\s+)", "", line)
    if re.search(r"\d", rest) or len(rest.split()) > 8:
        return False
    if rest.isupper() and len(rest.split()) < 2 and not line.startswith("#"):
        return False            # one all-caps word is as often a name
    return sum(c.isalpha() for c in rest) >= 4


def _paragraphs(pages):
    """[(page, text, is_heading)] in reading order."""
    out = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text or "")
        for block in re.split(r"\n\s*\n", text):
            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            buf = []
            for ln in lines:
                if _is_heading(ln):
                    if buf:
                        out.append((page, " ".join(buf), False))
                        buf = []
                    out.append((page, ln.lstrip("# ").strip(), True))
                else:
                    buf.append(ln)
            if buf:
                # keep table-like blocks (mostly numbers) line by line
                joiner = "\n" if sum(any(c.isdigit() for c in b)
                                     for b in buf) > len(buf) / 2 else " "
                out.append((page, joiner.join(buf), False))
    return out


def _split_long(text, limit):
    """A paragraph longer than a chunk: split at sentence ends, then hard."""
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        while len(sent) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(sent[:limit])
            sent = sent[limit:]
        if cur and len(cur) + 1 + len(sent) > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def _chunk_pages(pages):
    """[(text, page_from, page_to, section)], at most MAX_CHUNKS_PER_DOC.
    Consecutive chunks share a short overlap (the end of the previous
    chunk), so an answer that straddles a boundary is still findable."""
    chunks = []
    st = {"cur": [], "fresh": False, "from": None, "to": None, "section": None}

    def size():
        return sum(len(x) for x in st["cur"])

    def flush(overlap=True):
        if st["fresh"]:
            chunks.append(("\n\n".join(st["cur"]).strip(), st["from"],
                           st["to"], st["section"]))
        tail = ""
        if overlap and st["cur"]:
            tail = st["cur"][-1][-CHUNK_OVERLAP:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
        st["cur"] = [tail] if tail else []
        st["fresh"] = False
        st["from"] = st["to"] if tail else None

    def add(text, page):
        if st["from"] is None:
            st["from"] = page
        st["cur"].append(text)
        st["fresh"] = True
        if page is not None:
            st["to"] = page

    for page, text, heading in _paragraphs(pages):
        if heading:
            # a heading opens a new chunk unless the current one is short;
            # either way the heading text stays searchable in the chunk
            if size() > CHUNK_CHARS * 0.35:
                flush(overlap=False)
            st["section"] = text[:120]
            add(text, page)
            continue
        for piece in _split_long(text, CHUNK_CHARS):
            if st["fresh"] and size() + len(piece) > CHUNK_CHARS:
                flush()
            add(piece, page)
            if len(chunks) >= MAX_CHUNKS_PER_DOC:
                return chunks[:MAX_CHUNKS_PER_DOC]
    flush(overlap=False)
    return chunks[:MAX_CHUNKS_PER_DOC]


# ================================================================ ingestion
def ingest_file(symbol, filename, data: bytes, doc_type=None,
                source="manual upload", filed_date=None):
    """Parse + store one document. Returns {'doc_id', 'chunks'} or raises
    RuntimeError with a user-readable message."""
    _ensure_tables()
    name = filename.lower()
    if name.endswith(".pdf"):
        pages = _pdf_pages(data)
    elif name.endswith((".xlsx", ".xls")):
        pages = _xlsx_pages(data)
        doc_type = doc_type or "screener_export"
    elif name.endswith((".txt", ".md")):
        pages = [(None, data.decode("utf-8", errors="replace"))]
    else:
        raise RuntimeError("Supported: .pdf, .xlsx, .txt/.md")

    if doc_type is None:
        low = name + " "
        doc_type = next((v for k, v in _DOC_KEYWORDS.items() if k in low),
                        "document")
    chunks = _chunk_pages(pages)
    if not chunks:
        raise RuntimeError("Document parsed to empty text.")

    with db.get_conn() as conn:
        owner = db.scope_user() if source == "manual upload" else None
        # INSERT OR REPLACE gives a re-uploaded document a NEW id, which
        # used to leave the old copy's chunks behind (orphaned text);
        # drop them first
        old = conn.execute(
            "SELECT id FROM documents WHERE symbol=? AND title=? AND "
            "filed_date=?", (symbol.upper(), filename, filed_date or "")
        ).fetchone()
        if old:
            conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (old[0],))
        cur = conn.execute(
            """INSERT OR REPLACE INTO documents
               (symbol, doc_type, title, source, filed_date, added_at,
                username)
               VALUES (?,?,?,?,?,?,?)""",
            (symbol.upper(), doc_type, filename, source,
             filed_date or "", dt.datetime.now().isoformat(" ", "seconds"),
             owner))
        doc_id = cur.lastrowid
        conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            "INSERT INTO doc_chunks (doc_id, chunk_no, text, page_from, "
            "page_to, section) VALUES (?,?,?,?,?,?)",
            [(doc_id, i, text, pf, pt, sec)
             for i, (text, pf, pt, sec) in enumerate(chunks)])
    return {"doc_id": doc_id, "chunks": len(chunks), "doc_type": doc_type}


# ============================================================= BSE fetching
def fetch_bse(symbol, scrip_code, days=365, types=("transcript",
                                                   "annual report",
                                                   "investor presentation")):
    """Pull recent BSE announcements for a scrip code and ingest matching
    PDFs. scrip_code is the numeric BSE code (e.g. 533096 for Adani
    Power) — shown on every BSE quote page and in your app's symbol
    search. Returns a summary dict; never raises."""
    _ensure_tables()
    to = dt.date.today()
    frm = to - dt.timedelta(days=days)
    url = _BSE_LIST.format(frm=frm.strftime("%Y%m%d"),
                           to=to.strftime("%Y%m%d"), scrip=scrip_code)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=25)
        r.raise_for_status()
        rows = (r.json() or {}).get("Table", []) or []
    except Exception as e:
        return {"error": f"BSE announcements fetch failed ({e}). BSE "
                         "endpoints change occasionally — download the "
                         "PDF manually and use the upload route instead."}

    wanted, skipped, errors = [], 0, []
    for row in rows:
        title = (row.get("HEADLINE") or row.get("NEWSSUB") or "").strip()
        low = title.lower()
        if not any(t in low for t in types):
            skipped += 1
            continue
        attach = row.get("ATTACHMENTNAME")
        if not attach:
            skipped += 1
            continue
        wanted.append((title, attach, (row.get("NEWS_DT") or "")[:10]))

    ingested = []
    for title, attach, filed in wanted[:12]:      # politeness cap per run
        try:
            time.sleep(BSE_SLEEP)
            pdf = requests.get(_BSE_ATTACH.format(name=attach),
                               headers=_HEADERS, timeout=40)
            pdf.raise_for_status()
            res = ingest_file(symbol, title[:120] + ".pdf", pdf.content,
                              source=f"BSE filing {attach}",
                              filed_date=filed)
            ingested.append({"title": title[:90], "filed": filed,
                             "chunks": res["chunks"],
                             "type": res["doc_type"]})
        except Exception as e:
            errors.append(f"{title[:60]}: {e}")
    return {"ingested": ingested, "matched": len(wanted),
            "skipped_other": skipped, "errors": errors[:5]}


# ================================================================== search
_STOP = set("the a an and or of to in for on with is are was were be this "
            "that it its as at by from we our us has have had will would "
            "company quarter year".split())


def _visible():
    """SQL fragment + args restricting to shared docs plus the request
    user's own uploads. Unscoped (jobs/admin) sees everything."""
    u = db.scope_user()
    if u:
        return " AND (username IS NULL OR username = ?)", (u,)
    return "", ()


def resolve_symbol(symbol):
    """Docs are stored under the full Yahoo symbol (ASIANPAINT.NS). Accept
    the bare base too, and either suffix, so the analyst's tool calls
    don't miss documents over a '.NS'."""
    _ensure_tables()
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    base = sym.split(".")[0]
    with db.get_conn() as conn:
        vis, vargs = _visible()
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM documents WHERE (symbol = ? "
            f"OR symbol LIKE ?){vis}", (sym, base + ".%", *vargs)).fetchall()
    stored = [r[0] for r in rows]
    if sym in stored or not stored:
        return sym
    return stored[0]


def list_docs(symbol):
    _ensure_tables()
    symbol = resolve_symbol(symbol)
    vis, vargs = _visible()
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""SELECT d.id, d.doc_type, d.title, d.source, d.filed_date,
                      d.added_at, COUNT(c.chunk_no)
               FROM documents d LEFT JOIN doc_chunks c ON c.doc_id = d.id
               WHERE d.symbol = ?{vis.replace('username', 'd.username')}
               GROUP BY d.id
               ORDER BY d.filed_date DESC, d.id DESC""",
            (symbol, *vargs)).fetchall()
    return [{"doc_id": r[0], "doc_type": r[1], "title": r[2],
             "source": r[3], "filed_date": r[4], "added_at": r[5],
             "chunks": r[6]}
            for r in rows]


def read_doc(doc_id, start=0, n=4):
    """Sequential read of a stored document: chunks [start, start+n).
    For 'what is this document about', the first few chunks (cover
    letter, subject line, contents) are usually enough."""
    _ensure_tables()
    n = max(1, min(int(n or 4), 8))
    start = max(0, int(start or 0))
    with db.get_conn() as conn:
        vis, vargs = _visible()
        meta = conn.execute(
            "SELECT symbol, doc_type, title, filed_date FROM documents "
            f"WHERE id = ?{vis}", (int(doc_id), *vargs)).fetchone()
        if not meta:
            return {"error": f"no document with id {doc_id}"}
        total = conn.execute(
            "SELECT COUNT(*) FROM doc_chunks WHERE doc_id = ?",
            (int(doc_id),)).fetchone()[0]
        rows = conn.execute(
            "SELECT chunk_no, text, page_from, page_to FROM doc_chunks "
            "WHERE doc_id = ? AND chunk_no >= ? ORDER BY chunk_no LIMIT ?",
            (int(doc_id), start, n)).fetchall()
    pf = [r[2] for r in rows if r[2] is not None]
    pt = [r[3] for r in rows if r[3] is not None]
    return {"doc_id": int(doc_id), "symbol": meta[0], "doc_type": meta[1],
            "title": meta[2], "filed_date": meta[3],
            "total_chunks": total, "from_chunk": start,
            "to_chunk": start + len(rows) - 1,
            "more": start + len(rows) < total,
            "pages": (f"{min(pf)}-{max(pt or pf)}" if pf else None),
            "text": "\n\n".join(t for _, t, _, _ in rows)}


# Filings say the same thing in different words. Each group is searched as
# one idea: asking for "debt" also finds "borrowings". Stemming already
# covers plurals and tenses, so entries are base forms.
SYNONYMS = [
    ["debt", "borrowings", "loans", "leverage", "indebtedness"],
    ["capex", "capital expenditure", "capacity expansion", "greenfield",
     "brownfield"],
    ["guidance", "outlook", "forecast"],
    ["revenue", "sales", "turnover", "topline", "revenue from operations"],
    ["profit", "pat", "net income", "earnings", "bottom line"],
    ["ebitda", "operating profit", "operating margin"],
    ["order book", "orderbook", "order backlog", "order inflow"],
    ["pledge", "pledged", "encumbered", "encumbrance"],
    ["dividend", "payout"],
    ["acquisition", "merger", "takeover", "amalgamation"],
    ["working capital", "receivables", "debtors", "inventory"],
    ["cash flow", "cashflow", "operating cash", "free cash flow"],
    ["interest cost", "finance cost", "finance costs", "interest expense"],
    ["npa", "gnpa", "nnpa", "non performing", "asset quality",
     "bad loans"],
    ["attrition", "headcount"],
    ["buyback", "buy back"],
    ["litigation", "legal proceedings", "dispute", "contingent liability"],
    ["rating", "credit rating"],
    ["risk", "risk factors"],
    ["demand", "volume growth", "offtake"],
    ["promoter", "promoter group"],
]


def _expand(query):
    """[(term or phrase, is_from_query)]: the query's own words first,
    then every synonym of any group they hit."""
    low = " ".join(re.findall(r"[a-z0-9]+", (query or "").lower()))
    words = [w for w in low.split() if w not in _STOP and len(w) > 2]
    out = [(w, True) for w in dict.fromkeys(words)]
    seen = set(words)
    for group in SYNONYMS:
        if any(re.search(rf"\b{re.escape(g)}s?\b", low) for g in group):
            for g in group:
                if g not in seen:
                    seen.add(g)
                    out.append((g, False))
    return out


def _alternatives(query):
    """For each word of the question: that word plus its synonyms."""
    low = " ".join(re.findall(r"[a-z0-9]+", (query or "").lower()))
    out = {}
    for w in dict.fromkeys(low.split()):
        if w in _STOP or len(w) <= 2:
            continue
        alts = {w}
        for group in SYNONYMS:
            if any(re.fullmatch(rf"{re.escape(g)}s?", w) for g in group) or \
                    any(" " in g and g in low for g in group if w in g):
                alts.update(group)
        out[w] = alts
    return out


def _covers(text, alts):
    """Does the text mention this idea in any of its forms? Prefix match
    so 'reduction' also accepts 'reduced', like the stemmed index does."""
    for a in alts:
        if " " in a:
            if a in text:
                return True
        elif re.search(r"\b" + re.escape(a[:max(5, len(a) - 3)]), text):
            return True
    return False


def _fts_query(terms):
    """FTS5 MATCH string: every term or phrase quoted (so user text can't
    inject FTS syntax), OR-ed together; BM25 does the weighing."""
    return " OR ".join('"' + t.replace('"', "") + '"' for t, _ in terms)


def _candidate_docs(symbol):
    """{doc_id: (title, doc_type, filed_date)} visible to this user."""
    vis, vargs = _visible()
    with db.get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, title, doc_type, filed_date FROM documents "
            f"WHERE symbol = ?{vis}", (symbol, *vargs)).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def search(symbol, query, top_k=6):
    """Rank this stock's document chunks for a question and return the
    best ones with their document, pages and section — the analyst quotes
    and cites from these. BM25 (the scoring search engines use): a rare
    word like "capex" counts for more than a common one, repeats give
    diminishing returns, and long chunks get no free advantage."""
    _ensure_tables()
    symbol = resolve_symbol(symbol)
    terms = _expand(query)
    if not terms:
        return {"error": "query too generic — use specific words "
                         "(capex, guidance, pledge, margin...)"}
    docs = _candidate_docs(symbol)
    if not docs:
        return {"error": f"no documents stored for {symbol} — upload an "
                         "annual report/transcript or run the BSE fetch."}
    top_k = max(1, min(int(top_k or 6), 12))
    # BM25 over every term OR-ed together can let one rare word carry a
    # chunk that ignores the rest of the question. Take a wider shortlist,
    # then weigh each candidate by how many of the question's ideas it
    # covers (a synonym counts): all of them x1.25, one of three x0.58.
    pool = max(top_k * 6, 40)
    ranked = (_search_fts(terms, docs, pool) if _fts["ok"]
              else _search_python(terms, docs, pool))
    ideas = _alternatives(query)
    hits = []
    if ranked:
        with db.get_conn() as conn:
            for key, score in ranked:
                doc_id, cno = divmod(key, _KEY)
                row = conn.execute(
                    "SELECT text, page_from, page_to, section FROM doc_chunks "
                    "WHERE doc_id=? AND chunk_no=?", (doc_id, cno)).fetchone()
                if not row:
                    continue
                low = ((row[3] or "") + " " + row[0]).lower()
                cover = (sum(_covers(low, a) for a in ideas.values())
                         / len(ideas)) if ideas else 1.0
                title, dtype, filed = docs[doc_id]
                pages = (None if row[1] is None else
                         str(row[1]) if row[2] in (None, row[1])
                         else f"{row[1]}-{row[2]}")
                hits.append({"doc_id": doc_id, "title": title,
                             "doc_type": dtype, "filed": filed, "chunk": cno,
                             "pages": pages, "section": row[3],
                             "score": round(score * (0.25 + cover), 2),
                             "covers": f"{round(cover * len(ideas))}/"
                                       f"{len(ideas)}" if ideas else None,
                             "text": row[0]})
        hits.sort(key=lambda h: -h["score"])
        hits = hits[:top_k]
    return {"query_terms": [t for t, own in terms if own],
            "also_searched": [t for t, own in terms if not own],
            "ranking": "bm25" if _fts["ok"] else "bm25 (python)",
            "hits": hits}


def _search_fts(terms, docs, top_k):
    """[(key, score)] best first, via the FTS5 index."""
    ids = ",".join(str(int(d)) for d in docs)
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT rowid, bm25(doc_fts) FROM doc_fts "
            f"WHERE doc_fts MATCH ? AND (rowid / {_KEY}) IN ({ids}) "
            "ORDER BY bm25(doc_fts) LIMIT ?",
            (_fts_query(terms), top_k)).fetchall()
    return [(int(r[0]), -float(r[1])) for r in rows]   # bm25() is negative


_SUFFIXES = ("ings", "ing", "ies", "es", "ed", "s")


def _stem(w):
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _search_python(terms, docs, top_k, k1=1.2, b=0.75):
    """The same BM25 ranking computed in Python, for SQLite builds without
    FTS5. Fine for one stock's filings (a few thousand chunks at most)."""
    import math
    ids = ",".join(str(int(d)) for d in docs)
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, chunk_no, coalesce(section || ' ', '') || text "
            f"FROM doc_chunks WHERE doc_id IN ({ids})").fetchall()
    if not rows:
        return []
    toks = [[_stem(w) for w in re.findall(r"[a-z0-9]+", t.lower())]
            for _, _, t in rows]
    n, avg = len(rows), (sum(len(t) for t in toks) / len(rows)) or 1
    q = [[_stem(w) for w in t.split()] for t, _ in terms]
    joined = [" ".join(t) for t in toks]

    def tf(i, phrase):
        if len(phrase) == 1:
            return toks[i].count(phrase[0])
        return joined[i].count(" ".join(phrase))

    scores = [0.0] * n
    for phrase in q:
        counts = [tf(i, phrase) for i in range(n)]
        df = sum(1 for c in counts if c)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, c in enumerate(counts):
            if c:
                scores[i] += idf * c * (k1 + 1) / (
                    c + k1 * (1 - b + b * len(toks[i]) / avg))
    best = sorted(range(n), key=lambda i: -scores[i])[:top_k]
    return [(rows[i][0] * _KEY + rows[i][1], scores[i])
            for i in best if scores[i] > 0]
