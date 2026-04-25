"""Cache utility for GSI mappings with time-based expiration."""

import threading
import time
from functools import wraps
from typing import Any, Callable, Optional

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)


class TimedCache:
    """Simple time-based cache for GSI mappings."""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self.cache = {}
        self.timestamps = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self.cache:
                return None
            if time.time() - self.timestamps[key] > self.ttl_seconds:
                del self.cache[key]
                del self.timestamps[key]
                logger.debug(f"Cache expired for key: {key}")
                return None
            logger.debug(f"Cache hit for key: {key}")
            return self.cache[key]

    def set(self, key: str, value: Any):
        with self._lock:
            self.cache[key] = value
            self.timestamps[key] = time.time()
            logger.debug(f"Cache set for key: {key}")

    def clear(self, key: Optional[str] = None):
        with self._lock:
            if key:
                self.cache.pop(key, None)
                self.timestamps.pop(key, None)
                logger.info(f"Cache cleared for key: {key}")
            else:
                self.cache.clear()
                self.timestamps.clear()
                logger.info("Entire cache cleared")

    def get_cache_info(self) -> dict:
        with self._lock:
            current_time = time.time()
            valid_entries = sum(
                1 for ts in self.timestamps.values()
                if current_time - ts <= self.ttl_seconds
            )
            return {
                "total_entries": len(self.cache),
                "valid_entries": valid_entries,
                "expired_entries": len(self.cache) - valid_entries,
                "ttl_seconds": self.ttl_seconds,
            }


gsi_mappings_cache = TimedCache(ttl_seconds=4 * 3600)
gi2_mappings_cache = TimedCache(ttl_seconds=4 * 3600)


def clear_all_caches():
    logger.info("Clearing all GSI mapping caches at job startup")
    gsi_mappings_cache.clear()
    gi2_mappings_cache.clear()
    logger.info("All GSI mapping caches cleared")


def get_all_cache_info():
    return {
        "gsi_mappings_cache": gsi_mappings_cache.get_cache_info(),
        "gi2_mappings_cache": gi2_mappings_cache.get_cache_info(),
    }


def cached_gsi_query(ttl_seconds: int = 4 * 3600):
    """Decorator retained for compatibility; caching currently disabled."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger.info("CACHE DISABLED - executing GSI query directly")
            return func(self, *args, **kwargs)

        wrapper.cache_clear = lambda: logger.info("Cache clear called")
        wrapper.cache_info = lambda: {"status": "disabled"}
        return wrapper

    return decorator


def cached_gi2_query(ttl_seconds: int = 4 * 3600):
    """Decorator retained for compatibility; caching currently disabled."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger.info("CACHE DISABLED - executing GI2 query directly")
            return func(self, *args, **kwargs)

        wrapper.cache_clear = lambda: logger.info("Cache clear called")
        wrapper.cache_info = lambda: {"status": "disabled"}
        return wrapper

    return decorator
