"""SIM augmentation layer. Synthetic tanker tracks along REAL searoute geometry, for the rehearsed
offline demo path when live AIS is sparse or unavailable.

Project data-integrity contract: synthetic tracks are FLAGGED in code, TOGGLABLE, and
NEVER silently mixed with live data. So:
  - every synthetic row carries source='sim' and synthetic=True,
  - snapshots use a separate parquet prefix 'ais_sim' (never 'ais'),
  - the map/anomaly layers opt in explicitly; nothing here can masquerade as a live position.

Because each synthetic vessel gets a short backward time-series, the anomaly detector has real
temporal structure to work on (CLUSTER_TURN / LOITERING / DARK_GAP), and scenarios can inject a
labelled anomaly for the demo — clearly as simulation, not as a real event.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
NAMESPACE = "ais"
SOURCE_LABEL = "SIM augmentation (synthetic tankers on real searoute paths) — NOT LIVE"

# A representative west-coast Indian discharge port per corridor origin (searoute destination).
CORRIDOR_DEST = {  # [lon, lat]
    "hormuz": [69.84, 22.43],        # Sikka (Jamnagar)
    "bab_el_mandeb": [72.85, 18.95], # Mumbai
    "suez": [72.85, 18.95],          # Mumbai
    "malacca": [80.30, 13.10],       # Chennai (east coast entry)
}

DEFAULT_VESSELS_PER_CORRIDOR = 6
TRACK_POINTS = 8                 # positions per vessel (temporal depth for anomaly detection)
TRACK_STEP_MIN = 30             # minutes between synthetic pings


def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def _densify(coords: list[list[float]], factor: int = 12) -> list[list[float]]:
    """Linear-interpolate between successive [lon,lat] vertices for a smooth path."""
    out: list[list[float]] = []
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        for i in range(factor):
            t = i / factor
            out.append([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t])
    out.append(coords[-1])
    return out


def _bearing(p0: list[float], p1: list[float]) -> float:
    """Course over ground (deg) from p0 to p1, [lon,lat]."""
    lon0, lat0, lon1, lat1 = map(math.radians, [p0[0], p0[1], p1[0], p1[1]])
    dlon = lon1 - lon0
    y = math.sin(dlon) * math.cos(lat1)
    x = math.cos(lat0) * math.sin(lat1) - math.sin(lat0) * math.cos(lat1) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def build_tracks(corridor_id: str, meta: dict[str, Any], n_vessels: int,
                 inject_cluster_turn: bool = False, seed: int | None = None) -> list[dict[str, Any]]:
    """Generate synthetic tanker tracks for one corridor along its real searoute path."""
    import searoute as sr

    center = meta.get("ais_center")
    dest = CORRIDOR_DEST.get(corridor_id)
    if not center or not dest:
        return []
    rng = random.Random(seed if seed is not None else hash(corridor_id) & 0xFFFF)

    origin = [center["lon"], center["lat"]]
    route = sr.searoute(origin, dest)
    path = _densify(route["geometry"]["coordinates"])
    if len(path) < TRACK_POINTS + 2:
        path = _densify(route["geometry"]["coordinates"], factor=30)

    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    half = TRACK_POINTS // 2
    for v in range(n_vessels):
        mmsi = f"SIM{corridor_id[:3].upper()}{v:03d}"
        turning = inject_cluster_turn and v < 3   # first 3 vessels reverse course -> CLUSTER_TURN
        start_idx = rng.randint(half + 1, max(half + 1, len(path) - TRACK_POINTS - 1))
        for k in range(TRACK_POINTS):
            if turning:
                # advance for the first half, then physically reverse: index walks forward then back,
                # so the course-over-ground swings ~180deg between the first and last ping.
                offset = k if k < half else (2 * half - k)
                idx = min(start_idx + offset, len(path) - 2)
                # bearing computed along the actual direction of travel at this step
                if k < half:
                    pos, nxt = path[idx], path[min(idx + 1, len(path) - 1)]
                else:
                    pos, nxt = path[idx], path[max(idx - 1, 0)]
                cog = _bearing(pos, nxt)
            else:
                idx = min(start_idx + k, len(path) - 2)
                pos, nxt = path[idx], path[idx + 1]
                cog = _bearing(pos, nxt)
            ts = now - timedelta(minutes=TRACK_STEP_MIN * (TRACK_POINTS - 1 - k))
            rows.append({
                "mmsi": mmsi,
                "name": f"SIM TANKER {corridor_id[:3].upper()}-{v}",
                "lat": round(pos[1] + rng.uniform(-0.01, 0.01), 5),
                "lon": round(pos[0] + rng.uniform(-0.01, 0.01), 5),
                "sog": round(rng.uniform(10, 14), 1),
                "cog": round(cog, 1),
                "heading": round(cog, 1),
                "ship_type": "Crude Oil Tanker (SIM)",
                "corridor": corridor_id,
                "timestamp": ts,
                "source": "sim",
                "synthetic": True,
            })
    return rows


def run(corridors: list[str] | None = None, vessels_per_corridor: int | None = None,
        inject_cluster_turn: bool = False, seed: int | None = None, **_: Any) -> dict[str, Any]:
    """Generate synthetic tracks and snapshot them under the 'ais_sim' prefix (never 'ais')."""
    import pandas as pd

    cmeta = _corridors()
    targets = corridors or [cid for cid, m in cmeta.items()
                            if m.get("ais_center") and not m.get("reroute_reference")]
    n = vessels_per_corridor or DEFAULT_VESSELS_PER_CORRIDOR
    all_rows: list[dict[str, Any]] = []
    per_corridor = {}
    for cid in targets:
        rows = build_tracks(cid, cmeta[cid], n, inject_cluster_turn=inject_cluster_turn, seed=seed)
        per_corridor[cid] = len({r["mmsi"] for r in rows})
        all_rows.extend(rows)

    summary = {"provider": "sim", "synthetic": True, "vessel_count": sum(per_corridor.values()),
               "row_count": len(all_rows), "per_corridor": per_corridor,
               "inject_cluster_turn": inject_cluster_turn}
    if all_rows:
        path = storage.write_parquet_snapshot(pd.DataFrame(all_rows), "ais_sim")
        summary["snapshot"] = path.name
        storage.log_harvest("ais_sim", SOURCE_LABEL, "live", "ok", record_count=len(all_rows),
                            detail=str(path.name))
    tagged = tag(summary, SOURCE_LABEL, SourceKind.DEMO,
                 note="synthetic — flagged, togglable, never mixed with live").to_dict()
    storage.put_latest(NAMESPACE, "sim_last_snapshot", tagged, SOURCE_LABEL, "demo")
    return tagged


if __name__ == "__main__":
    storage.init_db()
    res = run(inject_cluster_turn=True, seed=42)
    print(res["value"]["provider"], res["value"]["per_corridor"],
          "rows=", res["value"]["row_count"], "snapshot=", res["value"].get("snapshot"))
