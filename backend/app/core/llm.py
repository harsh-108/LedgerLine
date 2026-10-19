"""
One LLM gateway for the whole app (AI analyst + English screener).

Why this exists: the analyst and nlp.py each used to talk to Groq on
their own. Groq's free tier is limited by TOKENS per minute, and the
analyst's tool-calling loop sends the full tool schema on every round —
so one or two questions burn the minute's budget and everything 429s.

OpenRouter's free tier is limited by REQUESTS per day instead (no token
cap), which suits a tool loop far better. So the default chain is now:

    custom (LLM_URL)  ->  openrouter  ->  groq  ->  groq-alt  ->  gemini

Each provider is only in the chain if its key is present in .env.
Configure in .env:

    OPENROUTER_API_KEY=sk-or-...        free at openrouter.ai/keys
    OPENROUTER_MODELS=openrouter/free   comma list, tried in order.
                                        "openrouter/free" auto-picks a
                                        free model that supports tools.
                                        Pin e.g. a specific ":free" model
                                        if you prefer, see the readme.
    OPENROUTER_DAILY_LIMIT=50           50 = no credits ever bought;
                                        1000 once you've bought $10 once.
    GROQ_API_KEY / GROQ_MODEL / GROQ_MODEL_ALT
    GEMINI_API_KEY / GEMINI_MODEL
    LLM_URL + LLM_API_KEY + LLM_MODEL   any OpenAI-compatible endpoint
    LLM_PROVIDER_ORDER=openrouter,groq,groq-alt,gemini   (optional)

Failover: a provider that errors is benched for FAIL_COOLDOWN_SEC; a 429
benches it for the Retry-After it asked for. When every provider 429s
with a short hint, we wait once and retry the chain. The per-provider
daily request counter is persisted to data/llm_usage.json so a server
restart doesn't forget how much of today's OpenRouter quota is gone.
"""

import datetime as _dt
import json
import re
import threading
import time

import requests

from app.core import envutil, paths

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/openai/"
              "chat/completions")

FAIL_COOLDOWN_SEC = 120
# Strongest first: Gemini (when its key is set) follows tool-use and the
# data rules most reliably; OpenRouter's free models are the last resort.
# LLM_PROVIDER_ORDER in .env overrides this.
DEFAULT_ORDER = ["custom", "gemini", "groq", "groq-alt", "openrouter"]
USAGE_FILE = paths.DATA_DIR / "llm_usage.json"

_down_until = {}                 # provider name -> unix time retry allowed
_lock = threading.Lock()
_usage = None                    # {"day": "YYYY-MM-DD", "counts": {name: n}}


# ------------------------------------------------------------------ usage
def _today():
    # OpenRouter's free-model day resets at midnight UTC.
    return _dt.datetime.utcnow().date().isoformat()


def _load_usage():
    global _usage
    if _usage is not None:
        return _usage
    try:
        with open(USAGE_FILE) as f:
            _usage = json.load(f)
    except Exception:
        _usage = {"day": _today(), "counts": {}}
    return _usage


def _bump(name):
    with _lock:
        u = _load_usage()
        if u.get("day") != _today():
            u.update(day=_today(), counts={})
        u["counts"][name] = u["counts"].get(name, 0) + 1
        try:
            with open(USAGE_FILE, "w") as f:
                json.dump(u, f)
        except Exception:
            pass


def usage_today():
    """{provider: requests made today (UTC)} — for the status endpoint."""
    with _lock:
        u = _load_usage()
        if u.get("day") != _today():
            return {}
        return dict(u["counts"])


# -------------------------------------------------------------- providers
def _daily_limit(name):
    if name == "openrouter":
        try:
            return int(envutil.get("OPENROUTER_DAILY_LIMIT", "50"))
        except ValueError:
            return 50
    return None


