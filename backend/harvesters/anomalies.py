"""AIS anomaly detector. Runs on each AIS parquet snapshot. Three signals, in priority order:

- CLUSTER_TURN — >=3 tankers reversing course within 6h in the same corridor zone. Truth
  Constraint #2 names this our STRONGEST explainable AIS signal; feature it, not DARK_GAP.
- LOITERING   — SOG < 1 kt inside a transit zone for > 2h (idling where ships should transit).
- DARK_GAP    — an AIS position gap. LABELED 'possible AIS silence or coverage gap', NEVER
  'went dark'. Terrestrial AIS has real holes; this is not proof of intent.

Feeds the Risk Index anomaly component. Dormant until AIS data exists (aisstream key blocked
2026-07-21); returns an empty, provenance-tagged result rather than failing when no snapshot.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
NAMESPACE = "anomalies"
SOURCE_LABEL = "AIS anomaly detector (derived from AIS parquet)"

# Detection thresholds. Kept with the detector; move to config if they become tunable in-demo.
CLUSTER_TURN_MIN_VESSELS = 3
CLUSTER_TURN_WINDOW_H = 6
CLUSTER_TURN_HEADING_DELTA = 120   # degrees of course reversal to count as a "turn"
LOITER_MAX_SOG_KT = 1.0
LOITER_MIN_HOURS = 2.0
DARK_GAP_MIN_HOURS = 3.0


def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def detect(snapshot_path: Path | None = None) -> dict[str, Any]:
    """Run detectors over the latest AIS snapshot. Returns Tagged list of anomaly events.

    While AIS is dormant, this returns an empty result with a clear note — the pipeline stays
    intact so it lights up the moment real AIS data lands.
    """
    # Prefer a live/datadocked 'ais' snapshot; fall back to a flagged SIM 'ais_sim' snapshot so the
    # rehearsed offline demo path works. The result records which it used — never silently mixed.
    live_path = storage.latest_snapshot("ais")
    sim_path = storage.latest_snapshot("ais_sim")
    path = snapshot_path or live_path or sim_path
    is_sim = path is not None and Path(path).name.startswith("ais_sim_")
    if path is None or not Path(path).exists():
        result = {"anomalies": [], "counts": {"CLUSTER_TURN": 0, "LOITERING": 0, "DARK_GAP": 0},
                  "status": "no AIS snapshot yet (datadocked not pulled; SIM not generated)"}
        tagged = tag(result, SOURCE_LABEL, SourceKind.CACHE,
                     note="no snapshot; anomaly detector idle").to_dict()
        storage.put_latest(NAMESPACE, "latest", tagged, SOURCE_LABEL, "cache")
        return tagged

    import pandas as pd
    df = pd.read_parquet(path)
    anomalies: list[dict[str, Any]] = []
    has_corridor_col = "corridor" in df.columns
    for cid, meta in _corridors().items():
        if meta.get("reroute_reference"):
            continue
        if has_corridor_col:
            # Rows already tagged with their corridor (datadocked/sim) — trust the tag. SIM tracks
            # span the whole route to India, so re-deriving zone from the chokepoint bbox would
            # drop most of a vessel's track. Fall back to bbox only for untagged raw AIS.
            zone = df[df["corridor"] == cid]
        else:
            bbox = meta["bbox"]
            zone = df[
                (df["lon"] >= bbox["lon_min"]) & (df["lon"] <= bbox["lon_max"]) &
                (df["lat"] >= bbox["lat_min"]) & (df["lat"] <= bbox["lat_max"])
            ]
        anomalies.extend(_cluster_turn(zone, cid))
        anomalies.extend(_loitering(zone, cid))
        anomalies.extend(_dark_gap(zone, cid))

    counts = {k: sum(1 for a in anomalies if a["type"] == k)
              for k in ("CLUSTER_TURN", "LOITERING", "DARK_GAP")}
    tagged = tag({"anomalies": anomalies, "counts": counts,
                  "status": "sim" if is_sim else "live", "synthetic": is_sim,
                  "snapshot": Path(path).name},
                 SOURCE_LABEL, SourceKind.DEMO if is_sim else SourceKind.LIVE,
                 note="synthetic AIS (SIM augmentation)" if is_sim else None).to_dict()
    storage.put_latest(NAMESPACE, "latest", tagged, SOURCE_LABEL,
                       "demo" if is_sim else "live")
    storage.log_harvest("anomalies", SOURCE_LABEL, "live", "ok", record_count=len(anomalies))
    return tagged


def _cluster_turn(zone, cid: str) -> list[dict[str, Any]]:
    """>=3 tankers reversing course within CLUSTER_TURN_WINDOW_H in this zone. Headline signal."""
    if zone.empty or "mmsi" not in zone.columns or "heading" not in zone.columns:
        return []
    turns = 0
    zone = zone.sort_values(["mmsi", "timestamp"])
    for _mmsi, g in zone.groupby("mmsi"):
        if len(g) < 2:
            continue
        h = g["heading"].to_numpy()
        span = g["timestamp"].max() - g["timestamp"].min()
        if hasattr(span, "total_seconds"):
            span_h = span.total_seconds() / 3600.0
        else:
            span_h = float(span) / 3600.0
        delta = abs(float(h[-1]) - float(h[0]))
        delta = min(delta, 360 - delta)
        if delta >= CLUSTER_TURN_HEADING_DELTA and span_h <= CLUSTER_TURN_WINDOW_H:
            turns += 1
    if turns >= CLUSTER_TURN_MIN_VESSELS:
        return [{"type": "CLUSTER_TURN", "corridor": cid, "vessel_count": turns,
                 "label": f"{turns} tankers reversed course within {CLUSTER_TURN_WINDOW_H}h",
                 "explainable": True}]
    return []


def _loitering(zone, cid: str) -> list[dict[str, Any]]:
    if zone.empty or "sog" not in zone.columns:
        return []
    slow = zone[zone["sog"] < LOITER_MAX_SOG_KT]
    events = []
    for mmsi, g in slow.groupby("mmsi"):
        span = g["timestamp"].max() - g["timestamp"].min()
        span_h = span.total_seconds() / 3600.0 if hasattr(span, "total_seconds") else float(span) / 3600.0
        if span_h >= LOITER_MIN_HOURS:
            events.append({"type": "LOITERING", "corridor": cid, "mmsi": int(mmsi),
                           "hours": round(span_h, 1),
                           "label": f"vessel idling >{LOITER_MIN_HOURS}h in transit zone"})
    return events


def _dark_gap(zone, cid: str) -> list[dict[str, Any]]:
    """AIS position gaps. LABELED as possible coverage gap, never as intentional dark activity."""
    if zone.empty or "mmsi" not in zone.columns:
        return []
    events = []
    zone = zone.sort_values(["mmsi", "timestamp"])
    for mmsi, g in zone.groupby("mmsi"):
        ts = g["timestamp"].to_list()
        for a, b in zip(ts, ts[1:]):
            gap = b - a
            gap_h = gap.total_seconds() / 3600.0 if hasattr(gap, "total_seconds") else float(gap) / 3600.0
            if gap_h >= DARK_GAP_MIN_HOURS:
                events.append({"type": "DARK_GAP", "corridor": cid, "mmsi": int(mmsi),
                               "gap_hours": round(gap_h, 1),
                               "label": "possible AIS silence or coverage gap (NOT proof of intent)"})
    return events


def run() -> dict[str, Any]:
    return detect()


if __name__ == "__main__":
    storage.init_db()
    res = run()
    print(res["value"]["status"], res["value"]["counts"])
