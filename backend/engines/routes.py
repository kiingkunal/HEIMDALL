"""Route engine (L4 support). Uses `searoute` to compute each supplier's real sea route to India,
detect which chokepoints it traverses, and price freight from distance.

TRUTH CONSTRAINT #5 (non-negotiable): searoute is for realistic route VISUALISATION and comparative
distance/time — NOT navigation. UI labels routes "strategic planning estimates". We use it only for
comparative distance, passage detection, and reroute geometry.

Passage names from searoute -> our corridor ids:
  ormuz->hormuz, babalmandab->bab_el_mandeb, suez->suez, malacca->malacca, south_africa->cape_good_hope

Closure logic:
  - Hormuz has NO sea bypass (Gulf is enclosed) -> a supplier routed through a closed Hormuz is
    UNAVAILABLE. reroutable=False.
  - Suez / Bab-el-Mandeb / Malacca have a Cape-of-Good-Hope alternative -> closure forces a reroute
    at higher freight + extra transit days. reroutable=True.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
CONFIG_ROOT = REPO_ROOT / "config"

PASSAGE_TO_CORRIDOR = {
    "ormuz": "hormuz",
    "babalmandab": "bab_el_mandeb",
    "suez": "suez",
    "malacca": "malacca",
    "south_africa": "cape_good_hope",
}
# Corridors with a viable sea alternative (Cape reroute). Hormuz is NOT here.
REROUTABLE_CORRIDORS = {"suez", "bab_el_mandeb", "malacca"}

# Representative Indian discharge port for route/passage detection (passages are the same for any
# Indian west-coast destination from these origins). Sikka (Jamnagar).
INDIA_REF_PORT = [69.84, 22.43]   # [lon, lat]


@lru_cache(maxsize=1)
def _ports() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "ports.json").read_text())["ports"]


@lru_cache(maxsize=1)
def _suppliers() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "suppliers.json").read_text())["suppliers"]


@lru_cache(maxsize=1)
def _pricing() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "solver_presets.yaml").read_text())["pricing"]


@lru_cache(maxsize=1)
def _cascade_reroute_days() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "cascade_params.yaml").read_text())["cascade"]["reroute_extra_days"]


def _load_port(supplier_id: str) -> list[float] | None:
    for p in _ports():
        if p.get("is_load_port") and p.get("supplier_id") == supplier_id:
            return [p["lon"], p["lat"]]
    return None


def _freight_usd(distance_km: float, rerouted: bool) -> float:
    pr = _pricing()
    base = pr["base_freight_usd_bbl"] + pr["freight_usd_per_1000km"] * (distance_km / 1000.0)
    return base * (pr["reroute_freight_multiplier"] if rerouted else 1.0)


@lru_cache(maxsize=1)
def compute_routes() -> dict[str, dict[str, Any]]:
    """For every supplier: route corridors, distance, transit days, freight, reroutability.
    Cached — searoute is deterministic and this is pure w.r.t. static data."""
    import searoute as sr

    out: dict[str, dict[str, Any]] = {}
    for s in _suppliers():
        sid = s["id"]
        origin = _load_port(sid)
        if origin is None:
            out[sid] = {"supplier_id": sid, "error": "no load port", "corridors": [],
                        "reroutable": False}
            continue
        r = sr.searoute(origin, INDIA_REF_PORT, return_passages=True)
        props = r["properties"]
        passages = props.get("traversed_passages") or []
        corridors = [PASSAGE_TO_CORRIDOR[p] for p in passages if p in PASSAGE_TO_CORRIDOR]
        monitored = [c for c in corridors if c != "cape_good_hope"]
        distance_km = round(props["length"], 1)
        transit_days = round(props["duration_hours"] / 24.0, 2)
        # reroutable only if none of the monitored corridors is Hormuz (no Gulf bypass)
        reroutable = bool(monitored) and all(c in REROUTABLE_CORRIDORS for c in monitored)
        out[sid] = {
            "supplier_id": sid,
            "load_port": origin,
            "corridors": monitored,
            "all_passages": corridors,
            "distance_km": distance_km,
            "transit_days": transit_days,
            "freight_usd_bbl": round(_freight_usd(distance_km, False), 3),
            "reroutable": reroutable,
            "reroute_extra_days": max((_cascade_reroute_days().get(c, 0) for c in monitored), default=0),
            "reroute_freight_usd_bbl": round(_freight_usd(distance_km, True), 3),
        }
    return out


def route_feasibility(supplier_id: str, corridor_states: dict[str, str]) -> dict[str, Any]:
    """Given corridor open/restricted/closed states, decide this supplier's route status.

    Returns: {available: bool, rerouted: bool, freight_usd_bbl, transit_days, route_risk_corridors,
              reason}. 'closed' on a non-reroutable corridor -> unavailable. On a reroutable corridor
              -> rerouted (higher freight + delay) if it still fits the arrival window (checked by caller).
    """
    route = compute_routes().get(supplier_id, {})
    corridors = route.get("corridors", [])
    freight = route.get("freight_usd_bbl", 0.0)
    transit = route.get("transit_days", 0.0)
    rerouted = False
    reason = "open route"

    for c in corridors:
        state = corridor_states.get(c, "open")
        if state == "closed":
            if c in REROUTABLE_CORRIDORS:
                rerouted = True
                freight = route.get("reroute_freight_usd_bbl", freight)
                transit = transit + route.get("reroute_extra_days", 0)
                reason = f"{c} closed -> Cape reroute"
            else:
                return {"available": False, "rerouted": False, "freight_usd_bbl": freight,
                        "transit_days": transit, "route_corridors": corridors,
                        "reason": f"{c} closed, no sea bypass -> supplier unavailable"}
    return {"available": True, "rerouted": rerouted, "freight_usd_bbl": round(freight, 3),
            "transit_days": round(transit, 2), "route_corridors": corridors, "reason": reason}


if __name__ == "__main__":
    for sid, r in compute_routes().items():
        print(f"{sid:14s} corridors={r.get('corridors')} km={r.get('distance_km')} "
              f"reroutable={r.get('reroutable')} freight=${r.get('freight_usd_bbl')}")
