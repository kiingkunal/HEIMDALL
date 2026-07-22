"""Explainable chokepoint pulse from AIS snapshots; no inferred crossings or intent claims."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..harvesters import sanctions
from ..lib import storage
from ..lib.provenance import SourceKind, tag


CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def _zone(df, corridor_id: str):
    """Select rows in a corridor using an explicit tag first, then its configured bbox."""
    if "risk_observation" in df.columns:
        # Expanded demo-density scans remain visible on the map but are excluded from a pulse whose
        # baseline was built from one consistent 50 km observation circle.
        df = df[df["risk_observation"].fillna(True).astype(bool)]
    if "corridor" in df.columns:
        tagged = df[df["corridor"] == corridor_id]
        if not tagged.empty:
            return tagged
    meta = _corridors()[corridor_id]
    box = meta["bbox"]
    return df[
        (df["lon"] >= box["lon_min"]) & (df["lon"] <= box["lon_max"])
        & (df["lat"] >= box["lat_min"]) & (df["lat"] <= box["lat_max"])
    ]


def _snapshot_counts(
    paths: list[Path], corridor_id: str, observation_area: str | None = None,
) -> list[int]:
    """Return like-for-like counts, never mixing different geographic observation circles."""
    import pandas as pd

    counts: list[int] = []
    for path in paths[-30:]:
        try:
            frame = pd.read_parquet(path)
            zone = _zone(frame, corridor_id)
            if observation_area:
                if "observation_area" in zone.columns:
                    zone = zone[zone["observation_area"] == observation_area]
                    if zone.empty:
                        continue
                elif observation_area != "primary corridor sweep":
                    # Legacy snapshots used the original configured circle and cannot be compared
                    # with a newly named replacement circle.
                    continue
            counts.append(int(zone["mmsi"].nunique()) if "mmsi" in zone.columns else len(zone))
        except Exception:
            continue
    return counts


def corridor_pulse(corridor_id: str) -> dict[str, Any]:
    """Compute observed-vessel pulse and snapshot baseline for one chokepoint."""
    import pandas as pd

    live_paths = storage.list_snapshots("ais")
    sim_paths = storage.list_snapshots("ais_sim")
    paths = live_paths or sim_paths
    synthetic = not bool(live_paths)
    if not paths:
        value = {
            "corridor": corridor_id, "observed_tankers": 0, "moving_tankers": 0,
            "slow_tankers": 0, "avg_speed_kt": None, "baseline_median": None,
            "baseline_delta_pct": None, "baseline_samples": 0, "sanctions_hits": 0,
            "snapshot": None, "synthetic": False, "data_age_hours": None,
            "note": "no AIS snapshot available",
        }
        return tag(value, "AIS corridor pulse", SourceKind.CACHE,
                   note="no AIS snapshot; pulse unavailable").to_dict()

    latest = paths[-1]
    frame = pd.read_parquet(latest)
    zone = _zone(frame, corridor_id)
    if "mmsi" in zone.columns:
        current = zone.sort_values("timestamp").drop_duplicates("mmsi", keep="last")
    else:
        current = zone
    observed = int(current["mmsi"].nunique()) if "mmsi" in current.columns else len(current)
    speeds = pd.to_numeric(current.get("sog"), errors="coerce") if "sog" in current.columns else None
    avg_speed = round(float(speeds.dropna().mean()), 2) if speeds is not None and not speeds.dropna().empty else None
    slow = int((speeds < 1.0).sum()) if speeds is not None else 0
    moving = int((speeds >= 1.0).sum()) if speeds is not None else 0

    names = [str(name) for name in current.get("name", []) if name and str(name) != "nan"]
    sanctions_hits = sum(1 for name in set(names) if sanctions.is_sanctioned(name))
    observation_area = None
    if "observation_area" in current.columns and not current.empty:
        area_values = current["observation_area"].dropna().astype(str).unique()
        if len(area_values) == 1:
            observation_area = str(area_values[0])
    counts = _snapshot_counts(paths, corridor_id, observation_area)
    baseline = None
    delta = None
    if counts:
        ordered = sorted(counts)
        middle = len(ordered) // 2
        baseline = float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        if len(counts) >= 3 and baseline > 0:
            delta = round((observed - baseline) / baseline * 100.0, 1)

    age_hours = None
    if "timestamp" in frame.columns and not frame.empty:
        newest = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").max()
        if pd.notna(newest):
            age_hours = round(max(0.0, (datetime.now(timezone.utc) - newest.to_pydatetime()).total_seconds() / 3600), 3)
    source = "SIM augmentation" if synthetic else "AIS snapshot"
    kind = SourceKind.DEMO if synthetic else SourceKind.LIVE
    value = {
        "corridor": corridor_id, "observed_tankers": observed,
        "moving_tankers": moving, "slow_tankers": slow, "avg_speed_kt": avg_speed,
        "baseline_median": baseline, "baseline_delta_pct": delta,
        "baseline_samples": len(counts), "sanctions_hits": sanctions_hits,
        "snapshot": latest.name, "synthetic": synthetic, "data_age_hours": age_hours,
        "observation_area": observation_area,
        "note": "observed tanker snapshots; not a certified transit/crossing count",
    }
    return tag(value, source, kind,
               note="snapshot pulse; crossings are not inferred without enter/dwell/exit history").to_dict()


def pulses_all() -> dict[str, Any]:
    return {
        corridor_id: corridor_pulse(corridor_id)
        for corridor_id, meta in _corridors().items()
        if not meta.get("reroute_reference")
    }