def providers():
    """Ordered provider chain, built from whatever keys .env has."""
    by_name = {}
    if envutil.get("LLM_URL") and envutil.get("LLM_API_KEY"):
        by_name["custom"] = [{
            "name": "custom", "url": envutil.get("LLM_URL"),
            "key": envutil.get("LLM_API_KEY"),
            "model": envutil.get("LLM_MODEL", "openai/gpt-oss-120b")}]
    if envutil.get("OPENROUTER_API_KEY"):
        models = [m.strip() for m in
                  envutil.get("OPENROUTER_MODELS",
                              envutil.get("OPENROUTER_MODEL",
                                          "openrouter/free")).split(",")
                  if m.strip()]
        # Every OpenRouter model shares ONE daily request budget, so they
        # all report as provider "openrouter" for usage counting; each
        # model is still its own failover step (a free model can be
        # overloaded upstream while another is fine).
        by_name["openrouter"] = [{
            "name": "openrouter", "model": m, "url": OPENROUTER_URL,
            "key": envutil.get("OPENROUTER_API_KEY"),
            "headers": {"HTTP-Referer": "http://localhost:8000",
                        "X-Title": "Watchlist Tracker"}} for m in models]
    if envutil.get("GROQ_API_KEY"):
        by_name["groq"] = [{
            "name": "groq", "url": GROQ_URL,
            "key": envutil.get("GROQ_API_KEY"),
            "model": envutil.get("GROQ_MODEL", "openai/gpt-oss-120b")}]
        # Groq limits are PER MODEL — a second model is a fresh bucket.
        by_name["groq-alt"] = [{
            "name": "groq-alt", "url": GROQ_URL,
            "key": envutil.get("GROQ_API_KEY"),
            "model": envutil.get("GROQ_MODEL_ALT", "openai/gpt-oss-20b")}]
    if envutil.get("GEMINI_API_KEY"):
        by_name["gemini"] = [{
            "name": "gemini", "url": GEMINI_URL,
            "key": envutil.get("GEMINI_API_KEY"),
            "model": envutil.get("GEMINI_MODEL", "gemini-3.5-flash")}]

    order = [s.strip() for s in
             envutil.get("LLM_PROVIDER_ORDER", ",".join(DEFAULT_ORDER))
             .split(",") if s.strip()]
    # LLM_PROVIDER_ORDER is authoritative when set: a provider left out of
    # the list is excluded even if its key exists. Unset -> default order.
    chain = []
    for name in order:
        chain.extend(by_name.get(name, []))
    return chain


def available():
    return bool(providers())


def describe():
    """Human-readable chain + today's usage, for the UI status line."""
    use = usage_today()
    out = []
    seen = set()
    for p in providers():
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        lim = _daily_limit(p["name"])
        entry = {"name": p["name"], "model": p["model"],
                 "used_today": use.get(p["name"], 0)}
        if lim:
            entry["daily_limit"] = lim
        benched = _down_until.get(p["name"], 0) - time.time()
        if benched > 0:
            entry["benched_for_sec"] = int(benched)
        out.append(entry)
    return out


# --------------------------------------------------------------- the call
def _err_detail(resp):
    try:
        j = resp.json()
        if isinstance(j, list) and j:           # Gemini wraps in a list
            j = j[0]
        err = j.get("error", j) if isinstance(j, dict) else {}
        if isinstance(err, str):
            return err[:200]
        return (err.get("message") or "")[:200]
    except Exception:
        try:
            return (resp.text or "")[:200]
        except Exception:
            return ""


