"""Tiny .env loader + config access. Never commit .env to git.

Accepted line forms (all equivalent):
    KEY=value
    KEY = value
    export KEY=value
    KEY="value with spaces"        KEY='single quoted'
    KEY=value   # trailing comment (stripped unless the value is quoted)
    # whole-line comment
"""
import os

_loaded = False


def _parse_value(raw):
    v = raw.strip()
    # Quoted: keep everything inside the quotes verbatim (comments included).
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    # Unquoted: drop an inline "# comment" (only when the # follows whitespace
    # or starts the value, so a bare '#' inside a URL fragment survives).
    if v.startswith("#"):
        return ""
    for i in range(1, len(v)):
        if v[i] == "#" and v[i - 1] in " \t":
            return v[:i].rstrip()
    return v


def _load_dotenv():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from app.core import paths
        with open(paths.ENV_FILE, encoding="utf-8-sig") as f:   # -sig eats a BOM
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                k, v = line.split("=", 1)
                k = k.strip()
                if not k:
                    continue
                os.environ.setdefault(k, _parse_value(v))
    except FileNotFoundError:
        pass


def get(key, default=None):
    _load_dotenv()
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return v
