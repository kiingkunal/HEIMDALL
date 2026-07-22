"""Playbook lifecycle engine (L4). A playbook is a pre-computed, certified response that EXISTS
before the crisis, carries a validity window + an input snapshot, and goes STALE (visibly, with a
stated reason) when the world drifts past a configured threshold — then regenerates.

Each playbook stores: generated timestamp, validity window, input snapshot, the three solver plans,
their robustness certificates, the recommended plan + fallback, a pre-crisis 'no-regret actions'
section, and (optionally) an LLM narrative. Persisted in the SQLite `playbooks` table.

Regeneration triggers (config/playbook_triggers.yaml): Brent move, Risk Index move, vessel
availability change, new sanctions event, corridor state change, time expiry.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag, utcnow
from . import certify, maritime, risk
from .allocator import Scenario, solve, PRESETS

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _triggers() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "playbook_triggers.yaml").read_text())


@lru_cache(maxsize=1)
def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def refresh_interval_minutes() -> int:
    return int(_triggers()["lifecycle"]["refresh_check_interval_min"])


# ------------------------------- input snapshot (for triggers) -------------------------------
def current_snapshot(scenario: Scenario) -> dict[str, Any]:
    """Capture the market inputs a playbook depends on, so drift can be detected later."""
    brent = None
    rec = storage.get_latest("prices", "brent_spot")
    if rec:
        brent = rec["payload"].get("value", {}).get("price_usd_per_bbl")

    risk_index = {}
    for cid, meta in _corridors().items():
        if meta.get("reroute_reference"):
            continue
        risk_index[cid] = risk.compute(cid, risk.gather_raw(cid)).index

    sanctions_vessels = None
    srec = storage.get_latest("sanctions", "sdn")
    if srec:
        sanctions_vessels = srec["payload"].get("value", {}).get("vessel_count")

    observed_tankers = {}
    for cid, meta in _corridors().items():
        if meta.get("reroute_reference"):
            continue
        observed_tankers[cid] = maritime.corridor_pulse(cid)["value"]["observed_tankers"]

    return {
        "brent_usd_bbl": brent,
        "risk_index": risk_index,
        "sanctions_vessel_count": sanctions_vessels,
        "observed_tankers": observed_tankers,
        "corridor_states": dict(scenario.corridor_states),
        "scenario_inputs": scenario.to_dict(),
        "captured_at": utcnow().isoformat(),
    }


def _no_regret_actions(certs: dict[str, Any], recommended: str) -> list[dict[str, Any]]:
    """Pre-crisis 'no-regret' options with option-value from the certificate spread (same MC
    machinery). E.g. diversifying now reduces cost-at-risk / worst-case shortfall later."""
    actions = []
    cost = certs.get("cost_first", {})
    sec = certs.get("security_first", {})
    if cost and sec:
        car_premium = round(sec.get("cost_at_risk_usd_bbl", 0)
                            - cost.get("cost_at_risk_usd_bbl", 0), 2)
        short_delta = round(cost.get("worst_case_shortfall_mb_d", 0)
                            - sec.get("worst_case_shortfall_mb_d", 0), 4)
        if short_delta > 0:
            valuation = (f"certificate spread: {short_delta} mb/d lower worst-case shortfall; "
                         f"cost-at-risk premium ${max(0.0, car_premium)}/bbl")
        else:
            valuation = ("certificate spread: no current worst-case shortfall reduction; "
                         f"diversification carries ${max(0.0, car_premium)}/bbl cost-at-risk premium")
        actions.append({
            "action": "Pre-diversify supplier mix toward the Security-First allocation",
            "option_value": valuation,
            "valuation_status": "certificate-derived",
            "reversible": True,
        })
    actions.append({
        "action": "Reserve alternative (non-Hormuz) tanker capacity ahead of need",
        "option_value": "operational readiness action; standalone option value not yet quantified",
        "valuation_status": "unquantified",
        "reversible": True,
    })
    actions.append({
        "action": "Top up commercial crude cover toward the upper buffer band",
        "option_value": "inventory-cover action; standalone option value not yet quantified",
        "valuation_status": "unquantified",
        "reversible": True,
    })
    return actions


# ------------------------------- generation -------------------------------
def generate(scenario: Scenario, playbook_id: str | None = None,
             n_samples: int | None = None) -> dict[str, Any]:
    """Solve + certify + assemble a playbook, persist it, return it."""
    plans = {p: solve(scenario, p) for p in PRESETS}
    cert_out = certify.recommend(plans, scenario, n_samples=n_samples)

    now = utcnow()
    validity_h = _triggers()["lifecycle"]["default_validity_hours"]
    valid_until = now + timedelta(hours=validity_h)
    pid = playbook_id or f"pb_{uuid.uuid4().hex[:10]}"

    payload = {
        "id": pid,
        "generated_at": now.isoformat(),
        "valid_until": valid_until.isoformat(),
        "status": "fresh",
        "scenario": scenario.to_dict(),
        "input_snapshot": current_snapshot(scenario),
        "plans": {p: plans[p].to_dict() for p in PRESETS},
        "certificates": cert_out["certificates"],
        "recommended": cert_out["recommended"],
        "recommended_pass_rate": cert_out["recommended_pass_rate"],
        "fallback": cert_out["fallback"],
        "no_regret_actions": _no_regret_actions(cert_out["certificates"], cert_out["recommended"]),
        "next_refresh": valid_until.isoformat(),
    }

    _persist(payload)
    return payload


def _persist(payload: dict[str, Any]) -> None:
    conn = storage.get_db()
    try:
        conn.execute(
            "INSERT INTO playbooks (id, created_at, valid_until, status, payload, stale_reason)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at,"
            " valid_until=excluded.valid_until, status=excluded.status,"
            " payload=excluded.payload, stale_reason=excluded.stale_reason",
            (payload["id"], payload["generated_at"], payload["valid_until"],
             payload["status"], json.dumps(payload), payload.get("stale_reason")),
        )
        conn.commit()
    finally:
        conn.close()


def get(playbook_id: str) -> dict[str, Any] | None:
    conn = storage.get_db()
    try:
        row = conn.execute("SELECT payload FROM playbooks WHERE id=?", (playbook_id,)).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:
        conn.close()


def list_playbooks() -> list[dict[str, Any]]:
    conn = storage.get_db()
    try:
        rows = conn.execute(
            "SELECT id, status, created_at, valid_until, stale_reason FROM playbooks"
            " ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _scenario_from_payload(payload: dict[str, Any]) -> Scenario:
    """Rehydrate known Scenario fields while tolerating older persisted playbooks."""
    allowed = Scenario.__dataclass_fields__.keys()
    return Scenario(**{k: v for k, v in payload.items() if k in allowed})


# ------------------------------- staleness / triggers -------------------------------
def check_staleness(playbook: dict[str, Any],
                    new_snapshot: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    """Compare the playbook's stored input snapshot to the current world. Return (stale, reason)."""
    tg = _triggers()["triggers"]
    reasons_cfg = _triggers()["stale_reasons"]
    snap = playbook["input_snapshot"]
    scenario = _scenario_from_payload(playbook["scenario"])
    cur = new_snapshot or current_snapshot(scenario)

    # time expiry
    if tg.get("time_expiry"):
        if utcnow() > datetime.fromisoformat(playbook["valid_until"]):
            return True, reasons_cfg["time_expiry"]

    # Brent move
    if snap.get("brent_usd_bbl") is not None and cur.get("brent_usd_bbl") is not None:
        if abs(cur["brent_usd_bbl"] - snap["brent_usd_bbl"]) >= tg["price_move_usd_per_bbl"]:
            return True, reasons_cfg["price_move_usd_per_bbl"].replace(
                "{threshold}", str(tg["price_move_usd_per_bbl"]))

    # Risk Index move (any corridor)
    for cid, old in (snap.get("risk_index") or {}).items():
        new = (cur.get("risk_index") or {}).get(cid)
        if new is not None and abs(new - old) >= tg["risk_index_move_points"]:
            return True, reasons_cfg["risk_index_move_points"].replace(
                "{threshold}", str(tg["risk_index_move_points"]))

    # new sanctions event (vessel count changed)
    if tg.get("new_sanctions_event"):
        if (snap.get("sanctions_vessel_count") is not None
                and cur.get("sanctions_vessel_count") is not None
                and cur["sanctions_vessel_count"] != snap["sanctions_vessel_count"]):
            return True, reasons_cfg["new_sanctions_event"]

    # observed tanker availability drift, evaluated corridor-by-corridor. Counts are an AIS
    # availability proxy, not global fleet inventory or a certified chokepoint crossing count.
    threshold = float(tg.get("vessel_availability_change_pct", 0.0))
    if threshold > 0:
        for cid, old in (snap.get("observed_tankers") or {}).items():
            new = (cur.get("observed_tankers") or {}).get(cid)
            if new is None:
                continue
            pct = (100.0 if old == 0 and new != 0 else
                   (abs(float(new) - float(old)) / float(old) * 100.0 if old else 0.0))
            if pct >= threshold:
                return True, reasons_cfg["vessel_availability_change_pct"].replace(
                    "{threshold}", str(tg["vessel_availability_change_pct"]))

    # corridor state change
    if tg.get("corridor_state_change"):
        if cur.get("corridor_states") != snap.get("corridor_states"):
            return True, reasons_cfg["corridor_state_change"]

    return False, None


