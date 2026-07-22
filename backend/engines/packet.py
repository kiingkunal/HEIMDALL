"""Action Packet engine (L4) + cost-of-delay. On human approval of a plan, HEIMDALL assembles a
full, auditable action packet. THE SYSTEM RECOMMENDS; A HUMAN AUTHORISES; HEIMDALL NEVER EXECUTES.

Packet: procurement quantities, route + arrival schedule, refinery allocation, SPR proposal,
assumptions (with sources), evidence ledger, risks, approval requirements, contingency (the
certified fallback), operational timeline, and a full audit trail.

cost_of_delay(): the live premium range that accrues for each day a decision is deferred, computed
from the cascade + Monte Carlo layers — the "cost of waiting" shown on every active risk.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..lib.provenance import SourceKind, tag, utcnow
from . import cascade as cascade_engine
from . import montecarlo as mc_engine
from . import playbooks as playbook_engine
from .cascade import CorridorShock


def build_packet(playbook_id: str, approved_preset: str,
                 approver: str = "energy-security controller") -> dict[str, Any]:
    """Assemble an auditable action packet for the approved plan of a playbook."""
    pb = playbook_engine.get(playbook_id)
    if not pb:
        return {"error": f"playbook {playbook_id} not found"}
    if approved_preset not in pb["plans"]:
        return {"error": f"unknown preset '{approved_preset}'", "available": list(pb["plans"])}

    plan = pb["plans"][approved_preset]
    cert = pb["certificates"][approved_preset]
    now = utcnow()

    # procurement + arrival schedule from the plan's purchases
    procurement = []
    for p in plan["purchases"]:
        procurement.append({
            "supplier_id": p["supplier_id"], "country": p["country"],
            "refinery_id": p["refinery_id"], "grade_class": p["grade_class"],
            "volume_mb_d": p["volume_mb_d"], "price_usd_bbl": p["price_usd_bbl"],
            "route_corridors": p["route_corridors"], "rerouted": p["rerouted"],
            "transit_days": p["transit_days"], "arrival_day": p["arrival_day"],
            "route_scope": "strategic planning estimate; not for navigation",
        })

    spr_proposal = plan["spr_drawdown"]
    contingency_preset = pb["fallback"]

    packet = {
        "packet_id": f"pkt_{uuid.uuid4().hex[:10]}",
        "playbook_id": playbook_id,
        "approved_preset": approved_preset,
        "plan_label": plan["label"],
        "status": "AWAITING_HUMAN_AUTHORISATION",
        "disclaimer": "HEIMDALL recommends; a human authorises. HEIMDALL never executes procurement.",
        "scenario": pb["scenario"],
        "procurement_quantities": procurement,
        "refinery_allocation": _by_refinery(plan["purchases"], plan["spr_drawdown"]),
        "spr_proposal": spr_proposal,
        "commercial_use_mb_d": plan["commercial_use_mb_d"],
        "total_shortage_mb_d": plan["total_shortage_mb_d"],
        "avg_landed_usd_bbl": plan["avg_landed_usd_bbl"],
        "robustness_certificate": {
            "pass_rate": cert["robustness_pass_rate"],
            "confidence_interval": cert["confidence_interval"],
            "worst_case_shortfall_mb_d": cert["worst_case_shortfall_mb_d"],
            "cost_at_risk_usd_bbl": cert["cost_at_risk_usd_bbl"],
            "binding_constraints": cert["binding_constraints"],
        },
        "assumptions": plan["sources"],
        "evidence_ledger": {
            "input_snapshot": pb["input_snapshot"],
            "generated_at": pb["generated_at"],
        },
        "risks": _risks(cert, plan),
        "approval_requirements": [
            "Procurement controller sign-off on supplier commitments",
            "SPR drawdown requires MoPNG / ISPRL authorisation" if spr_proposal else
            "No SPR drawdown proposed",
            "Confirm OFAC screening on assigned vessels before charter",
        ],
        "contingency_plan": {
            "fallback_preset": contingency_preset,
            "note": f"if the approved plan degrades, fall back to '{contingency_preset}' "
                    f"(next-best certified plan)",
        },
        "operational_timeline": _timeline(now, procurement),
        "audit_trail": [
            {"ts": pb["generated_at"], "event": "playbook generated + certified"},
            {"ts": now.isoformat(), "event": f"packet assembled for approval by {approver}"},
        ],
    }
    return tag(packet, "HEIMDALL action packet engine", SourceKind.ENGINE,
               note="recommendation only; requires human authorisation").to_dict()


def _by_refinery(purchases: list[dict], spr: list[dict]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for p in purchases:
        r = out.setdefault(p["refinery_id"], {"crude_mb_d": 0.0, "sources": []})
        r["crude_mb_d"] = round(r["crude_mb_d"] + p["volume_mb_d"], 5)
        r["sources"].append({"supplier": p["supplier_id"], "volume_mb_d": p["volume_mb_d"]})
    for s in spr:
        r = out.setdefault(s["refinery_id"], {"crude_mb_d": 0.0, "sources": []})
        r["crude_mb_d"] = round(r["crude_mb_d"] + s["volume_mb_d"], 5)
        r["sources"].append({"supplier": s["spr_id"] + " (SPR)", "volume_mb_d": s["volume_mb_d"]})
    return out


def _risks(cert: dict, plan: dict) -> list[str]:
    risks = []
    if cert["worst_case_shortfall_mb_d"] > 0:
        risks.append(f"worst-case shortfall {cert['worst_case_shortfall_mb_d']} mb/d under stress")
    for b in cert["binding_constraints"]:
        risks.append(f"binding: {b}")
    if plan["total_shortage_mb_d"] > 0:
        risks.append(f"residual shortage {plan['total_shortage_mb_d']} mb/d even at baseline")
    return risks or ["no material residual risk identified under sampled futures"]


def _timeline(now: datetime, procurement: list[dict]) -> list[dict[str, Any]]:
    tl = [{"t_plus_days": 0, "milestone": "human authorisation"}]
    tl.append({"t_plus_days": 1, "milestone": "issue purchase confirmations + vessel charters"})
    tl.append({"t_plus_days": 3, "milestone": "loading at origin terminals"})
    arrivals = sorted({float(p["arrival_day"]) for p in procurement if p.get("arrival_day") is not None})
    if arrivals:
        tl.append({"t_plus_days": arrivals[0],
                   "milestone": "earliest modeled cargo discharge (strategic planning estimate)"})
        if arrivals[-1] > arrivals[0]:
            tl.append({"t_plus_days": arrivals[-1],
                       "milestone": "latest modeled cargo discharge in approved allocation"})
    return tl


# ------------------------------- cost of delay -------------------------------
def cost_of_delay(corridor: str, severity: float, duration_days: float,
                  decision_window_days: int = 7) -> dict[str, Any]:
    """Premium that accrues per day a decision is deferred, from cascade + MC. Planning estimate."""
    shock = [CorridorShock(corridor, severity, duration_days)]
    casc = cascade_engine.run_cascade(shock)
    mc = mc_engine.run_mc(shock)

    # extra landed-cost pressure per day if the deficit persists unmitigated ($M/day)
    per_day_musd = round(casc.deficit_mb_d * casc.landed_cost_pressure_usd_bbl, 4)
    # range from MC expected vs cost-at-risk (uncertainty band on the premium)
    lo_factor = 0.6
    hi_factor = round(mc.cost_at_risk_usd_bbl / max(mc.expected_landed_cost_usd_bbl, 1e-6), 3)
    low = round(per_day_musd * lo_factor, 4)
    high = round(per_day_musd * max(hi_factor, 1.0), 4)

    return tag({
        "corridor": corridor, "severity": severity, "duration_days": duration_days,
        "premium_per_day_musd": {"low": low, "high": high, "point": per_day_musd},
        "cumulative_over_window_musd": {
            "low": round(low * decision_window_days, 4),
            "high": round(high * decision_window_days, 4),
        },
        "decision_window_days": decision_window_days,
        "basis": "cascade deficit x landed-cost pressure, MC uncertainty band",
    }, "HEIMDALL cost-of-delay", SourceKind.ENGINE,
        note="planning estimate; premium avoided by acting now vs after a spike").to_dict()


if __name__ == "__main__":
    from ..lib import storage
    from .allocator import Scenario
    storage.init_db()
    pb = playbook_engine.generate(Scenario(corridor_states={"hormuz": "restricted"},
                                           restrict_severity=0.6))
    pkt = build_packet(pb["id"], pb["recommended"])["value"]
    print("packet:", pkt["packet_id"], "| preset:", pkt["approved_preset"],
          "| status:", pkt["status"])
    print("  procurement lines:", len(pkt["procurement_quantities"]),
          "| approvals:", len(pkt["approval_requirements"]))
    cod = cost_of_delay("hormuz", 0.5, 14)["value"]
    print("  cost-of-delay $/day range:", cod["premium_per_day_musd"])
