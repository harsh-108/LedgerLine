"""
AI Analyst + Documents API router.

Install (exactly two lines in api.py, anywhere AFTER `app = FastAPI(...)`
— by convention next to the other feature sections):

    from app.analyst import analyst_api
    app.include_router(analyst_api.router)

That's the whole backend wiring. The router inherits the app's
require_login middleware automatically (all routes are /api/..., which
the middleware protects), so:
  - request.state.user  -> username set by your middleware, used to
    scope get_portfolio to the signed-in account
  - the 'session' cookie -> per-user chat memory key

Extra dependency for file uploads: pip install python-multipart
(FastAPI needs it for UploadFile/Form).
"""

from fastapi import (APIRouter, File, Form, HTTPException, Request,
                     UploadFile)

from app.analyst import analyst
from app.analyst import documents
from pydantic import BaseModel

router = APIRouter(prefix="/api")

MAX_UPLOAD_MB = 40


# ---------------------------------------------------------------- chat
class ChatIn(BaseModel):
    text: str
    symbol: str | None = None     # symbol selected in the documents panel


@router.post("/analyst/chat")
def analyst_chat(c: ChatIn, request: Request):
    text = (c.text or "").strip()
    if not text:
        raise HTTPException(400, "Empty message.")
    if len(text) > 4000:
        raise HTTPException(400, "Message too long (4000 chars max).")
    sid = request.cookies.get("session", "anon")
    username = getattr(request.state, "user", None)
    # A message trying to talk the analyst out of its rules ("ignore your
    # previous instructions...", disguised or not) is answered here with
    # the SDK's refusal: no AI call, nothing added to the chat history, and
    # it does not use up one of the user's daily questions.
    from app.analyst import injection_guard
    verdict = injection_guard.check(text)
    if verdict.blocked:
        return {"reply": verdict.block_message, "tools_used": [],
                "provider": None, "blocked": "prompt_injection",
                "category": verdict.pattern_matched}
    from app.core import accounts
    if username and not accounts.analyst_consume(username):
        used, limit = accounts.analyst_quota(username)
        raise HTTPException(429, f"Daily analyst limit reached ({limit} "
                                 f"questions). It resets at midnight.")
    out = analyst.chat(sid, text, username=username,
                       context={"symbol": c.symbol} if c.symbol else None)
    if "error" in out:
        # 503 = "the analyst is unavailable", distinct from a bad request
        raise HTTPException(503, out["error"])
    return out


@router.post("/analyst/reset")
def analyst_reset(request: Request):
    analyst.reset(request.cookies.get("session", "anon"))
    return {"ok": True}


@router.get("/analyst/status")
def analyst_status(request: Request):
    """Admins see the provider chain; users see readiness and their quota."""
    from app.core import accounts, envutil, llm
    username = getattr(request.state, "user", None)
    used, limit = accounts.analyst_quota(username) if username else (0, None)
    out = {"llm_ready": analyst.available(),
           "quota": {"used": used, "limit": limit,
                     "left": (None if limit is None else max(0, limit - used))}}
    if getattr(request.state, "role", "user") == accounts.ROLE_ADMIN:
        out["providers"] = llm.describe()
        out["web_search"] = bool(envutil.get("TAVILY_API_KEY"))
    return out


# ----------------------------------------------------------- documents
@router.post("/docs/upload")
async def docs_upload(symbol: str = Form(...),
                      file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File over {MAX_UPLOAD_MB} MB.")
    try:
        res = documents.ingest_file(symbol, file.filename or "upload.pdf",
                                    data)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Ingest failed: {e}")
    return res


class BseFetchIn(BaseModel):
    symbol: str
    scrip_code: str       # numeric BSE code, e.g. "533096" for ADANIPOWER
    days: int = 365


@router.post("/docs/fetch-bse")
def docs_fetch_bse(b: BseFetchIn):
    if not b.scrip_code.strip().isdigit():
        raise HTTPException(400, "scrip_code must be the numeric BSE "
                                 "code (shown on the BSE quote page).")
    return documents.fetch_bse(b.symbol, b.scrip_code.strip(),
                               days=max(30, min(b.days, 1095)))


@router.get("/docs/{symbol}")
def docs_list(symbol: str):
    return {"documents": documents.list_docs(symbol)}
