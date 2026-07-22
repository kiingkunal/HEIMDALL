"""Replay dataset loader. Reads the immutable 2025-standoff fixture and serves evidence + prices
strictly chronologically, every read certified by leakage_guard against the sim clock.

The loader is the ONLY door to replay data. Engines never read the raw files directly, so the
leakage guarantee holds in one place.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import leakage_guard
from .clock import ReplayClock

REPLAY_ROOT = Path(__file__).resolve().parents[2] / "data" / "replay" / "2025-standoff"
CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _rules() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "replay_backtest.yaml").read_text())


class ReplayDataset:
    def __init__(self, root: Path | None = None):
        self.root = root or REPLAY_ROOT
        self._evidence = self._load_evidence()
        self._brent = self._load_brent()

    def _load_evidence(self) -> list[dict[str, Any]]:
        path = self.root / "evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        ordered = sorted(rows, key=lambda r: _aware(r["timestamp"]))
        if rows != ordered:
            raise ValueError("replay evidence source must be stored in chronological order")
        tone_rules = _rules()["event_tone_by_type"]
        for row in rows:
            if not str(row.get("source_url", "")).startswith("http"):
                raise ValueError(f"replay evidence {row.get('id')} lacks an original source URL")
            row["tone"] = float(tone_rules.get(row["type"], 0.0))
            row["tone_basis"] = "config/replay_backtest.yaml event-type rule; not GDELT tone"
        return rows

    def _load_brent(self) -> list[dict[str, Any]]:
        path = self.root / "brent_daily.json"
        series = json.loads(path.read_text())["series"]
        for row in series:
            # normalize daily period to an ISO timestamp at market close-ish for guard comparison
            row["timestamp"] = f"{row['period']}T00:00:00Z"
        series.sort(key=lambda r: _aware(r["timestamp"]))
        return series

    def window(self) -> tuple[datetime, datetime]:
        # The replay begins with the calm EIA baseline, before the first conflict evidence record.
        start = min(_aware(self._evidence[0]["timestamp"]), _aware(self._brent[0]["timestamp"]))
        end = max(_aware(self._evidence[-1]["timestamp"]), _aware(self._brent[-1]["timestamp"]))
        return start, end

    def make_clock(self, step_hours: float = 6.0) -> ReplayClock:
        start, end = self.window()
        return ReplayClock(start, end, step_hours)

    def evidence_at(self, sim_now: datetime) -> list[dict[str, Any]]:
        """Evidence visible at sim_now — at-or-before the clock, leakage-guarded."""
        return leakage_guard.guard_rows(self._evidence, sim_now, context="replay-evidence")

    def latest_evidence(self, sim_now: datetime) -> dict[str, Any] | None:
        visible = self.evidence_at(sim_now)
        return visible[-1] if visible else None

    def brent_at(self, sim_now: datetime) -> float | None:
        """Most recent Brent print at-or-before sim_now. Authoritative price for replay."""
        visible = leakage_guard.guard_rows(self._brent, sim_now, context="replay-brent")
        return visible[-1]["value"] if visible else None

    def brent_series_to(self, sim_now: datetime) -> list[dict[str, Any]]:
        return leakage_guard.guard_rows(self._brent, sim_now, context="replay-brent-series")

    def risk_raw_at(self, sim_now: datetime, corridor: str = "hormuz") -> dict[str, Any]:
        """Build replay risk inputs using only evidence/Brent visible at the simulation clock.

        News volume is a computed daily count of the immutable sourced evidence records. Tone is an
        explicit event-type coding rule from config, not a claimed GDELT measurement.
        """
        sim_now = _aware(sim_now)
        visible = [row for row in self.evidence_at(sim_now) if row.get("corridor") == corridor]
        market_start = _aware(self._brent[0]["timestamp"]).date()
        day = market_start
        counts: list[float] = []
        while day <= sim_now.date():
            counts.append(float(sum(1 for row in visible if _aware(row["timestamp"]).date() == day)))
            day += timedelta(days=1)

        raw: dict[str, Any] = {}
        if visible:
            latest = visible[-1]
            raw["news_volume"] = {"latest": counts[-1], "series": counts}
            raw["tone"] = {"latest": latest["tone"]}
            raw["_age_hours"] = max(
                0.0, (sim_now - _aware(latest["timestamp"])).total_seconds() / 3600.0)
        prices = self.brent_series_to(sim_now)
        if prices:
            raw["price_vol"] = {"series": [row["value"] for row in prices[-60:]]}
        return raw


def _aware(dt: str | datetime) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    ds = ReplayDataset()
    clock = ds.make_clock(step_hours=24)
    print("window:", ds.window())
    for t in clock.ticks():
        ev = ds.latest_evidence(t)
        brent = ds.brent_at(t)
        headline = ev["headline"][:50] if ev else "-"
        print(f"{t.date()}  Brent={brent}  latest_evidence='{headline}'")