def complete(messages, tools=None, temperature=0.3, max_tokens=1800,
             timeout=60):
    """Try each provider in order; fail over on any error.
    Returns (assistant_message_dict, provider_name).
    Raises RuntimeError with the per-provider reasons if all fail."""
    chain = providers()
    if not chain:
        raise RuntimeError("no LLM provider configured")

    for attempt in (0, 1):
        now = time.time()
        ready = [p for p in chain if now >= _down_until.get(p["name"], 0)]
        if not ready:                     # all benched — oldest first
            ready = sorted(chain,
                           key=lambda p: _down_until.get(p["name"], 0))
        use = usage_today()
        errors, waits = [], []
        # Providers still benched from an earlier failure are skipped;
        # say so, otherwise they vanish from the error message entirely.
        for p in chain:
            if p not in ready:
                left = max(0, int(_down_until.get(p["name"], 0) - now))
                errors.append(f"{p['name']} ({p['model']}): skipped, "
                              f"benched for {left}s after an earlier error")
        for p in ready:
            lim = _daily_limit(p["name"])
            if lim and use.get(p["name"], 0) >= lim:
                errors.append(f"{p['name']}: daily request budget "
                              f"({lim}) used up — resets 00:00 UTC")
                continue
            body = {"model": p["model"], "temperature": temperature,
                    "max_tokens": max_tokens, "messages": messages}
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"
            headers = {"Authorization": f"Bearer {p['key']}",
                       "Content-Type": "application/json"}
            headers.update(p.get("headers", {}))
            try:
                _bump(p["name"])
                resp = requests.post(p["url"], headers=headers, json=body,
                                     timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                # OpenRouter can return HTTP 200 with an error body when
                # the upstream provider failed mid-route.
                if isinstance(data, dict) and data.get("error") \
                        and not data.get("choices"):
                    raise RuntimeError(
                        (data["error"].get("message")
                         if isinstance(data["error"], dict)
                         else str(data["error"]))[:200])
                msg = _normalise(data["choices"][0]["message"])
                # "length" = the answer hit max_tokens and is cut off.
                # Reasoning models (gpt-oss, Gemini thinking) spend part of
                # max_tokens thinking first, so callers check this rather
                # than trusting a half answer.
                msg["finish_reason"] = data["choices"][0].get("finish_reason")
                _down_until.pop(p["name"], None)
                return msg, f"{p['name']}:{p['model']}"
            except requests.exceptions.HTTPError as e:
                code = getattr(e.response, "status_code", "?")
                detail = _err_detail(e.response)
                errors.append(f"{p['name']} ({p['model']}): HTTP {code} "
                              f"{detail}".strip())
                if code == 429:
                    ra = None
                    try:
                        ra = float(e.response.headers.get("retry-after"))
                    except Exception:
                        pass
                    if ra is None:            # Groq puts it in the text
                        # Parse the FULL body: _err_detail truncates to
                        # 200 chars and usually cuts the hint off.
                        try:
                            raw = e.response.text or ""
                        except Exception:
                            raw = detail
                        m = re.search(r"try again in (?:(\d+)h)?"
                                      r"(?:(\d+)m)?([\d.]+)s", raw)
                        if m:
                            h, mi, s = m.groups()
                            ra = (int(h or 0) * 3600 + int(mi or 0) * 60
                                  + float(s))
                    waits.append(min(ra, 30.0) if ra else 20.0)
                    _down_until[p["name"]] = time.time() + (
                        ra or FAIL_COOLDOWN_SEC)
                    continue
            except Exception as e:
                errors.append(f"{p['name']} ({p['model']}): {e}")
            _down_until[p["name"]] = time.time() + FAIL_COOLDOWN_SEC

        if attempt == 0 and waits and len(waits) == len(ready) \
                and min(waits) <= 30.0:
            time.sleep(min(waits) + 1.0)
            continue
        raise RuntimeError("All LLM providers failed — " +
                           " | ".join(errors))


def _normalise(msg):
    """Different free models are sloppy about the tool-call shape; make
    it match what the analyst loop expects (arguments as a JSON string,
    every call with an id)."""
    calls = msg.get("tool_calls") or []
    fixed = []
    for i, tc in enumerate(calls):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, (dict, list)):
            args = json.dumps(args)
        fixed.append({"id": tc.get("id") or f"call_{i}",
                      "type": "function",
                      "function": {"name": fn.get("name", ""),
                                   "arguments": args or "{}"}})
    if fixed:
        msg["tool_calls"] = fixed
    else:
        msg.pop("tool_calls", None)
    if msg.get("content") is None:
        msg["content"] = ""
    return msg


def setup_hint():
    return ("No LLM key in .env — add OPENROUTER_API_KEY (free at "
            "openrouter.ai/keys) and/or GROQ_API_KEY / GEMINI_API_KEY.")
