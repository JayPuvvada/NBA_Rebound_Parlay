import time
import functools
import threading

def ttl_cache(seconds: float):
    """
    Thread-safe TTL cache decorator for memoizing function calls.
    Results expire after `seconds`.
    """
    def deco(fn):
        store = {}
        lock = threading.Lock()
        
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # We don't cache 'self' since it's the class instance.
            # Using function name and args/kwargs for the key.
            # Convert args to string or omit self if args[0] is instance of NBADataLoader
            cache_args = args[1:] if len(args) > 0 and hasattr(args[0], '__class__') and args[0].__class__.__name__ == 'NBADataLoader' else args
            
            # Serialize kwargs to a hashable tuple
            cache_kwargs = tuple(sorted(kwargs.items()))
            
            # Key ignores 'self' to avoid caching by object reference
            key = (fn.__name__, cache_args, cache_kwargs)
            now = time.time()
            
            with lock:
                hit = store.get(key)
                if hit and (now - hit[0]) < seconds:
                    return hit[1]
            
            # Cache miss, call function
            val = fn(*args, **kwargs)
            
            with lock:
                store[key] = (now, val)
            
            return val
            
        wrapper.invalidate = lambda: store.clear()
        return wrapper
    return deco
