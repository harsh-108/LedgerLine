"""
Live-ish quotes layer with a provider abstraction.

Provider 1 (works today, zero setup): Yahoo fast quotes — delayed
~15 minutes, fine for an intraday glance, useless for scalping.

Provider 2 (real-time, needs YOUR Angel One account): SmartAPI adapter.
Written against Angel One's documented smartapi-python SDK but NOT
testable without live credentials — treat it as a starting template,
expect to debug the login handshake once with your own keys.

To activate SmartAPI:
    pip install smartapi-python pyotp
    .env:
        SMARTAPI_KEY=...        (from smartapi.angelbroking.com)
        SMARTAPI_CLIENT=...     (your client code)
        SMARTAPI_PIN=...
        SMARTAPI_TOTP_SECRET=...  (the QR secret from enabling TOTP)
Security note: these credentials can place orders on your account.
Keep .env out of git, and prefer creating a market-data-only app key.
"""

from app.core import envutil

try:
    import yfinance as yf
except ImportError:      # pragma: no cover
    yf = None


# ------------------------------------------------------- provider: yahoo
def yahoo_quotes(symbols):
    """{symbol: (last_price, prev_close)} — delayed, but free and instant."""
    out = {}
    if yf is None:
        return out
    for s in symbols:
        try:
            fi = yf.Ticker(s).fast_info
            last = fi.get("last_price") or fi.get("lastPrice")
            prev = fi.get("previous_close") or fi.get("previousClose")
            if last:
                out[s] = (float(last), float(prev) if prev else None)
        except Exception:
            continue
    return out


# ---------------------------------------------------- provider: smartapi
def smartapi_configured():
    return all(envutil.get(k) for k in
               ("SMARTAPI_KEY", "SMARTAPI_CLIENT", "SMARTAPI_PIN",
                "SMARTAPI_TOTP_SECRET"))


def smartapi_quotes(symbols):
    """Real-time LTP via Angel One SmartAPI. UNTESTED TEMPLATE — requires
    your credentials, and Angel One's instrument-token mapping.
    Raises RuntimeError with guidance on any failure."""
    if not smartapi_configured():
        raise RuntimeError("SmartAPI credentials missing in .env — see "
                           "live.py header for the four required keys.")
    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError:
        raise RuntimeError("Run: pip install smartapi-python pyotp")

    api = SmartConnect(api_key=envutil.get("SMARTAPI_KEY"))
    totp = pyotp.TOTP(envutil.get("SMARTAPI_TOTP_SECRET")).now()
    session = api.generateSession(
        envutil.get("SMARTAPI_CLIENT"), envutil.get("SMARTAPI_PIN"), totp
    )
    if not session.get("status"):
        raise RuntimeError(f"SmartAPI login failed: {session.get('message')}")

    # SmartAPI needs its own instrument tokens; reuse smartapi_source's
    # scrip master (in-process maps + weekly disk cache).
    from app.data_sources.smartapi_source import resolve_token

    out = {}
    for s in symbols:
        found = resolve_token(s)
        if not found:
            continue
        exch, token = found
        base = s.split(".")[0].upper()
        tradingsymbol = base + "-EQ" if exch == "NSE" else base
        try:
            ltp = api.ltpData(exch, tradingsymbol, token)
            if ltp.get("status"):
                out[s] = (float(ltp["data"]["ltp"]), None)
        except Exception:
            continue
    return out


def get_quotes(symbols):
    """Best available provider. Returns (quotes_dict, provider_name)."""
    if smartapi_configured():
        try:
            return smartapi_quotes(symbols), "Angel One SmartAPI (real-time)"
        except Exception:
            pass  # any SmartAPI failure (network, payload) falls to yahoo
    return yahoo_quotes(symbols), "Yahoo (delayed ~15 min)"
