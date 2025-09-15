# hardbound/utils/logging.py
"""
Structured logging with Rich console output and JSON file logging
Provides context binding for ASIN, title, volume, and job tracking
"""
from __future__ import annotations
import json
import logging
from logging import Logger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import structlog
from structlog.stdlib import LoggerFactory, add_log_level, filter_by_level
from structlog.processors import TimeStamper
from structlog.dev import ConsoleRenderer
from structlog.contextvars import (
    bind_contextvars,
    unbind_contextvars,
    merge_contextvars,
    clear_contextvars,
)

try:
    from rich.logging import RichHandler
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# ---- public helpers ---------------------------------------------------------

def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger bound to the app. Use .bind(asin="…") to add context.
    
    Example:
        log = get_logger(__name__)
        bound_log = log.bind(asin="{ASIN.B0ABC123}", title="Book Title")
        bound_log.info("processing.start")
    """
    base = structlog.get_logger(name or "hardbound")
    return base

def bind(**kw) -> None:
    """Bind key=value to the implicit context (thread/Task-local)."""
    bind_contextvars(**kw)

def unbind(*keys: str) -> None:
    """Remove keys from the implicit context."""
    unbind_contextvars(*keys)

def clear_context() -> None:
    """Clear all context variables."""
    clear_contextvars()

# ---- setup ------------------------------------------------------------------

def setup_logging(
    *,
    level: str = "INFO",
    file_enabled: bool = True,
    console_enabled: bool = True,
    json_file: bool = True,
    log_path: Path = Path("/mnt/cache/scripts/hardbound/logs/hardbound.log"),
    rotate_max_bytes: int = 10 * 1024 * 1024,
    rotate_backups: int = 5,
    rich_tracebacks: bool = True,
    show_path: bool = False,
) -> Logger:
    """
    Configure structlog + stdlib logging with:
      - Rich console (human readable)
      - Rotating JSON file (machine readable)
    Call this ONCE at program start (CLI entrypoint).
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        file_enabled: Enable file logging
        console_enabled: Enable console logging
        json_file: Use JSON format for file logs
        log_path: Path to log file
        rotate_max_bytes: Max bytes before rotation
        rotate_backups: Number of backup files to keep
        rich_tracebacks: Enable Rich traceback formatting
        show_path: Show file paths in Rich console output
        
    Returns:
        Configured stdlib logger for compatibility
    """
    # Ensure log directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Build stdlib handlers
    handlers: list[logging.Handler] = []

    if console_enabled:
        if _HAS_RICH:
            console_handler = RichHandler(  # type: ignore
                show_time=False,  # structlog handles timestamps
                rich_tracebacks=rich_tracebacks,
                show_path=show_path,
                markup=False,  # Avoid Rich markup conflicts
            )
            handlers.append(console_handler)
        else:
            # Fallback to standard StreamHandler if Rich not available
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logging.Formatter("%(message)s"))
            handlers.append(stream_handler)

    if file_enabled:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=rotate_max_bytes,
            backupCount=rotate_backups,
            encoding="utf-8",
        )
        # Plain formatter; structlog will render the message
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(file_handler)

    # Configure standard library root logger
    root_level = getattr(logging, level.upper(), logging.INFO)
    
    # Clear any existing handlers to avoid duplicates
    logging.getLogger().handlers.clear()
    
    # Configure basic logging
    logging.basicConfig(
        handlers=handlers, 
        level=root_level, 
        format="%(message)s"
    )

    # Configure structlog processors
    timestamper = TimeStamper(fmt="iso", utc=True)

    def json_renderer(logger, method_name, event_dict):
        """Render log events as JSON"""
        return json.dumps(event_dict, ensure_ascii=False, separators=(",", ":"))

    def console_renderer(logger, method_name, event_dict):
        """Render log events for console (Rich-friendly)"""
        # Use structlog's built-in console renderer for nice key=value formatting
        renderer = ConsoleRenderer()
        return renderer(logger, method_name, event_dict)

    # Choose renderer based on whether we want JSON files
    if json_file and file_enabled:
        final_renderer = json_renderer
    else:
        final_renderer = console_renderer

    # Import CallsiteParameterAdder for debugging
    from structlog.processors import CallsiteParameterAdder

    # Configure structlog
    structlog.configure(
        cache_logger_on_first_use=True,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=LoggerFactory(),
        processors=[
            # Filter by level first (performance optimization)
            filter_by_level,
            # Merge context variables (ASIN, title, volume, etc.)
            merge_contextvars,
            # Add log level to event dict
            add_log_level,
            # Add callsite information (filename, func_name, lineno) for debugging
            CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # Add timestamp
            timestamper,
            # Format stack info for exceptions
            structlog.processors.StackInfoRenderer(),
            # Format exception info
            structlog.processors.format_exc_info,
            # Final rendering step
            final_renderer,
        ],
    )

    # Return a conventional stdlib logger for compatibility
    return logging.getLogger("hardbound")

# ---- context helpers --------------------------------------------------------

def bind_audiobook_context(asin: str, title: str, volume: str, **extra) -> None:
    """
    Convenience function to bind common audiobook context.
    
    Args:
        asin: ASIN token (e.g., "{ASIN.B0ABC123}")
        title: Book title
        volume: Volume (e.g., "vol_01")
        **extra: Additional context to bind
    """
    context = {
        "asin": asin,
        "title": title,
        "volume": volume,
        **extra
    }
    bind_contextvars(**context)

def bind_operation_context(operation: str, job_id: Optional[str] = None, **extra) -> None:
    """
    Convenience function to bind operation context.
    
    Args:
        operation: Operation name (e.g., "link", "trim", "scan")
        job_id: Unique job identifier
        **extra: Additional context to bind
    """
    context = {
        "operation": operation,
        **extra
    }
    if job_id:
        context["job_id"] = job_id
    
    bind_contextvars(**context)

# ---- validation -------------------------------------------------------------

def validate_log_level(level: str) -> bool:
    """Validate that a log level string is valid."""
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    return level.upper() in valid_levels

def get_log_size(log_path: Path) -> int:
    """Get the current size of the log file in bytes."""
    try:
        return log_path.stat().st_size
    except (OSError, FileNotFoundError):
        return 0

def list_log_files(log_dir: Path) -> list[Path]:
    """List all log files in the log directory (including rotated ones)."""
    try:
        return list(log_dir.glob("hardbound.log*"))
    except (OSError, FileNotFoundError):
        return []