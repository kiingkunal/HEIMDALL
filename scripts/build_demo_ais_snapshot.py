"""Spend a bounded Data Docked budget to build one dense, deduplicated demo AIS snapshot.

The regular harvester stays corridor-centred and frugal. This one-off demo builder samples nearby
approaches and Indian receiving ports, merges them with the latest real snapshot, and removes MMSI
duplicates. Every row remains labelled ``source=datadocked``; no SIM data is mixed into the file.
"""
from __future__ import annotations

import argparse
from collections import Counter
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import pandas as pd

from backend.harvesters import ais
from backend.lib import ais_keypool, storage
from backend.lib.provenance import SourceKind, tag


# Eleven calls × 10 credits = 110 credits. Together with the preceding four-corridor sweep, this
# keeps the user-authorised demo refresh at a maximum of 150 credits.
DEMO_AREAS = [
    ("Hormuz Strait", "hormuz", 26.42, 56.35),
    ("Jebel Ali approach", "hormuz", 25.02, 55.05),
    ("Ras Tanura loading area", "hormuz", 26.64, 50.16),
    ("Suez south anchorage", "suez", 29.92, 32.55),
    ("Port Said approach", "suez", 31.22, 32.33),
    ("Djibouti approach", "bab_el_mandeb", 11.60, 43.15),
    ("Aden approach", "bab_el_mandeb", 12.80, 45.00),
    ("Singapore anchorage", "malacca", 1.26, 103.85),
    ("North Malacca approach", "malacca", 5.35, 100.30),
    ("Mumbai receiving area", "india_west", 18.95, 72.90),
    ("Jamnagar-Sikka receiving area", "india_west", 22.45, 69.75),
]

# Only these extra scans replace previously sparse primary corridor observation circles. The other
# scans add honest map density but must not be compared with the narrower historical pulse baseline.
RISK_OBSERVATION_AREAS = {"Suez south anchorage", "Djibouti approach"}


def _dedupe_key(frame: pd.DataFrame) -> pd.Series:
    """Prefer MMSI; use a stable name/position key only when MMSI is absent."""
    mmsi = frame["mmsi"].fillna("").astype(str).str.strip()
    fallback = (
        frame["name"].fillna("unknown").astype(str)
        + "|"
        + frame["lat"].round(4).astype(str)
        + "|"
        + frame["lon"].round(4).astype(str)
    )
    return mmsi.where(mmsi.str.len() >= 6, fallback)


def _distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance used only to recover area labels for an already-fetched snapshot."""
    dlat, dlon = radians(lat_b - lat_a), radians(lon_b - lon_a)
    a = sin(dlat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def reclassify_existing(base_path: Path, expanded_path: Path) -> None:
    """Mark expanded-area rows without making another API call or changing the map total."""
    storage.init_db()
    base = pd.read_parquet(base_path)
    expanded = pd.read_parquet(expanded_path)
    base_ids = set(base["mmsi"].fillna("").astype(str))

    def area_for(row: pd.Series) -> str:
        return min(
            DEMO_AREAS,
            key=lambda area: _distance_km(float(row["lat"]), float(row["lon"]), area[2], area[3]),
        )[0]

    expanded["observation_area"] = expanded.apply(area_for, axis=1)
    expanded["risk_observation"] = expanded["observation_area"].isin(RISK_OBSERVATION_AREAS)
    inherited = expanded["mmsi"].fillna("").astype(str).isin(base_ids)
    expanded.loc[inherited, "risk_observation"] = True
    expanded.loc[inherited, "observation_area"] = "primary corridor sweep"

    output = storage.write_parquet_snapshot(expanded, "ais")
    risk_counts = dict(Counter(expanded.loc[expanded["risk_observation"], "corridor"].fillna("unassigned")))
    summary = {
        "provider": "datadocked",
        "tanker_count": len(expanded),
        "per_corridor_primary_observation": risk_counts,
        "snapshot": output.name,
        "credits_spent_this_run": 0,
        "credits_remaining": ais_keypool.total_remaining(),
        "deduplicated_by": "MMSI (name+position fallback)",
        "density_rows_excluded_from_pulse": int((~expanded["risk_observation"]).sum()),
    }
    tagged = tag(
        summary,
        ais.DATADOCKED_LABEL,
        SourceKind.LIVE,
        note="real AIS demo snapshot; expanded density rows excluded from like-for-like corridor pulse",
    ).to_dict()
    storage.put_latest("ais", "last_snapshot", tagged, ais.DATADOCKED_LABEL, "live")
    print(tagged)


def main() -> None:
    storage.init_db()
    before = ais_keypool.total_remaining()
    latest = storage.latest_snapshot("ais")
    frames: list[pd.DataFrame] = []
    if latest is not None:
        existing = pd.read_parquet(latest)
        if set(existing.get("source", [])) == {"datadocked"}:
            existing["risk_observation"] = existing.get("risk_observation", True)
            existing["observation_area"] = existing.get("observation_area", "primary corridor sweep")
            frames.append(existing)

    per_area: dict[str, int] = {}
    for label, corridor, lat, lon in DEMO_AREAS:
        rows = ais.fetch_datadocked_area(
            corridor,
            {"ais_center": {"lat": lat, "lon": lon, "radius_km": 50}},
        )
        per_area[label] = len(rows)
        if rows:
            area_frame = pd.DataFrame(rows)
            area_frame["observation_area"] = label
            area_frame["risk_observation"] = label in RISK_OBSERVATION_AREAS
            frames.append(area_frame)

    if not frames:
        raise RuntimeError("Data Docked returned no usable tanker rows; existing snapshot preserved")

    merged = pd.concat(frames, ignore_index=True)
    merged["_dedupe_key"] = _dedupe_key(merged)
    merged = (
        merged.sort_values("timestamp")
        .drop_duplicates("_dedupe_key", keep="last")
        .drop(columns="_dedupe_key")
        .reset_index(drop=True)
    )
    output = storage.write_parquet_snapshot(merged, "ais")
    counts = dict(Counter(merged["corridor"].fillna("unassigned")))
    remaining = ais_keypool.total_remaining()
    summary = {
        "provider": "datadocked",
        "tanker_count": len(merged),
        "per_corridor": counts,
        "per_demo_area": per_area,
        "snapshot": output.name,
        "credits_spent_this_run": before - remaining,
        "credits_remaining": remaining,
        "deduplicated_by": "MMSI (name+position fallback)",
    }
    tagged = tag(
        summary,
        ais.DATADOCKED_LABEL,
        SourceKind.LIVE,
        note="bounded multi-area demo snapshot; real AIS rows only, MMSI-deduplicated",
    ).to_dict()
    storage.log_harvest(
        "ais",
        ais.DATADOCKED_LABEL,
        "live",
        "ok",
        record_count=len(merged),
        detail=output.name,
    )
    storage.put_latest("ais", "last_snapshot", tagged, ais.DATADOCKED_LABEL, "live")
    print(tagged)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclassify-base", type=Path)
    parser.add_argument("--reclassify-expanded", type=Path)
    args = parser.parse_args()
    if args.reclassify_base and args.reclassify_expanded:
        reclassify_existing(args.reclassify_base, args.reclassify_expanded)
    else:
        main()
