"""Diagnose NSE access step by step.

    python scripts/check_nse.py [SYMBOL]

Prints which HTTP client is in use and the status of each step, so you can
tell an Akamai TLS-fingerprint block or a corporate proxy from a code
problem. Run from the project root.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.data_sources import nse_source as nse  # noqa: E402

sym = (sys.argv[1] if len(sys.argv) > 1 else "WIPRO").upper()

s = nse._new_client()
print(f"0. client: {nse._client_name}"
      + ("" if nse._client_name == "curl_cffi"
         else "  !! plain requests — NSE blocks its TLS fingerprint; "
              "run: pip install curl_cffi"))

print("1. homepage (cookie warm-up)")
try:
    r = s.get(nse._BASE + "/", timeout=12)
    try:
        names = sorted(list(s.cookies.keys()))
    except Exception:
        names = []
    print(f"   HTTP {r.status_code}, {len(r.content)} bytes, "
          f"cookies: {', '.join(names) or 'NONE'}")
    if r.status_code == 403 and "Access Denied" in r.text:
        print("   !! Akamai 'Access Denied' page. With curl_cffi this means "
              "your network (office proxy / VPN) is being rejected — retry "
              "on a phone hotspot.")
    elif "nsit" not in names and "nseappid" not in names:
        print("   !! no nsit/nseappid cookie — something other than NSE "
              "answered")
except Exception as e:
    print(f"   FAILED: {e.__class__.__name__}: {e}")
    sys.exit(1)

print(f"2. /api/quote-equity?symbol={sym}")
try:
    r = s.get(f"{nse._BASE}/api/quote-equity", params={"symbol": sym},
              timeout=12)
    ctype = (r.headers.get("content-type", "") or "").split(";")[0]
    print(f"   HTTP {r.status_code}, content-type: {ctype or 'unknown'}")
    if r.status_code < 400 and "json" in ctype:
        info = r.json().get("priceInfo") or {}
        print(f"   lastPrice={info.get('lastPrice')} "
              f"previousClose={info.get('previousClose')}")
    else:
        print("   body starts:", r.text[:160].replace("\n", " "))
except Exception as e:
    print(f"   FAILED: {e.__class__.__name__}: {e}")

print("3. daily bhavcopy (what the sync now uses first)")
bdate, rows = nse.fetch_bhavcopy()
if rows:
    row = rows.get(sym)
    print(f"   OK: {bdate}, {len(rows)} symbols; {sym}: "
          f"{row if row else 'not present (wrong ticker or not EQ series)'}")
else:
    print(f"   FAILED: {nse.last_error}")

print("4. per-symbol fallback through fetch_quote()")
q = nse.fetch_quote(sym)
print("   ", q if q else f"None — {nse.last_error}")
