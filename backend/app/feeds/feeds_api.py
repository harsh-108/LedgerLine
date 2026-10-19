"""Routes for News, the Results calendar, and IPOs / new fund offers.
One line in main.py wires this in:  app.include_router(feeds_api.router)"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.feeds import events_calendar as cal
from app.feeds import ipos, news

router = APIRouter(prefix="/api")
news.ensure_tables()
ipos.ensure_tables()
cal.ensure_tables()


# ---------------------------------------------------------------- news
@router.get("/news")
def news_list(request: Request, scope: str = "mine", symbol: str | None = None,
              limit: int = 40):
    user = getattr(request.state, "user", None)
    return {"items": news.latest(scope, symbol.upper() if symbol else None,
                                 min(limit, 100), user),
            "scope": scope}


@router.post("/news/refresh")
def news_refresh():
    return {"status": "started" if news.refresh_in_background()
            else "already_running"}


@router.get("/news/status")
def news_status():
    return {"running": news.STATE["running"], "done": news.STATE["done"],
            "log": news.STATE["log"][-14:]}


@router.post("/news/{news_id}/explain")
def news_explain(news_id: int):
    try:
        return news.explain(news_id)
    except KeyError:
        raise HTTPException(404, "That story is no longer stored.")
    except RuntimeError as e:
        raise HTTPException(503, str(e))


class FeedIn(BaseModel):
    name: str = ""
    url: str


@router.get("/news/feeds")
def feeds_list():
    return {"feeds": news.list_feeds()}


@router.post("/news/feeds")
def feeds_add(f: FeedIn):
    try:
        news.add_feed(f.name, f.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.delete("/news/feeds/{feed_id}")
def feeds_remove(feed_id: int):
    news.remove_feed(feed_id)
    return {"ok": True}


# ---------------------------------------------------------------- calendar
@router.get("/calendar")
def calendar(request: Request, start: str | None = None, days: int = 35):
    try:
        return cal.events(start, max(1, min(days, 120)),
                          getattr(request.state, "user", None))
    except ValueError:
        raise HTTPException(400, "start must look like 2026-09-21.")


@router.post("/calendar/refresh")
def calendar_refresh():
    return {"status": "started" if cal.refresh_in_background()
            else "already_running"}


@router.get("/calendar/status")
def calendar_status():
    return {"running": cal.STATE["running"], "done": cal.STATE["done"],
            "log": cal.STATE["log"][-14:]}


# ---------------------------------------------------------------- ipos
class IpoIn(BaseModel):
    kind: str = "ipo"
    name: str
    detail: str | None = None
    open_date: str | None = None
    close_date: str | None = None
    listing_date: str | None = None
    price_low: float | None = None
    price_high: float | None = None
    lot_size: int | None = None
    issue_size: str | None = None
    link: str | None = None
    # verdict inputs, all optional
    symbol: str | None = None
    sub_total: float | str | None = None
    sub_qib: float | str | None = None
    sub_nii: float | str | None = None
    sub_retail: float | str | None = None
    gmp_pct: float | str | None = None
    pe: float | str | None = None
    fresh_pct: float | str | None = None
    promoter_post: float | str | None = None


class IpoInputsIn(BaseModel):
    """Only the verdict inputs; anything omitted is left alone, a blank
    string clears the field."""
    symbol: str | None = None
    sub_total: float | str | None = None
    sub_qib: float | str | None = None
    sub_nii: float | str | None = None
    sub_retail: float | str | None = None
    gmp_pct: float | str | None = None
    pe: float | str | None = None
    fresh_pct: float | str | None = None
    promoter_post: float | str | None = None


@router.get("/ipos")
def ipo_list():
    return {"items": ipos.all_rows(), "input_help": ipos.INPUT_HELP}


class RhpIn(BaseModel):
    url: str | None = None


@router.post("/ipos/{ipo_id}/read-rhp")
def ipo_read_rhp(ipo_id: int, x: RhpIn):
    """Fill P/E, fresh-issue share and promoter holding from the RHP PDF.
    Slow (download + model call): tens of seconds on a phone."""
    try:
        return ipos.read_rhp(ipo_id, x.url)
    except KeyError:
        raise HTTPException(404, "That issue is no longer stored.")
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not read that PDF: {e}")


@router.post("/ipos/{ipo_id}/subscription")
def ipo_subscription(ipo_id: int):
    """Pull the subscription figures for one issue from NSE now."""
    n, errors = ipos.refresh_subscriptions(ipo_id)
    if errors:
        raise HTTPException(502, errors[0])
    return {"ok": True, "updated": n}


@router.post("/ipos/{ipo_id}/inputs")
def ipo_inputs(ipo_id: int, x: IpoInputsIn):
    data = x.model_dump(exclude_unset=True) if hasattr(x, "model_dump") \
        else x.dict(exclude_unset=True)
    try:
        ipos.update_inputs(ipo_id, data)
    except KeyError:
        raise HTTPException(404, "That issue is no longer stored.")
    return {"ok": True}


@router.post("/ipos")
def ipo_save(x: IpoIn):
    try:
        ipos.save(x.model_dump() if hasattr(x, "model_dump") else x.dict())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.delete("/ipos/{ipo_id}")
def ipo_remove(ipo_id: int):
    ipos.remove(ipo_id)
    return {"ok": True}


@router.post("/ipos/sync")
def ipo_sync():
    try:
        return ipos.sync_nse()
    except RuntimeError as e:
        raise HTTPException(502, str(e))
