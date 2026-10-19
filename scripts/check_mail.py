#!/usr/bin/env python3
"""Send one test email through the app's mailer and show exactly what
Resend answered. Run from anywhere:

    python scripts/check_mail.py you@example.com

Reads the same .env the server does, so it tells you what the server sees.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core import envutil, mailer, paths  # noqa: E402

PASS, FAIL, WARN = "[ok]  ", "[FAIL]", "[warn]"


def show(key, secret=False):
    v = envutil.get(key)
    if v is None:
        print(f"{FAIL} {key} is empty or missing in {paths.ENV_FILE}")
        return None
    shown = (v[:6] + "…" + v[-3:]) if secret and len(v) > 12 else v
    print(f"{PASS} {key} = {shown!r}")
    if "#" in v and not secret:
        print(f"{WARN}   value contains '#': an inline comment leaked in? "
              f"Put comments on their own line.")
    return v


def main():
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print(__doc__)
        sys.exit(2)
    to = sys.argv[1].strip()
    print(f"env file: {paths.ENV_FILE} ({'found' if paths.ENV_FILE.exists() else 'MISSING'})")
    key = show("RESEND_API_KEY", secret=True)
    frm = show("MAIL_FROM")
    show("APP_BASE_URL")
    print(f"       AUTH_DEV_LINKS -> {'on' if mailer.dev_links() else 'off'}")
    if not key:
        sys.exit(1)
    if key and not key.startswith("re_"):
        print(f"{WARN} Resend keys start with 're_'; this one doesn't.")
    if frm and "resend.dev" in frm:
        print(f"{WARN} From is onboarding@resend.dev: Resend delivers that "
              f"ONLY to the address that owns your Resend account.")

    print(f"\nsending test mail to {to} …")
    ok, err = mailer.send(to, "Ledgerline mail check",
                          "If you can read this, outbound mail works.\n")
    if ok:
        print(f"{PASS} Resend accepted it. Check the inbox (and spam).")
        sys.exit(0)
    print(f"{FAIL} {err}")
    e = (err or "").lower()
    if "401" in e or "api key" in e or "invalid" in e:
        print("   -> the API key is wrong or has trailing junk. Re-copy it "
              "from resend.com/api-keys; make sure nothing follows it on "
              "the line.")
    elif "domain is not verified" in e or "not verified" in e:
        print("   -> MAIL_FROM uses a domain you haven't verified in Resend. "
              "Add the DNS records under Domains, or use "
              "onboarding@resend.dev while testing.")
    elif "own email address" in e or "testing emails" in e:
        print("   -> With onboarding@resend.dev you can only send to your own "
              "Resend account email. Verify a domain to send to others.")
    elif "403" in e:
        print("   -> 403: the key may be restricted (sending access / domain "
              "scope). Create a full-access key.")
    elif "timed out" in e or "connection" in e or "resolve" in e:
        print("   -> network: the server can't reach api.resend.com.")
    sys.exit(1)


if __name__ == "__main__":
    main()
