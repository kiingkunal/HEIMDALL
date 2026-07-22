"""AIS harvester. Provider-aware (env AIS_PROVIDER):

  - datadocked  : FALLBACK. datadocked.com REST 'get-vessels-by-area' per corridor chokepoint.
                  Credit-metered (10 cr/call) via lib.ais_keypool; a SNAPSHOT source, not a
                  continuous recorder. Real ground-truth positions for the map + anomaly base.
  - aisstream   : PRIMARY when configured. Continuous WebSocket recorder with reconnect/backoff.
  - sim         : offline synthetic density (see harvesters/sim.py), for the rehearsed demo path.

TRUTH CONSTRAINT #1 (non-negotiable): no provider gives a server-side *tanker* filter.
  - aisstream: subscription filters are bbox/MMSI/message-type only -> we join ShipStaticData Type
    to PositionReports by MMSI and keep codes 80-89 LOCALLY.
  - datadocked: get-vessels-by-area returns ALL vessels in the circle with a `typeSpecific` string
    -> we keep tankers LOCALLY by matching 'tanker' in typeSpecific.
Never claim server-side tanker filtering.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv

from ..lib import ais_keypool, storage
from ..lib.provenance import SourceKind, tag

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"

NAMESPACE = "ais"
AIS_PROVIDER = os.getenv("AIS_PROVIDER", "datadocked").lower()

# ---- aisstream (continuous primary when configured) ----
AISSTREAM_KEY = os.getenv("AISSTREAM_API_KEY", "")
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_LABEL = "aisstream.io WebSocket (beta, no SLA)"
TANKER_TYPE_MIN = 80          # AIS ship type codes 80-89 == tanker (local filter, constraint #1)
TANKER_TYPE_MAX = 89
SNAPSHOT_INTERVAL_S = 600
RECONNECT_BASE_S = 2.0
RECONNECT_MAX_S = 60.0
_MMSI_TYPE_CACHE = CONFIG_ROOT.parent / "data" / "snapshots" / "mmsi_type_map.json"

# ---- datadocked (active) ----
DATADOCKED_BASE = "https://datadocked.com/api/vessels_operations"
DATADOCKED_AREA_URL = f"{DATADOCKED_BASE}/get-vessels-by-area"
DATADOCKED_LABEL = "datadocked.com get-vessels-by-area (satellite+terrestrial AIS)"
DATADOCKED_AREA_COST = 10     # credits per area call (published)
# A vessel is a tanker if any of these appear in its typeSpecific string (local filter).
TANKER_TYPE_KEYWORDS = ("tanker", "crude", "lng", "lpg", "chemical", "oil products")


def active_provider() -> str:
    return AIS_PROVIDER


def is_dormant() -> bool:
    """True only if the active provider has no usable credentials/credits."""
    if AIS_PROVIDER == "aisstream":
        return not AISSTREAM_KEY
    if AIS_PROVIDER == "datadocked":
        return ais_keypool.total_remaining() <= 0
    if AIS_PROVIDER == "sim":
        return False
    return True


def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def _is_tanker(type_specific: str | None) -> bool:
    if not type_specific:
        return False
    t = type_specific.lower()
    return any(kw in t for kw in TANKER_TYPE_KEYWORDS)


# --------------------------------------------------------------------------------------
# datadocked provider (ACTIVE) — snapshot source, credit-metered.
# --------------------------------------------------------------------------------------
def fetch_datadocked_area(corridor_id: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """One area call for one corridor. Returns tanker rows (local filter). Charges credits.

    Reconciles the local budget with reality: a 402/insufficient response disables that key.
    Returns [] on any failure (caller decides fallback); never raises to the scheduler.
    """
    center = meta.get("ais_center")
    if not center:
        return []
    picked = ais_keypool.pick_key(DATADOCKED_AREA_COST)
    if picked is None:
        storage.log_harvest("ais", DATADOCKED_LABEL, "cache", "empty",
                            detail=f"insufficient credits for {corridor_id} (need {DATADOCKED_AREA_COST})")
        return []
    key, masked = picked
    params = {"latitude": center["lat"], "longitude": center["lon"],
              "circle_radius": center.get("radius_km", 50)}
    try:
        r = requests.get(DATADOCKED_AREA_URL,
                         headers={"x-api-key": key, "accept": "application/json"},
                         params=params, timeout=30)
        if r.status_code in (401, 403):
            ais_keypool.disable(masked, f"auth {r.status_code}")
            return []
        if r.status_code in (402, 429):
            ais_keypool.disable(masked, f"credits/rate {r.status_code}")
            return []
        r.raise_for_status()
        ais_keypool.charge(masked, DATADOCKED_AREA_COST)  # only charge on a real 200

        vessels = r.json().get("vessels", [])
        now = datetime.now(timezone.utc)
        rows = []
        for v in vessels:
            if not _is_tanker(v.get("typeSpecific")):
                continue  # LOCAL tanker filter (constraint #1)
            rows.append({
                "mmsi": str(v.get("mmsi") or ""),
                "name": v.get("name"),
                "lat": _f(v.get("latitude")),
                "lon": _f(v.get("longitude")),
                "sog": _f(v.get("speed")),
                "cog": _f(v.get("course")),
                "heading": _f(v.get("heading")),
                "ship_type": v.get("typeSpecific"),
                "corridor": corridor_id,
                "timestamp": now,
                "source": "datadocked",
            })
        return rows
    except Exception as exc:
        storage.log_harvest("ais", f"{DATADOCKED_LABEL}:{corridor_id}", "live", "error",
                            detail=str(exc)[:200])
        return []


def _f(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def run_datadocked(corridors: list[str] | None = None) -> dict[str, Any]:
    """Sweep corridors (or a subset) via datadocked, snapshot tankers to parquet.

    Frugal by default: only corridors with an ais_center and only while the pool can afford it.
    """
    import pandas as pd

    cmeta = _corridors()
    targets = corridors or [cid for cid, m in cmeta.items()
                            if m.get("ais_center") and not m.get("reroute_reference")]
    all_rows: list[dict[str, Any]] = []
    per_corridor = {}
    for cid in targets:
        rows = fetch_datadocked_area(cid, cmeta[cid])
        per_corridor[cid] = len(rows)
        all_rows.extend(rows)

    if all_rows:
        df = pd.DataFrame(all_rows)
        path = storage.write_parquet_snapshot(df, "ais")
        storage.log_harvest("ais", DATADOCKED_LABEL, "live", "ok", record_count=len(all_rows),
                            detail=str(path.name))
        summary = {"provider": "datadocked", "tanker_count": len(all_rows),
                   "per_corridor": per_corridor, "snapshot": path.name,
                   "credits_remaining": ais_keypool.total_remaining()}
        kind = SourceKind.LIVE
    else:
        summary = {"provider": "datadocked", "tanker_count": 0, "per_corridor": per_corridor,
                   "credits_remaining": ais_keypool.total_remaining(),
                   "note": "no tanker rows (credits exhausted, sparse coverage, or all-failed)"}
        kind = SourceKind.CACHE

    tagged = tag(summary, DATADOCKED_LABEL, kind).to_dict()
    storage.put_latest(NAMESPACE, "last_snapshot", tagged, DATADOCKED_LABEL, kind.value)
    return tagged


# --------------------------------------------------------------------------------------
# aisstream provider — continuous recorder with bounded manual-probe support.
# --------------------------------------------------------------------------------------
def _corridor_bboxes() -> list[list[list[float]]]:
    boxes = []
    for meta in _corridors().values():
        if meta.get("reroute_reference"):
            continue
        b = meta["bbox"]
        boxes.append([[b["lat_min"], b["lon_min"]], [b["lat_max"], b["lon_max"]]])
    return boxes


def _load_type_map() -> dict[str, dict[str, Any]]:
    """Load MMSI static metadata, accepting the legacy ``mmsi -> type`` cache shape."""
    if _MMSI_TYPE_CACHE.exists():
        try:
            raw = json.loads(_MMSI_TYPE_CACHE.read_text())
            return {
                str(mmsi): ({"type": int(value), "name": None}
                            if isinstance(value, (int, float))
                            else {"type": value.get("type"), "name": value.get("name")})
                for mmsi, value in raw.items()
            }
        except json.JSONDecodeError:
            return {}
    return {}


def _save_type_map(m: dict[str, dict[str, Any]]) -> None:
    _MMSI_TYPE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _MMSI_TYPE_CACHE.write_text(json.dumps(m))


def _corridor_for_position(lat: Any, lon: Any) -> str | None:
    """Return the configured chokepoint containing a position, if any."""
    lat_f, lon_f = _f(lat), _f(lon)
    if lat_f is None or lon_f is None:
        return None
    for corridor_id, meta in _corridors().items():
        if meta.get("reroute_reference"):
            continue
        box = meta["bbox"]
        if (box["lat_min"] <= lat_f <= box["lat_max"]
                and box["lon_min"] <= lon_f <= box["lon_max"]):
            return corridor_id
    return None


async def _aisstream_stream(duration_s: float | None = None) -> None:
    import pandas as pd
    import websockets

    type_map = _load_type_map()
    positions: list[dict[str, Any]] = []
    started = datetime.now(timezone.utc)
    backoff = RECONNECT_BASE_S
    last_snapshot = started
    subscribe = {
        "APIKey": AISSTREAM_KEY,
        "BoundingBoxes": _corridor_bboxes(),
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    while True:
        try:
            async with websockets.connect(
                AISSTREAM_URL, ping_interval=20, open_timeout=20, close_timeout=10,
            ) as ws:
                await ws.send(json.dumps(subscribe))
                backoff = RECONNECT_BASE_S
                storage.put_latest(
                    NAMESPACE, "stream_status",
                    tag({"provider": "aisstream", "connected": True, "receiving": False},
                        AISSTREAM_LABEL, SourceKind.LIVE,
                        note="socket connected; awaiting AIS frames").to_dict(),
                    AISSTREAM_LABEL, "live",
                )
                while True:
                    now = datetime.now(timezone.utc)
                    elapsed = (now - started).total_seconds()
                    if duration_s and elapsed >= duration_s:
                        if positions:
                            _snapshot(pd.DataFrame(positions))
                        _save_type_map(type_map)
                        return
                    receive_timeout = min(30.0, max(0.1, duration_s - elapsed)) if duration_s else 30.0
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=receive_timeout)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    mtype = msg.get("MessageType")
                    meta = msg.get("MetaData", {})
                    mmsi = str(meta.get("MMSI") or "")
                    if mtype == "ShipStaticData":
                        static = msg.get("Message", {}).get("ShipStaticData", {})
                        code = static.get("Type")
                        if mmsi and code is not None:
                            type_map[mmsi] = {"type": int(code), "name": static.get("Name")}
                    elif mtype == "PositionReport":
                        static = type_map.get(mmsi) or {}
                        code = static.get("type")
                        if code is None or not (TANKER_TYPE_MIN <= code <= TANKER_TYPE_MAX):
                            continue
                        pr = msg.get("Message", {}).get("PositionReport", {})
                        lat, lon = meta.get("latitude"), meta.get("longitude")
                        positions.append({
                            "mmsi": mmsi, "name": static.get("name"), "lat": lat, "lon": lon,
                            "sog": pr.get("Sog"), "cog": pr.get("Cog"),
                            "heading": pr.get("TrueHeading"), "ship_type": code,
                            "corridor": _corridor_for_position(lat, lon),
                            "timestamp": datetime.now(timezone.utc), "source": "aisstream",
                        })
                        storage.put_latest(
                            NAMESPACE, "stream_status",
                            tag({"provider": "aisstream", "connected": True, "receiving": True},
                                AISSTREAM_LABEL, SourceKind.LIVE,
                                note="AIS frames are being received").to_dict(),
                            AISSTREAM_LABEL, "live",
                        )
                    now = datetime.now(timezone.utc)
                    if (now - last_snapshot).total_seconds() >= SNAPSHOT_INTERVAL_S and positions:
                        _snapshot(pd.DataFrame(positions)); _save_type_map(type_map)
                        positions = []; last_snapshot = now
        except Exception as exc:
            storage.log_harvest("ais", AISSTREAM_LABEL, "live", "error", detail=str(exc)[:200])
            storage.put_latest(
                NAMESPACE, "stream_status",
                tag({"provider": "aisstream", "connected": False, "receiving": False,
                     "error_type": type(exc).__name__}, AISSTREAM_LABEL, SourceKind.CACHE,
                    note="stream unavailable; cached/DataDocked/SIM positions remain visible").to_dict(),
                AISSTREAM_LABEL, "cache",
            )
            if duration_s and (datetime.now(timezone.utc) - started).total_seconds() >= duration_s:
                _save_type_map(type_map)
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_S)


def _snapshot(df) -> None:
    path = storage.write_parquet_snapshot(df, "ais")
    storage.log_harvest("ais", AISSTREAM_LABEL, "live", "ok", record_count=len(df),
                        detail=str(path.name))
    storage.put_latest(NAMESPACE, "last_snapshot",
                       tag({"rows": len(df), "path": str(path.name), "provider": "aisstream"},
                           AISSTREAM_LABEL, SourceKind.LIVE).to_dict(),
                       AISSTREAM_LABEL, "live")


def run_aisstream(duration_s: float | None = None) -> dict[str, Any]:
    if not AISSTREAM_KEY:
        status = "dormant — AISSTREAM_API_KEY missing"
        storage.log_harvest("ais", AISSTREAM_LABEL, "cache", "empty", detail=status)
        return tag({"status": status}, AISSTREAM_LABEL, SourceKind.CACHE, note=status).to_dict()
    asyncio.run(_aisstream_stream(duration_s))
    return tag({"status": "recorded"}, AISSTREAM_LABEL, SourceKind.LIVE).to_dict()


# --------------------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------------------
def run(**kwargs: Any) -> dict[str, Any]:
    """Scheduler/manual entry point. Dispatches on AIS_PROVIDER."""
    if AIS_PROVIDER == "datadocked":
        return run_datadocked(kwargs.get("corridors"))
    if AIS_PROVIDER == "aisstream":
        return run_aisstream(kwargs.get("duration_s"))
    if AIS_PROVIDER == "sim":
        from . import sim
        return sim.run(**kwargs)
    return tag({"status": f"unknown AIS_PROVIDER '{AIS_PROVIDER}'"},
               "ais dispatch", SourceKind.CACHE).to_dict()


if __name__ == "__main__":
    storage.init_db()
    print("provider:", AIS_PROVIDER, "| dormant:", is_dormant())
    print("keypool:", ais_keypool.status())
