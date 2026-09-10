"""Utility functions for logging and retry logic."""

import asyncio
import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from rich.console import Console
from rich.logging import RichHandler
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

console = Console()

T = TypeVar("T")


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    """Set up logging with both file and console handlers."""
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"sec_connector_{datetime.now():%Y%m%d_%H%M%S}.log"

    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, show_time=False, show_path=False),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logger = logging.getLogger("sec_connector")
    logger.setLevel(level)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(f"sec_connector.{name}")


def retry_with_backoff(
    max_attempts: int = 5,
    min_wait: float = 4.0,
    max_wait: float = 60.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Create a retry decorator with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        reraise=True,
    )


class RateLimiter:
    """Serialize admissions with monotonic pacing, without a token burst."""

    def __init__(self, rate: float):
        """Initialize rate limiter.

        Args:
            rate: Maximum requests per second
        """
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Rate must be a finite positive number")
        self.rate = rate
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def acquire(self) -> None:
        """Admit one request; concurrent callers cannot reserve the same slot."""
        async with self._lock:
            while (delay := self._next_request - time.monotonic()) > 0:
                await asyncio.sleep(delay)
            self._next_request = time.monotonic() + self._interval


def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to be filesystem-safe."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to maximum length with suffix."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
