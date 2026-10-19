"""
"Continue with Google" — verifies the ID token the Google Identity
Services button hands the browser, server-side, against Google's
tokeninfo endpoint. No client secret is needed for this flow.

.env:
    GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com

Setup in Google Cloud Console: APIs & Services -> Credentials -> Create
OAuth client ID -> Web application. Add every origin the app is served
from to "Authorized JavaScript origins" (http://localhost:8000, your
tunnel or real domain). No redirect URIs are needed for the button flow.
"""
import requests

from app.core import envutil

TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def configured():
    return bool(envutil.get("GOOGLE_CLIENT_ID"))


def client_id():
    return envutil.get("GOOGLE_CLIENT_ID") or ""


def verify_id_token(credential):
    """Return {'sub','email','name','email_verified'} or raise ValueError."""
    if not configured():
        raise ValueError("Google sign-in is not configured.")
    try:
        r = requests.get(TOKENINFO, params={"id_token": credential},
                         timeout=10)
    except Exception as e:
        raise ValueError(f"Could not reach Google: {e}")
    if r.status_code != 200:
        raise ValueError("Google rejected the sign-in token.")
    info = r.json()
    if info.get("aud") != client_id():
        raise ValueError("Token was issued for a different app.")
    if info.get("iss") not in ISSUERS:
        raise ValueError("Unexpected token issuer.")
    if str(info.get("email_verified", "false")).lower() != "true":
        raise ValueError("Google reports this email as unverified.")
    return {"sub": info["sub"], "email": info["email"].lower(),
            "name": info.get("name") or info.get("given_name"),
            "email_verified": True}
