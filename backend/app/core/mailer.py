"""
Outbound email for verification and password-reset links.

Provider: Resend's HTTP API (https://resend.com), because the app may run
on a phone or a VPS with no mail server. Free tier covers a small app.

.env:
    RESEND_API_KEY=re_...
    MAIL_FROM="Ledgerline <noreply@yourdomain.in>"   (a verified domain;
                                  "onboarding@resend.dev" works for testing
                                  but only delivers to your own address)
    APP_BASE_URL=https://app.yourdomain.in            (used in the links)
    AUTH_DEV_LINKS=1   -> when no mail provider is configured, return the
                          link in the API response and print it to the log.
                          Development only; never set this in production.
"""
import logging

import requests

from app.core import envutil

log = logging.getLogger("mailer")
RESEND_URL = "https://api.resend.com/emails"


def configured():
    return bool(envutil.get("RESEND_API_KEY"))


def base_url():
    return (envutil.get("APP_BASE_URL") or "http://localhost:8000").rstrip("/")


def dev_links():
    return (envutil.get("AUTH_DEV_LINKS") or "").strip() in ("1", "true", "yes")


def send(to, subject, text):
    """Returns (ok, error|None). Never raises."""
    if not configured():
        return False, "email not configured (RESEND_API_KEY missing)"
    try:
        r = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {envutil.get('RESEND_API_KEY')}",
                     "Content-Type": "application/json"},
            json={"from": envutil.get("MAIL_FROM") or "onboarding@resend.dev",
                  "to": [to], "subject": subject, "text": text},
            timeout=15)
        if r.status_code in (200, 201):
            return True, None
        return False, f"mail provider error {r.status_code}: {r.text[:160]}"
    except Exception as e:
        return False, str(e)


def verification_email(to, username, link):
    return send(
        to, "Confirm your email",
        f"Hi {username},\n\nConfirm your email to activate your account:\n\n"
        f"{link}\n\nThe link is valid for 24 hours. If you didn't sign up, "
        f"ignore this message.\n")


def reset_email(to, username, link):
    return send(
        to, "Reset your password",
        f"Hi {username},\n\nReset your password with this link:\n\n{link}\n\n"
        f"It expires in one hour. If you didn't ask for this, ignore it; "
        f"your password stays the same.\n")
