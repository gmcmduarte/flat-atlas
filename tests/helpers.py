"""Shared test helpers (importable as ``helpers``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

FAKE_OPENALEX_KEY = "oa-key-SECRET-0123456789"  # gitleaks:allow (fake test value)
FAKE_EMAIL = "tester@example.org"


class FakeClock:
    """Monotonic clock and wall clock that only move when ``sleep`` is called."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.start = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.t - 1000.0)

    def advance(self, **kwargs: float) -> None:
        self.t += timedelta(**kwargs).total_seconds()
