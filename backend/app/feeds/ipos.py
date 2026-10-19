"""IPOs and new fund offers.

There is no free official API, so the source of truth is a small table you
can fill by hand (Data and admin, or the IPO page). `sync_nse()` is a
best-effort auto-fill from NSE's public IPO pages through nsepython. When it
fails, the page still shows what was entered by hand and says so plainly.
"""
import datetime as dt

from app.core import database as db
from app.feeds.ipo_verdict import INPUT_HELP  # noqa: F401  (re-exported)

FIELDS = ("kind", "name", "detail", "open_date", "close_date", "listing_date",
          "price_low", "price_high", "lot_size", "issue_size", "link", "source")
# Inputs for the verdict (ipo_verdict.py). Subscription figures are filled
# from NSE while an issue is open; the rest is typed in from the RHP.
INPUTS = ("symbol", "sub_total", "sub_qib", "sub_nii", "sub_retail", "gmp_pct",
          "pe", "fresh_pct", "promoter_post")
# Bookkeeping the UI shows next to the verdict: when NSE last answered for
# the subscription, why it didn't, and what the RHP reader found.
META = ("sub_updated", "sub_error", "rhp_note")
ALL = FIELDS + INPUTS + META


def ensure_tables():
    with db.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ipos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            kind         TEXT NOT NULL DEFAULT 'ipo',     -- ipo | nfo
            name         TEXT NOT NULL,
            detail       TEXT,                            -- sector or fund category
            open_date    TEXT,
            close_date   TEXT,
            listing_date TEXT,
            price_low    REAL,
            price_high   REAL,
            lot_size     INTEGER,
            issue_size   TEXT,
            link         TEXT,
            source       TEXT NOT NULL DEFAULT 'manual',
            UNIQUE(kind, name, open_date)
        );
        """)
        for col in INPUTS + META:
            db._ensure_column(conn, "ipos", col,
                              "TEXT" if col in ("symbol",) + META else "REAL")


def _status(row, today):
    o, c, l = row.get("open_date"), row.get("close_date"), row.get("listing_date")
    if l and l <= today:
        return "listed"
    if o and o > today:
        return "upcoming"
    if o and c and o <= today <= c:
        return "open"
    if c and c < today:
        return "closed"
    return "upcoming"


def all_rows(with_verdict=True):
    ensure_tables()
    from app.feeds import ipo_verdict
    today = dt.date.today().isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, " + ", ".join(ALL) + " FROM ipos "
            "ORDER BY COALESCE(open_date, '9999') DESC").fetchall()
    out = []
    mood = ipo_verdict.market_mood() if with_verdict else None
    for r in rows:
        d = dict(zip(("id",) + ALL, r))
        d["status"] = _status(d, today)
        if d["status"] == "open" and d["close_date"]:
            d["days_left"] = (dt.date.fromisoformat(d["close_date"])
                              - dt.date.today()).days
        if d["price_high"] and d["lot_size"]:
            d["min_investment"] = round(d["price_high"] * d["lot_size"])
        if with_verdict and d["kind"] == "ipo":
            try:
                d["verdict"] = ipo_verdict.assess(d, mood)
            except Exception:
                d["verdict"] = None
        out.append(d)
    return out


def _iso(v):
    """Accept 2026-09-22, 22-Sep-2026, 22-09-2026, 22 Sep 2026."""
    if not v:
        return None
    v = str(v).strip()
    # whole string first ("22-September-2026" is longer than 11 chars),
    # then the first 11 chars to drop a trailing time
    for cand in (v, v[:11].strip()):
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d %b %Y",
                    "%d-%B-%Y", "%d %B %Y"):
            try:
                return dt.datetime.strptime(cand, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def save(data):
    ensure_tables()
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("A name is required.")
    vals = {k: data.get(k) for k in ALL}
    vals["kind"] = "nfo" if vals.get("kind") == "nfo" else "ipo"
    vals["name"] = name
    vals["source"] = vals.get("source") or "manual"
    for k in ("open_date", "close_date", "listing_date"):
        vals[k] = _iso(vals[k])
    for k in INPUTS[1:]:
        vals[k] = _float(vals[k])
    with db.get_conn() as conn:
        # COALESCE keeps hand-typed values when an NSE sync sends nulls
        conn.execute(
            "INSERT INTO ipos (" + ", ".join(ALL) + ") VALUES ("
            + ",".join("?" * len(ALL)) + ") "
            "ON CONFLICT(kind, name, open_date) DO UPDATE SET "
            + ", ".join(f"{k}=COALESCE(excluded.{k}, {k})"
                        for k in ALL if k not in ("kind", "name", "open_date")),
            [vals[k] for k in ALL])


def _float(v):
    """'12.3x' -> 12.3, '' -> None. Tolerates the x suffix NSE and news use."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).lower().replace("x", "").replace(",", "").strip())
    except ValueError:
        return None


