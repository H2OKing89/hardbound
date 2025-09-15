# hardbound/utils/timing.py
"""
Timing decorator for automatic start/complete event logging
"""
import time
from functools import wraps

from .logging import get_logger


def log_step(event_base: str):
    """
    Decorator to automatically emit start/complete events with timing.

    @log_step("linker.plan") emits:
      - event: "linker.plan_start"
      - event: "linker.plan_complete" with duration_ms

    Args:
        event_base: Base event name (e.g., "linker.plan")

    Example:
        @log_step("linker.plan")
        def plan_and_link(...):
            ...
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            log = get_logger(fn.__module__)
            log.info(f"{event_base}_start")
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                dt = (time.perf_counter() - t0) * 1000
                log.info(f"{event_base}_complete", took_ms=round(dt, 3))

        return wrapper

    return decorator