def refresh(playbook_id: str, new_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """If stale, mark STALE (with reason) and regenerate with an updated certificate."""
    pb = get(playbook_id)
    if not pb:
        return {"error": f"playbook {playbook_id} not found"}
    stale, reason = check_staleness(pb, new_snapshot)
    if not stale:
        return {"playbook_id": playbook_id, "status": "fresh", "regenerated": False}

    # mark stale (visible) then regenerate in place
    pb["status"] = "stale"
    pb["stale_reason"] = reason
    _persist(pb)

    scenario = _scenario_from_payload(pb["scenario"])
    regenerated = generate(scenario, playbook_id=playbook_id)
    return {"playbook_id": playbook_id, "status": "regenerated", "regenerated": True,
            "stale_reason": reason, "playbook": regenerated}


def refresh_all() -> dict[str, Any]:
    """Evaluate every persisted playbook and regenerate only those whose trigger fired."""
    results = [refresh(item["id"]) for item in list_playbooks()]
    return {"checked": len(results),
            "regenerated": sum(1 for r in results if r.get("regenerated")),
            "results": results}


def generate_tagged(scenario: Scenario, **kw) -> dict[str, Any]:
    return tag(generate(scenario, **kw), "HEIMDALL playbook engine", SourceKind.ENGINE,
               note="expiring, certified playbook; regenerates on drift").to_dict()


if __name__ == "__main__":
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.6)
    pb = generate(sc)
    print("generated:", pb["id"], "status:", pb["status"], "recommended:", pb["recommended"])
    # simulate a Brent spike drift -> should go stale
    snap = dict(pb["input_snapshot"])
    snap["brent_usd_bbl"] = (snap["brent_usd_bbl"] or 80) + 10
    stale, reason = check_staleness(pb, snap)
    print("after +$10 Brent drift -> stale:", stale, "| reason:", reason)
