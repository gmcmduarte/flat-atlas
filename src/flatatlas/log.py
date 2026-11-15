"""Logging: secret redaction, stderr plus file output, and a progress/ETA helper."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

_secrets: set[str] = set()
_MIN_SECRET_LENGTH = 4
_HANDLER_ATTR = "_flatatlas_handler"


def register_secret(value: str) -> None:
    """Make ``redact()`` and the log formatter hide ``value`` from now on."""
    if len(value) >= _MIN_SECRET_LENGTH:
        _secrets.add(value)


def redact(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, "***")
    return text


class RedactingFormatter(logging.Formatter):
    """Formats a record and then hides every registered secret, tracebacks included."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(
    logs_dir: Path | None = None,
    *,
    level: int = logging.INFO,
    stream: TextIO | None = None,
) -> Path | None:
    """Log to stderr and, when ``logs_dir`` is given, to ``flatatlas-YYYYMMDD.log``.

    Safe to call again: handlers added by an earlier call are replaced. Returns the log file.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_ATTR, False):
            root.removeHandler(handler)
            handler.close()

    formatter = RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(stream or sys.stderr)]
    log_file: Path | None = None
    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"flatatlas-{datetime.now(UTC):%Y%m%d}.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_ATTR, True)
        root.addHandler(handler)
    root.setLevel(level)
    return log_file


class Progress:
    """Logs ``label: done/total (rate/s, ETA ...)`` every ``every`` items."""

    def __init__(
        self,
        label: str,
        total: int | None = None,
        *,
        every: int = 100,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        self.label = label
        self.total = total
        self.every = every
        self.done = 0
        self._clock = clock
        self._start = clock()
        self._log = logger or logging.getLogger("flatatlas.progress")

    def update(self, n: int = 1) -> None:
        before = self.done
        self.done += n
        if self.done // self.every > before // self.every:
            self._log.info(self.message())

    def finish(self) -> None:
        self._log.info("%s (finished)", self.message())

    def message(self) -> str:
        elapsed = max(self._clock() - self._start, 1e-9)
        rate = self.done / elapsed
        if self.total:
            eta = (self.total - self.done) / rate if rate > 0 else float("inf")
            return (
                f"{self.label}: {self.done}/{self.total} ({rate:.1f}/s, ETA {_format_seconds(eta)})"
            )
        return f"{self.label}: {self.done} ({rate:.1f}/s)"


def _format_seconds(seconds: float) -> str:
    if seconds == float("inf"):
        return "unknown"
    seconds = int(max(seconds, 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"
