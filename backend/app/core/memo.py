"""
Cache for results that only change when the stored data changes.

The data refreshes about once a day, yet every stock page, portfolio,
backtest and fund view used to rebuild the same checklist, model, ranking
and chart series from scratch: tens of milliseconds each on a PC, several
times that on the phone that serves the app. Results here are reused until
database.data_version() moves (every writer of prices, fundamentals,
watchlists, holdings... bumps it), with a time limit as a safety net in case
a write ever slips past the version.

    value = memo.cached(("checklist", symbol, user), lambda: compute(...))

Values are handed out as copies, so a caller that changes what it got
cannot change what the next caller sees.
"""

import copy
import threading
import time

from app.core import database as db

# Safety net only: every writer of the data these results come from bumps
# the data version, so entries are normally replaced the moment data
# changes. Long enough that the pages warmed after the evening refresh
# stay warm through the next day's use.
TTL_SECONDS = 6 * 60 * 60
MAX_ENTRIES = 1500          # a whole universe of checklists fits; then reset

from collections import OrderedDict  # noqa: E402

_store = OrderedDict()      # key -> (data_version, stored_at, value), LRU order
_limits = {}                # name -> most entries of that kind (big values)
_lock = threading.Lock()


def _copy(value):
    try:
        import pandas as pd
        if isinstance(value, (pd.DataFrame, pd.Series)):
            return value.copy()
    except ImportError:                                    # pragma: no cover
        pass
    if isinstance(value, (dict, list, tuple, set)):
        return copy.deepcopy(value)
    return value


def cached(key, compute, ttl=TTL_SECONDS, share=False):
    """share=True hands out the stored object itself, for large results the
    caller only reads (copying 2,500-point chart series on every hit would
    cost about as much as building them)."""
    give = (lambda v: v) if share else _copy
    version = db.data_version()       # read BEFORE computing: a write that
    hit = _store.get(key)             # lands mid-compute makes this stale
    if hit and hit[0] == version and time.time() - hit[1] < ttl:
        with _lock:
            if key in _store:
                _store.move_to_end(key)           # recently used
        return give(hit[2])
    value = compute()
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            _store.clear()
        _store[key] = (version, time.time(), value)
        _store.move_to_end(key)
        _trim(key)
    return give(value)


def _trim(key):
    """Keep at most _limits[name] entries of a big kind, dropping the least
    recently used (a phone has little memory to spare). Caller holds _lock."""
    name = key[0] if isinstance(key, tuple) and key else None
    cap = _limits.get(name)
    if not cap:
        return
    same = [k for k in _store if isinstance(k, tuple) and k and k[0] == name]
    for k in same[:max(0, len(same) - cap)]:
        _store.pop(k, None)


def _freeze(v):
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, set):
        return tuple(sorted(v))
    return v


def memoize(name, per_user=False, share=False, max_items=None):
    """Decorator form of cached(): the key is the function's arguments
    (plus the signed-in user when per_user, for results that depend on
    that user's watchlist or portfolio). max_items caps how many results of
    this kind are kept (for big values). fn.uncached is the original."""
    import functools
    if max_items:
        _limits[name] = max_items

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (name, _freeze(args), _freeze(kwargs),
                   user() if per_user else None)
            return cached(key, lambda: fn(*args, **kwargs), share=share)
        wrapper.uncached = fn
        return wrapper
    return deco


def clear():
    with _lock:
        _store.clear()


def user():
    """The signed-in user for keys of per-user results (their watchlist or
    portfolio changes the answer); None in background jobs."""
    return db.current_user.get()