def update_inputs(ipo_id, data):
    """Change only the verdict inputs of one issue (used by the small
    form on each card). Blank values clear the field."""
    ensure_tables()
    sets, args = [], []
    for k in INPUTS:
        if k not in data:
            continue
        sets.append(f"{k}=?")
        args.append((str(data[k]).strip().upper() or None) if k == "symbol"
                    else _float(data[k]))
    if not sets:
        return
    with db.get_conn() as conn:
        cur = conn.execute("UPDATE ipos SET " + ", ".join(sets) +
                           " WHERE id=?", args + [ipo_id])
        if cur.rowcount == 0:
            raise KeyError(ipo_id)


def remove(ipo_id):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM ipos WHERE id=?", (ipo_id,))


def _band(text):
    import re
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(text or "").replace(",", ""))]
    if not nums:
        return None, None
    return min(nums), max(nums)


def sync_nse():
    """Best-effort: read NSE's current and upcoming issue lists.
    Raises RuntimeError with a readable reason on any failure."""
    try:
        from nsepython import nsefetch
    except ImportError:
        raise RuntimeError("nsepython is not installed. Run: pip install "
                           "nsepython, then restart. Until then, add issues by hand.")
    added, errors = 0, []
    for url in ("https://www.nseindia.com/api/ipo-current-issue",
                "https://www.nseindia.com/api/all-upcoming-issues?category=ipo"):
        try:
            data = nsefetch(url)
            rows = data if isinstance(data, list) else (data or {}).get("data", [])
            for x in rows:
                name = x.get("companyName") or x.get("company") or x.get("symbol")
                if not name:
                    continue
                lo, hi = _band(x.get("issuePrice") or x.get("priceRange")
                               or x.get("priceBand"))
                series = str(x.get("series") or "")
                symbol = x.get("symbol")
                # NSE's issueSize is a share count; keep the unit explicit
                # so the verdict can turn it into crore with the price band.
                raw_size = str(x.get("issueSize") or "").replace(",", "")
                size = (f"{float(raw_size):,.0f} shares"
                        if raw_size.replace(".", "", 1).isdigit() else
                        (str(x.get("issueSize") or "") or None))
                save({"kind": "ipo", "name": name, "symbol": symbol,
                      "detail": "SME issue" if "SME" in series.upper() else "Mainboard issue",
                      "open_date": x.get("issueStartDate") or x.get("startDate"),
                      "close_date": x.get("issueEndDate") or x.get("endDate"),
                      "price_low": lo, "price_high": hi,
                      "lot_size": x.get("lotSize") or x.get("marketLot"),
                      "issue_size": size,
                      "link": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
                      "source": "nse"})
                added += 1
        except Exception as e:
            errors.append(f"{url.rsplit('/', 1)[-1]}: {e}")
    subs, sub_errors = refresh_subscriptions()
    errors += sub_errors
    if not added and errors:
        raise RuntimeError("NSE did not answer (" + " | ".join(errors) + "). "
                           "This source is unofficial and fails at times. "
                           "Issues added by hand are unaffected.")
    return {"added_or_updated": added, "subscriptions": subs, "errors": errors}


def _set_meta(ipo_id, **kv):
    with db.get_conn() as conn:
        conn.execute("UPDATE ipos SET " + ", ".join(f"{k}=?" for k in kv) +
                     " WHERE id=?", list(kv.values()) + [ipo_id])


