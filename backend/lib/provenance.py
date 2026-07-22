"""Provenance + data-age tagging. Every number HEIMDALL shows must carry where it came from
and how old it is (doctrine: no number on screen without an engine output or a sourced constant).

A Provenance wraps a value with source, timestamp, and freshness so the UI can render a
DATA AGE badge and degrade to cache with a visible warning instead of showing stale data silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    """Single source of 'now' — timezone-aware UTC. Replay clock overrides this elsewhere."""
    return datetime.now(timezone.utc)


class SourceKind(str, Enum):
    LIVE = "live"            # fetched this session from a live API
    CACHE = "cache"          # served from a prior snapshot (source failed or rate-limited)
    CONFIG = "config"        # sourced constant from config/ or data/ curated file
    ENGINE = "engine"        # computed by a HEIMDALL engine (cascade, risk, solver, MC)
    REPLAY = "replay"        # drawn from the immutable replay dataset at the sim clock
    DEMO = "demo"            # clearly-labeled demo assumption (never disguised as live fact)


# Age thresholds (hours) for the freshness badge. Mirrors risk_weights freshness horizon.
FRESH_HOURS = 6.0
STALE_HOURS = 72.0


@dataclass
class Provenance:
    source: str                       # human label e.g. "EIA Brent daily", "GDELT DOC API"
    kind: SourceKind
    fetched_at: datetime              # when this value was obtained/computed
    source_url: str | None = None
    note: str | None = None           # e.g. "DEMO ASSUMPTION", "cached — EIA 429"
    extra: dict[str, Any] = field(default_factory=dict)

    def age_hours(self, ref: datetime | None = None) -> float:
        ref = ref or utcnow()
        ft = self.fetched_at
        if ft.tzinfo is None:
            ft = ft.replace(tzinfo=timezone.utc)
        return max(0.0, (ref - ft).total_seconds() / 3600.0)

    def freshness_label(self, ref: datetime | None = None) -> str:
        age = self.age_hours(ref)
        if age <= FRESH_HOURS:
            return "fresh"
        if age <= STALE_HOURS:
            return "aging"
        return "stale"

    def to_dict(self, ref: datetime | None = None) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["fetched_at"] = self.fetched_at.astimezone(timezone.utc).isoformat()
        d["age_hours"] = round(self.age_hours(ref), 3)
        d["freshness"] = self.freshness_label(ref)
        return d


@dataclass
class Tagged:
    """A value bound to its provenance. This is what crosses the API boundary to the UI."""
    value: Any
    provenance: Provenance

    def to_dict(self, ref: datetime | None = None) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance.to_dict(ref)}


def tag(value: Any, source: str, kind: SourceKind, *,
        fetched_at: datetime | None = None, source_url: str | None = None,
        note: str | None = None, **extra: Any) -> Tagged:
    """Convenience constructor for a Tagged value."""
    return Tagged(
        value=value,
        provenance=Provenance(
            source=source,
            kind=kind,
            fetched_at=fetched_at or utcnow(),
            source_url=source_url,
            note=note,
            extra=extra,
        ),
    )
