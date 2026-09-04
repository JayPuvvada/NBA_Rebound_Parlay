"""Small, process-local TTL cache helpers."""

import copy
import functools
import threading
import time


def _freeze(value):
    """Convert common containers to a stable, hashable cache-key value."""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(item) for item in value))
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def _clone(value):
    """Do not let callers mutate a cached DataFrame/container by reference."""
    try:
        # pandas objects support a real deep copy.
        return value.copy(deep=True)
    except (AttributeError, TypeError):
        try:
            return copy.deepcopy(value)
        except Exception:
            return value


def _is_empty(value):
    if value is None:
        return True
    empty = getattr(value, "empty", None)
    if isinstance(empty, bool):
        return empty
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return len(value) == 0
    return False


def ttl_cache(seconds: float, *, cache_empty: bool = False, ttl_for_value=None):
    """Memoize calls with season-aware keys and per-key stampede protection.

    Empty values are intentionally not cached by default.  APIs for which an
    empty result is a verified success (such as an off-day schedule) can opt in.
    ttl_for_value can shorten retention for degraded results; zero skips caching.
    """
    if seconds <= 0:
        raise ValueError("TTL must be positive")

    def deco(fn):
        store = {}
        in_flight = {}
        lock = threading.RLock()

        def make_key(args, kwargs):
            if args and hasattr(args[0], "__dict__"):
                instance = args[0]
                token = getattr(instance, "_ttl_cache_token", None)
                if token is None:
                    token = object()
                    setattr(instance, "_ttl_cache_token", token)
                namespace = (
                    instance.__class__.__module__,
                    instance.__class__.__qualname__,
                    token,
                    getattr(instance, "season", None),
                )
                call_args = args[1:]
            else:
                namespace = None
                call_args = args
            return namespace, _freeze(call_args), _freeze(kwargs)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = make_key(args, kwargs)

            while True:
                now = time.monotonic()
                with lock:
                    # Opportunistic pruning prevents never-reused expired keys
                    # from accumulating for the lifetime of a web worker.
                    for expired_key, (expires_at, _) in list(store.items()):
                        if now >= expires_at:
                            del store[expired_key]
                    hit = store.get(key)
                    if hit is not None:
                        expires_at, cached_value = hit
                        if now < expires_at:
                            return _clone(cached_value)

                    waiter = in_flight.get(key)
                    if waiter is None:
                        waiter = threading.Event()
                        in_flight[key] = waiter
                        break

                waiter.wait()

            try:
                value = fn(*args, **kwargs)
                retention = seconds if ttl_for_value is None else ttl_for_value(value)
                if retention > 0 and (cache_empty or not _is_empty(value)):
                    with lock:
                        store[key] = (time.monotonic() + min(seconds, retention), _clone(value))
                return value
            finally:
                with lock:
                    event = in_flight.pop(key, None)
                    if event is not None:
                        event.set()

        def invalidate():
            with lock:
                store.clear()

        wrapper.invalidate = invalidate
        return wrapper

    return deco
