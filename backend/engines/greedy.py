"""Greedy feasible allocator — the fallback + sanity baseline behind the SAME interface as the
OR-Tools solver (allocator.solve). No optimisation: fill each refinery's demand from the cheapest
grade-compatible available supplier first, then commercial, then SPR (last resort), leaving any
remainder as shortage. Respects every hard constraint by construction, so it is always feasible.

Purpose: (1) if OR-Tools ever fails to load, HEIMDALL still returns a defensible plan; (2) it is a
lower-bound sanity check — the LP should never be WORSE than greedy on its own objective.
"""
from __future__ import annotations

from typing import Any

from ..lib.provenance import SourceKind, tag
from .allocator import (Plan, Scenario, prepare, RESERVE_OPS_BUFFER_MB_D,
                        SPR_STRATEGIC_PREMIUM_USD_BBL, COMMERCIAL_PREMIUM_USD_BBL)


def solve_greedy(scenario: Scenario, preset: str = "cost_first") -> Plan:
    data = prepare(scenario)
    suppliers = {s["id"]: dict(s) for s in data["suppliers"]}
    refineries = sorted(data["refineries"], key=lambda r: -r["demand_mb_d"])
    brent = data["brent"]

    remaining_avail = {sid: s["available_mb_d"] for sid, s in suppliers.items()}
    spr_remaining = {f["id"]: f["max_rate_mb_d"] for f in data["spr_facilities"]}
    commercial_remaining = data["commercial_usable_rate"]
    avail_total = sum(s["available_mb_d"] for s in data["suppliers"])
    demand_total = sum(r["demand_mb_d"] for r in refineries)
    reserve_remaining = max(0.0, demand_total - avail_total) + RESERVE_OPS_BUFFER_MB_D

    purchases, spr_dd = [], []
    supplier_mix, bucket_mix = {}, {}
    landed_musd, total_vol, com_use, total_short = 0.0, 0.0, 0.0, 0.0

    for r in refineries:
        need = r["demand_mb_d"]
        cap_left = r["capacity_mb_d"]
        # 1) cheapest grade-compatible suppliers first
        compat = sorted(
            [s for s in suppliers.values() if s["grade_class"] in r["accepts"]],
            key=lambda s: s["price_usd_bbl"])
        for s in compat:
            if need <= 1e-9 or cap_left <= 1e-9:
                break
            take = min(need, cap_left, remaining_avail[s["id"]])
            if take <= 1e-9:
                continue
            remaining_avail[s["id"]] -= take
            need -= take
            cap_left -= take
            landed_musd += s["price_usd_bbl"] * take
            total_vol += take
            supplier_mix[s["id"]] = round(supplier_mix.get(s["id"], 0.0) + take, 6)
            bucket_mix[s["bucket"]] = round(bucket_mix.get(s["bucket"], 0.0) + take, 6)
            purchases.append({"supplier_id": s["id"], "country": s["country"],
                              "refinery_id": r["id"], "grade_class": s["grade_class"],
                              "volume_mb_d": round(take, 6), "price_usd_bbl": s["price_usd_bbl"],
                              "rerouted": s["rerouted"], "route_corridors": s["route_corridors"],
                              "transit_days": s["transit_days"],
                              "arrival_day": s["transit_days"]})
        # 2) commercial buffer (respects reserve gap cap)
        if need > 1e-9 and cap_left > 1e-9:
            take = min(need, cap_left, commercial_remaining, reserve_remaining)
            if take > 1e-9:
                commercial_remaining -= take
                reserve_remaining -= take
                com_use += take
                need -= take
                cap_left -= take
        # 3) SPR last resort (sour crude -> only sour-accepting refineries; rate-capped; reserve gap)
        if need > 1e-9 and cap_left > 1e-9 and "medium_sour" in r["accepts"]:
            for fid in list(spr_remaining):
                if need <= 1e-9 or reserve_remaining <= 1e-9:
                    break
                take = min(need, cap_left, spr_remaining[fid], reserve_remaining)
                if take <= 1e-9:
                    continue
                spr_remaining[fid] -= take
                reserve_remaining -= take
                need -= take
                cap_left -= take
                spr_dd.append({"spr_id": fid, "refinery_id": r["id"], "volume_mb_d": round(take, 6)})
        # 4) remainder is shortage
        total_short += max(0.0, need)

    demand = round(demand_total, 6)
    total_short = round(total_short, 6)
    return Plan(
        preset=f"greedy_{preset}", label="Greedy (fallback baseline)", status="FEASIBLE",
        objective=-1.0, landed_cost_musd_day=round(landed_musd, 4),
        avg_landed_usd_bbl=round(landed_musd / total_vol, 3) if total_vol > 1e-9 else 0.0,
        total_shortage_mb_d=total_short,
        purchases=sorted(purchases, key=lambda p: -p["volume_mb_d"]),
        spr_drawdown=spr_dd, commercial_use_mb_d=round(com_use, 6),
        supplier_mix=supplier_mix, bucket_mix=bucket_mix,
        excluded_suppliers=data["excluded"], demand_mb_d=demand,
        served_mb_d=round(demand - total_short, 6), solver="greedy",
        sources=["data/suppliers.json", "data/refineries.json", "data/spr.json",
                 "config/solver_presets.yaml", "config/cascade_params.yaml",
                 "searoute (strategic planning estimates)"],
        planning_horizon_days=data["duration"], scenario_inputs=data["scenario_inputs"],
    )


def greedy_tagged(scenario: Scenario) -> dict[str, Any]:
    return tag(solve_greedy(scenario).to_dict(), "HEIMDALL greedy allocator (fallback)",
               SourceKind.ENGINE, note="feasible baseline; not optimised").to_dict()


if __name__ == "__main__":
    from ..lib import storage
    storage.init_db()
    for label, sc in [("baseline", Scenario()),
                      ("Hormuz CLOSED", Scenario(corridor_states={"hormuz": "closed"}))]:
        p = solve_greedy(sc)
        print(f"{label}: short={p.total_shortage_mb_d} avg=${p.avg_landed_usd_bbl} buckets={p.bucket_mix}")
