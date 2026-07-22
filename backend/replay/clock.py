"""Replay clock. The single authority for 'now' during a replay. Advances strictly forward.
Every replay-mode read of evidence goes through leakage_guard against this clock, so no component
can ever see data timestamped after the simulated moment (Truth Constraint #4).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator


class ReplayClock:
    def __init__(self, start: datetime, end: datetime, step_hours: float = 6.0):
        self.start = _aware(start)
        self.end = _aware(end)
        self.step_hours = step_hours
        self._now = self.start

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, hours: float | None = None) -> datetime:
        from datetime import timedelta
        self._now = min(self._now + timedelta(hours=hours or self.step_hours), self.end)
        return self._now

    def ticks(self) -> Iterator[datetime]:
        """Yield each simulated timestamp from start to end. Monotonic, no going back."""
        self._now = self.start
        yield self._now
        while self._now < self.end:
            yield self.advance()

    def done(self) -> bool:
        return self._now >= self.end


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
