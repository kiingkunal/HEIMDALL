"""Leakage guard. The honesty backbone of the replay (Truth Constraint #4: future-data leakage is
prohibited AND tested for). Any replay component that reads an evidence record must pass it through
guard_row/guard_rows against the current sim clock. If a record's timestamp is after the clock,
that is future data leaking into the past — we RAISE, loudly, rather than silently cheat the backtest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


class LeakageError(RuntimeError):
    """Raised when a replay component reads data timestamped after the simulation clock."""


def _aware(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def guard_timestamp(ts: datetime | str, sim_now: datetime, *, context: str = "") -> None:
    """Raise LeakageError if ts is strictly after sim_now."""
    ts_a = _aware(ts)
    now_a = _aware(sim_now)
    if ts_a > now_a:
        raise LeakageError(
            f"future-data leakage{(' in ' + context) if context else ''}: "
            f"record@{ts_a.isoformat()} is after sim_clock@{now_a.isoformat()}"
        )


def guard_row(row: dict[str, Any], sim_now: datetime, *,
              ts_field: str = "timestamp", context: str = "") -> dict[str, Any]:
    """Validate one record and return it unchanged if safe. Raises on leakage."""
    if ts_field not in row:
        raise LeakageError(f"row missing timestamp field '{ts_field}' — cannot verify leakage safety")
    guard_timestamp(row[ts_field], sim_now, context=context or row.get("id", ""))
    return row


def guard_rows(rows: Iterable[dict[str, Any]], sim_now: datetime, *,
               ts_field: str = "timestamp", context: str = "") -> list[dict[str, Any]]:
    """Filter to records at-or-before sim_now, RAISING if any row is malformed. Use this to select
    the visible evidence window at a given tick — it both filters AND certifies no leakage slips in.
    """
    out = []
    for row in rows:
        if ts_field not in row:
            raise LeakageError(f"row missing timestamp field '{ts_field}'")
        ts = _aware(row[ts_field])
        if ts <= _aware(sim_now):
            out.append(row)
    return out