def refresh_subscriptions(ipo_id=None):
    """Pull category-wise subscription from NSE for every open issue (or
    one). Records when it last worked and why it didn't, per issue, so the
    card can say so. Returns (updated_count, [error strings])."""
    updated, errors = 0, []
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for row in all_rows(with_verdict=False):
        if ipo_id is not None and row["id"] != ipo_id:
            continue
        if row["kind"] != "ipo" or (ipo_id is None and row["status"] != "open"):
            continue
        if not row.get("symbol"):
            _set_meta(row["id"], sub_error="No NSE symbol on this issue — "
                      "add it under the numbers, or run Fill from NSE.")
            continue
        try:
            if _sync_subscription(row):
                updated += 1
                _set_meta(row["id"], sub_updated=now, sub_error=None)
            else:
                _set_meta(row["id"], sub_error="NSE answered but sent no "
                          "category figures (issue may not have opened yet).")
        except Exception as e:
            msg = str(e)[:200]
            errors.append(f"subscription {row['symbol']}: {msg}")
            _set_meta(row["id"], sub_error=f"NSE did not answer: {msg}")
    return updated, errors


def subscription_loop():
    """Background: while any IPO is open, refresh subscription figures
    every 30 minutes during bidding hours (10:00-17:30 IST, weekdays).
    Started from main.py. Quiet on every failure; the card shows the last
    error instead."""
    import time
    while True:
        time.sleep(1800)
        try:
            now = dt.datetime.now()
            if now.weekday() >= 5 or not (10 <= now.hour < 18):
                continue
            if not any(r["status"] == "open" and r["kind"] == "ipo"
                       for r in all_rows(with_verdict=False)):
                continue
            refresh_subscriptions()
        except Exception:
            pass


def read_rhp(ipo_id, url=None):
    """Fill the valuation inputs of one issue from its RHP PDF. Uses the
    row's link when no url is given. Raises RuntimeError with a readable
    reason (no LLM configured, not a PDF, nothing found...)."""
    from app.feeds import rhp_reader
    rows = {r["id"]: r for r in all_rows(with_verdict=False)}
    row = rows.get(ipo_id)
    if not row:
        raise KeyError(ipo_id)
    url = (url or "").strip() or (row.get("link") or "")
    if not url.lower().startswith("http"):
        raise RuntimeError("Paste the link to the RHP PDF (from NSE, SEBI "
                           "or the lead manager's site).")
    inputs, note = rhp_reader.read(url, row.get("price_high"))
    fields = {k: v for k, v in inputs.items() if k in INPUTS}
    if fields:
        update_inputs(ipo_id, fields)
    extra = {k: v for k, v in inputs.items() if k in ("issue_size", "price_high")
             and not row.get(k)}
    if extra:
        _set_meta(ipo_id, **extra)
    _set_meta(ipo_id, rhp_note=note)
    return {"filled": sorted(list(fields) + list(extra)), "note": note}


def _sync_subscription(row):
    """Category-wise subscription for one open issue from NSE's
    ipo-active-category endpoint. Its JSON shape has changed before, so
    this reads any list of {category, ...times} dicts it can find and
    matches categories by keyword. Returns True when something was saved."""
    from nsepython import nsefetch
    data = nsefetch("https://www.nseindia.com/api/ipo-active-category?symbol="
                    + str(row["symbol"]))
    items = None
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                items = v
                break
    elif isinstance(data, list):
        items = data
    if not items:
        return False
    found = {}
    for it in items:
        cat = " ".join(str(it.get(k, "")) for k in ("category", "categoryName",
                                                  "name", "label")).lower()
        times = None
        for k, v in it.get("subCategory", {}).items() if isinstance(
                it.get("subCategory"), dict) else it.items():
            if "time" in str(k).lower():
                times = _float(v)
                break
        if times is None:
            continue
        if "total" in cat:
            found["sub_total"] = times
        elif "qualified" in cat or "qib" in cat:
            found["sub_qib"] = times
        elif "non" in cat or "nii" in cat or "hni" in cat:
            found["sub_nii"] = times
        elif "retail" in cat or "rii" in cat:
            found["sub_retail"] = times
    if not found:
        return False
    update_inputs(row["id"], found)
    return True
