"""Daily spend ledger per source (PLAN §5.1 budget guard).

The ledger is a small JSON file next to the source's cache, so it survives restarts and is
shared by every process using the same data root. Amounts are integer micro-dollars to avoid
float drift. The day is the UTC date.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_MICRO = 1_000_000
_KEEP_DAYS = 30


class SourceError(RuntimeError):
    """A source could not be reached or answered with an error."""


class BudgetExhausted(SourceError):  # noqa: N818 - name is part of the public contract
    """The daily budget would be exceeded. Relaunch the job after midnight UTC."""


def utc_day(now: datetime) -> str:
    return now.astimezone(UTC).date().isoformat()


class BudgetLedger:
    def __init__(
        self,
        path: Path,
        daily_budget_usd: float | None,
        *,
        now: Callable[[], datetime],
        source: str = "source",
    ) -> None:
        self.path = path
        self.source = source
        self._now = now
        self.limit_micro = None if daily_budget_usd is None else round(daily_budget_usd * _MICRO)

    def _load(self) -> dict[str, int]:
        try:
            return {str(k): int(v) for k, v in json.loads(self.path.read_text()).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save(self, data: dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True))
        os.replace(tmp, self.path)

    def spent_today_usd(self) -> float:
        return self._load().get(utc_day(self._now()), 0) / _MICRO

    def charge(self, cost_usd: float) -> None:
        """Record ``cost_usd`` or raise ``BudgetExhausted`` without recording it."""
        micro = round(cost_usd * _MICRO)
        if micro <= 0 or self.limit_micro is None:
            return
        day = utc_day(self._now())
        data = self._load()
        spent = data.get(day, 0)
        if spent + micro > self.limit_micro:
            raise BudgetExhausted(
                f"{self.source}: daily budget ${self.limit_micro / _MICRO:.4f} would be exceeded "
                f"(spent ${spent / _MICRO:.4f} on {day} UTC). Relaunch after midnight UTC."
            )
        data[day] = spent + micro
        for old in sorted(data)[:-_KEEP_DAYS]:
            del data[old]
        self._save(data)
