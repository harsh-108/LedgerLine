"""
Account routes beyond login/logout (those stay in main.py):

  POST /api/auth/signup            email + username + password + invite
  GET  /api/auth/verify?token=     from the email link; signs the user in
  POST /api/auth/resend            re-send verification
  POST /api/auth/forgot            always 200; mails a reset link if known
  POST /api/auth/reset             token + new password
  POST /api/auth/google            Google ID token -> sign in / sign up
  POST /api/auth/change-password   signed in; revokes other sessions
  GET  /api/auth/config            what the login/signup pages need

  GET/POST/DELETE /api/admin/invites, GET /api/admin/users,
  POST /api/admin/users/{u}/role, DELETE /api/admin/users/{u}
                                            (admin only, enforced in
                                             main.py's middleware)

  POST /api/telegram/link-code, GET /api/telegram/status,
  DELETE /api/telegram/link
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import accounts, auth, envutil, google_auth, mailer

router = APIRouter(prefix="/api")


_LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _ip(request: Request):
    """The visitor's address, for per-IP rate limits. Forwarded headers are
    trusted only when the connection comes from this machine, i.e. through
    the local ngrok / cloudflared agent; anyone else could write any value
    there. ngrok APPENDS the real address to X-Forwarded-For, so the last
    entry is the one it vouches for; the first is whatever the client sent
    (taking it let an attacker rotate fake IPs past the login limit)."""
    peer = request.client.host if request.client else "?"
    if peer not in _LOOPBACK:
        return peer
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return peer


def _device(ua):
    """'Chrome on Android'-style label from a User-Agent, for alerts."""
    ua = ua or ""
    browser = next((b for k, b in (("Edg/", "Edge"), ("OPR/", "Opera"),
                                   ("Firefox/", "Firefox"),
                                   ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if k in ua),
                   "a browser")
    system = next((o for k, o in (("Android", "Android"), ("iPhone", "iPhone"),
                                  ("iPad", "iPad"), ("Windows", "Windows"),
                                  ("Mac OS", "Mac"), ("Linux", "Linux"))
                   if k in ua), "an unknown device")
    return f"{browser} on {system}"


def _signin_alert(username, request):
    """Tell the account's linked Telegram chat about a new sign-in, so a
    stolen password shows up the first time it is used. Background thread:
    Telegram being slow must never slow the login itself."""
    import threading
    from datetime import datetime
    from app.alerts import notify
    device = _device(request.headers.get("user-agent"))
    text = (f"New sign-in to Ledgerline as '{username}' "
            f"({datetime.now():%d %b %Y, %H:%M}), {device}, "
            f"from {_ip(request)}.\n"
            "Not you? Open Settings, choose 'Sign out other devices', "
            "and change your password.")
    threading.Thread(target=notify.send_to_user, args=(username, text),
                     daemon=True).start()


def _session_response(username, payload=None, request=None):
    body = {"ok": True, "user": username}
    if payload:
        body.update(payload)
    if request is not None:
        try:
            _signin_alert(username, request)
        except Exception:
            pass                      # an alert must never block a login
    resp = JSONResponse(body)
    resp.set_cookie("session", auth.start_session(username), httponly=True,
                    samesite="lax", secure=_secure_cookies(),
                    max_age=auth.SESSION_DAYS * 86400)
    return resp


def _secure_cookies():
    return mailer.base_url().startswith("https://")


def signup_requires_invite():
    v = (envutil.get("SIGNUP_REQUIRE_INVITE") or "1").strip().lower()
    return v not in ("0", "false", "no")


def google_requires_invite():
    """Google sign-ups skip the invite code by default: Google has already
    verified the inbox, and the code was really a stand-in for that. Set
    GOOGLE_SIGNUP_REQUIRE_INVITE=1 to demand a code from them as well."""
    if not signup_requires_invite():
        return False
    v = (envutil.get("GOOGLE_SIGNUP_REQUIRE_INVITE") or "0").strip().lower()
    return v in ("1", "true", "yes")


# ------------------------------------------------------------- config
@router.get("/auth/config")
def auth_config():
    return {"google_client_id": google_auth.client_id(),
            "email_configured": mailer.configured(),
            "invite_required": signup_requires_invite(),
            "google_invite_required": google_requires_invite(),
            "signup_open": auth.any_users()}


# ------------------------------------------------------------- signup
class SignupIn(BaseModel):
    email: str
    username: str
    password: str
    invite_code: str | None = None


def _send_verification(username, email):
    token = accounts.issue_token(username, "verify")
    link = f"{mailer.base_url()}/verify?token={token}"
    ok, err = mailer.verification_email(email, username, link)
    extra = {}
    if not ok:
        print(f"[auth] verification mail to {email} FAILED: {err}")
        if mailer.dev_links():
            print(f"[auth] verification link for {username}: {link}")
            extra["dev_verify_url"] = link
            extra["mail_error"] = err          # dev mode only
    return ok, err, extra


@router.post("/auth/signup")
def auth_signup(c: SignupIn, request: Request):
    if not auth.any_users():
        raise HTTPException(400, "Create the first account on the login "
                                 "page instead.")
    if accounts.rate_limited("signup_ip", _ip(request)):
        raise HTTPException(429, "Too many sign-ups from this address. "
                                 "Try again later.")
    if signup_requires_invite() and not accounts.invite_valid(c.invite_code):
        raise HTTPException(403, "A valid invite code is required.")
    if not mailer.configured() and not mailer.dev_links():
        raise HTTPException(503, "Email isn't configured on this server, so "
                                 "sign-up is closed. Ask the admin.")
    try:
        username = accounts.register(c.username, c.password, email=c.email,
                                     verified=False)
        if signup_requires_invite():
            accounts.redeem_invite(c.invite_code, username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ok, err, extra = _send_verification(username, c.email.strip().lower())
    if not ok and not extra:
        raise HTTPException(503, f"Account created but the email failed: "
                                 f"{err}. Use 'resend' after the admin "
                                 f"fixes email.")
    return {"ok": True, "user": username, "verify_sent": ok, **extra}


class EmailIn(BaseModel):
    email: str


@router.post("/auth/resend")
def auth_resend(c: EmailIn, request: Request):
    if accounts.rate_limited("forgot_ip", _ip(request)):
        raise HTTPException(429, "Too many requests. Try again later.")
    username = accounts.find_by_email(c.email)
    u = accounts.get_user(username) if username else None
    extra = {}
    if u and not u["email_verified"]:
        # Same contract as signup/forgot: the failure is logged, and when
        # AUTH_DEV_LINKS=1 the link + provider error come back in the body
        # so the UI can show them instead of a misleading "on its way".
        _, _, extra = _send_verification(username, u["email"])
    return {"ok": True, **extra}             # never reveal whether it exists


@router.get("/auth/verify")
def auth_verify(request: Request, token: str = ""):
    """Called by the /verify page (JSON, sets the session cookie)."""
    username = accounts.consume_token(token, "verify")
    if not username:
        raise HTTPException(400, "This link is invalid or has expired. "
                                 "Request a new one from the sign-in page.")
    accounts.mark_verified(username)
    return _session_response(username, request=request)


# ------------------------------------------------------------- reset
@router.post("/auth/forgot")
def auth_forgot(c: EmailIn, request: Request):
    if accounts.rate_limited("forgot_ip", _ip(request)):
        raise HTTPException(429, "Too many requests. Try again later.")
    username = accounts.find_by_email(c.email)
    extra = {}
    if username:
        token = accounts.issue_token(username, "reset")
        link = f"{mailer.base_url()}/reset?token={token}"
        ok, err = mailer.reset_email(c.email.strip().lower(), username, link)
        if not ok:
            print(f"[auth] reset mail to {c.email} FAILED: {err}")
            if mailer.dev_links():
                print(f"[auth] reset link for {username}: {link}")
                extra["dev_reset_url"] = link
                extra["mail_error"] = err
    return {"ok": True, **extra}


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/auth/reset")
def auth_reset(c: ResetIn, request: Request):
    username = accounts.consume_token(c.token, "reset")
    if not username:
        raise HTTPException(400, "This link is invalid or has expired.")
    try:
        accounts.change_password(username, c.password)
        accounts.mark_verified(username)          # they proved the inbox
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _session_response(username, request=request)


class ChangePwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def auth_change_password(c: ChangePwIn, request: Request):
    username = request.state.user
    if not auth.verify(username, c.current_password):
        raise HTTPException(401, "Current password is wrong.")
    try:
        accounts.change_password(username, c.new_password,
                                 keep_session_token=request.cookies.get(
                                     "session"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ------------------------------------------------------------- google
class GoogleIn(BaseModel):
    credential: str
    invite_code: str | None = None


@router.post("/auth/google")
def auth_google(c: GoogleIn, request: Request):
    if accounts.rate_limited("google_ip", _ip(request)):
        raise HTTPException(429, "Too many attempts. Try again later.")
    try:
        info = google_auth.verify_id_token(c.credential)
    except ValueError as e:
        raise HTTPException(401, str(e))
    username = accounts.find_by_google_sub(info["sub"])
    if not username:
        username = accounts.find_by_email(info["email"])
        if username:
            accounts.link_google(username, info["sub"])   # same inbox
    if not username:
        if not auth.any_users():
            raise HTTPException(400, "Create the first account on the "
                                     "login page first.")
        need_invite = google_requires_invite()
        if need_invite and not accounts.invite_valid(c.invite_code):
            raise HTTPException(403, "No account for this Google email "
                                     "yet. Enter an invite code to sign up.")
        try:
            username = accounts.register(
                accounts.username_from_email(info["email"]), None,
                email=info["email"], verified=True, google_sub=info["sub"],
                display_name=info.get("name"))
            # Redeem a code when one was required, or when the person
            # typed a valid one anyway, so the admin's counters stay honest.
            if need_invite or (c.invite_code
                               and accounts.invite_valid(c.invite_code)):
                accounts.redeem_invite(c.invite_code, username)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return _session_response(username, {"role": accounts.get_user(
        username)["role"]}, request=request)


# ------------------------------------------------------------- admin
class InviteIn(BaseModel):
    max_uses: int = 1
    note: str | None = None


@router.get("/admin/invites")
def admin_invites():
    return {"invites": accounts.list_invites(),
            "signup_url": f"{mailer.base_url()}/signup"}


@router.post("/admin/invites")
def admin_invite_create(c: InviteIn, request: Request):
    code = accounts.create_invite(request.state.user,
                                  max_uses=max(1, min(c.max_uses, 100)),
                                  note=c.note)
    return {"ok": True, "code": code,
            "url": f"{mailer.base_url()}/signup?invite={code}"}


@router.delete("/admin/invites/{code}")
def admin_invite_delete(code: str):
    accounts.delete_invite(code)
    return {"ok": True}


@router.get("/admin/users")
def admin_users():
    return {"users": accounts.list_users()}


@router.post("/admin/users/{username}/confirm")
def admin_confirm_user(username: str):
    """Mark the email verified without the link — for when the admin can
    vouch for the person (or mail can't reach them yet)."""
    u = accounts.get_user(username.lower())
    if not u:
        raise HTTPException(404, "No such user.")
    accounts.mark_verified(username.lower())
    return {"ok": True}


class RoleIn(BaseModel):
    role: str


@router.post("/admin/users/{username}/role")
def admin_set_role(username: str, c: RoleIn):
    try:
        accounts.set_role(username.lower(), c.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.delete("/admin/users/{username}")
def admin_delete_user(username: str, request: Request):
    """Remove an account and all its data (watchlist, portfolio, alerts,
    notes, sessions...). Admin only via ADMIN_PATHS. You cannot delete
    yourself or the last admin."""
    try:
        removed = accounts.delete_user(username, request.state.user)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "removed": removed}


# ------------------------------------------------------------- telegram
@router.post("/telegram/link-code")
def telegram_link_code(request: Request):
    from app.alerts import telegram_bot
    bot = telegram_bot.bot_username()
    if not bot:
        raise HTTPException(503, "Telegram bot isn't configured on this "
                                 "server (TELEGRAM_BOT_TOKEN).")
    code = accounts.telegram_link_code(request.state.user)
    return {"ok": True, "code": code, "bot": bot,
            "url": f"https://t.me/{bot}?start={code}",
            "expires_min": accounts.TG_CODE_TTL_MIN}


@router.get("/telegram/status")
def telegram_status(request: Request):
    from app.alerts import telegram_bot
    link = accounts.telegram_chat_for(request.state.user)
    return {"configured": bool(telegram_bot.bot_username()),
            "bot": telegram_bot.bot_username(),
            "linked": bool(link),
            "tg_username": link["tg_username"] if link else None,
            "linked_at": link["linked_at"] if link else None}


@router.delete("/telegram/link")
def telegram_unlink(request: Request):
    accounts.telegram_unlink(username=request.state.user)
    return {"ok": True}
