"""Phase 2 gate: ZERO hard-constraint violations across all three presets + greedy, and a killed
corridor is provably avoided by every plan.

validate_plan re-derives the ground-truth caps from prepare(scenario) and checks the emitted plan
against every hard constraint independently of the solver — so this catches a solver that lies."""
import json
from pathlib import Path

import pytest

from backend.engines.allocator import (Plan, Scenario, prepare, solve, three_plans, PRESETS,
                                        RESERVE_OPS_BUFFER_MB_D)
from backend.engines.greedy import solve_greedy
from backend.lib import storage

GULF_SUPPLIERS = {"iraq", "saudi_arabia", "uae", "kuwait"}   # all route through Hormuz
TOL = 1e-4


def _refineries_index(data):
    return {r["id"]: r for r in data["refineries"]}


def validate_plan(plan: Plan, scenario: Scenario) -> list[str]:
    """Return a list of hard-constraint violations. Empty list == fully feasible."""
    data = prepare(scenario)
    sup = {s["id"]: s for s in data["suppliers"]}
    refs = _refineries_index(data)
    spr_caps = {f["id"]: f["max_rate_mb_d"] for f in data["spr_facilities"]}
    excluded_ids = {e["supplier_id"] for e in data["excluded"]}
    v = []

    # per-supplier availability + existence (route/sanctions exclusion)
    per_supplier = {}
    for p in plan.purchases:
        per_supplier[p["supplier_id"]] = per_supplier.get(p["supplier_id"], 0.0) + p["volume_mb_d"]
        if p["supplier_id"] in excluded_ids:
            v.append(f"purchase from EXCLUDED supplier {p['supplier_id']}")
        if p["supplier_id"] not in sup:
            v.append(f"purchase from unavailable supplier {p['supplier_id']}")
            continue
        # grade compatibility
        if p["grade_class"] not in refs[p["refinery_id"]]["accepts"]:
            v.append(f"grade {p['grade_class']} not accepted by {p['refinery_id']}")
    for sid, vol in per_supplier.items():
        if sid in sup and vol > sup[sid]["available_mb_d"] + TOL:
            v.append(f"supplier {sid} over availability: {vol} > {sup[sid]['available_mb_d']}")

    # refinery capacity + demand balance
    inflow = {rid: 0.0 for rid in refs}
    for p in plan.purchases:
        inflow[p["refinery_id"]] += p["volume_mb_d"]
    for s in plan.spr_drawdown:
        inflow[s["refinery_id"]] += s["volume_mb_d"]
    # commercial is not attributed per-refinery in output; fold into a global balance check instead
    for rid, r in refs.items():
        if inflow[rid] > r["capacity_mb_d"] + TOL:
            v.append(f"refinery {rid} over capacity: {inflow[rid]} > {r['capacity_mb_d']}")

    # SPR facility rate caps
    spr_by_fac = {}
    for s in plan.spr_drawdown:
        spr_by_fac[s["spr_id"]] = spr_by_fac.get(s["spr_id"], 0.0) + s["volume_mb_d"]
    for fid, vol in spr_by_fac.items():
        if vol > spr_caps.get(fid, 0.0) + TOL:
            v.append(f"SPR {fid} over drawdown rate: {vol} > {spr_caps.get(fid)}")

    # reserve gap cap
    avail_total = sum(s["available_mb_d"] for s in data["suppliers"])
    demand_total = sum(r["demand_mb_d"] for r in data["refineries"])
    reserve_cap = max(0.0, demand_total - avail_total) + RESERVE_OPS_BUFFER_MB_D
    reserve_used = sum(s["volume_mb_d"] for s in plan.spr_drawdown) + plan.commercial_use_mb_d
    if reserve_used > reserve_cap + TOL:
        v.append(f"reserves over gap cap: {reserve_used} > {reserve_cap}")

    # demand balance: served + shortage == demand
    if abs(plan.served_mb_d + plan.total_shortage_mb_d - plan.demand_mb_d) > 1e-2:
        v.append("demand balance broken")
    return v


SCENARIOS = {
    "baseline": Scenario(),
    "hormuz_closed": Scenario(corridor_states={"hormuz": "closed"}),
    "hormuz_restricted": Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.6),
    "triple_closed": Scenario(corridor_states={"hormuz": "closed", "bab_el_mandeb": "closed",
                                               "suez": "closed"}),
}


@pytest.mark.parametrize("scen_name", list(SCENARIOS))
@pytest.mark.parametrize("preset", PRESETS)
def test_zero_constraint_violations_lp(scen_name, preset):
    storage.init_db()
    sc = SCENARIOS[scen_name]
    plan = solve(sc, preset)
    assert plan.status in ("OPTIMAL", "FEASIBLE"), f"{preset}/{scen_name}: {plan.status}"
    violations = validate_plan(plan, sc)
    assert violations == [], f"{preset}/{scen_name} violations: {violations}"


@pytest.mark.parametrize("scen_name", list(SCENARIOS))
def test_zero_constraint_violations_greedy(scen_name):
    storage.init_db()
    sc = SCENARIOS[scen_name]
    plan = solve_greedy(sc)
    violations = validate_plan(plan, sc)
    assert violations == [], f"greedy/{scen_name} violations: {violations}"


@pytest.mark.parametrize("preset", PRESETS)
def test_corridor_kill_avoids_hormuz(preset):
    """Kill Hormuz -> every plan buys ZERO from Hormuz (Gulf) suppliers."""
    storage.init_db()
    plan = solve(Scenario(corridor_states={"hormuz": "closed"}), preset)
    for p in plan.purchases:
        assert p["supplier_id"] not in GULF_SUPPLIERS, \
            f"{preset} still bought from {p['supplier_id']} with Hormuz closed"
    assert not (set(plan.supplier_mix) & GULF_SUPPLIERS)


def test_corridor_kill_greedy_avoids_hormuz():
    storage.init_db()
    plan = solve_greedy(Scenario(corridor_states={"hormuz": "closed"}))
    assert not (set(plan.supplier_mix) & GULF_SUPPLIERS)


def test_presets_produce_distinct_plans():
    """Cost-First vs Security-First must differ (concentration vs diversification)."""
    storage.init_db()
    cost = solve(Scenario(), "cost_first")
    sec = solve(Scenario(), "security_first")
    assert cost.bucket_mix != sec.bucket_mix
    # security-first spreads across more buckets than cost-first
    assert len([b for b, v in sec.bucket_mix.items() if v > TOL]) >= \
           len([b for b, v in cost.bucket_mix.items() if v > TOL])


def test_lp_not_worse_than_greedy_on_cost():
    """Sanity: the LP's landed cost should be <= greedy's on the cost-first objective."""
    storage.init_db()
    lp = solve(Scenario(), "cost_first")
    gr = solve_greedy(Scenario(), "cost_first")
    assert lp.landed_cost_musd_day <= gr.landed_cost_musd_day + 1e-3


def test_reserves_not_drained_in_calm_baseline():
    """No SPR drawdown when suppliers can cover demand (reserves are for genuine gaps)."""
    storage.init_db()
    for preset in PRESETS:
        plan = solve(Scenario(), preset)
        spr_total = sum(s["volume_mb_d"] for s in plan.spr_drawdown)
        assert spr_total < 0.05, f"{preset} drained SPR in calm baseline: {spr_total}"


def test_three_plans_tagged_structure():
    storage.init_db()
    out = three_plans(Scenario(corridor_states={"hormuz": "restricted"}))["value"]
    assert set(out["plans"]) == set(PRESETS)
    for p in out["plans"].values():
        assert "purchases" in p and "total_shortage_mb_d" in p


def test_scenario_controls_change_real_model_inputs():
    """Duration/demand/fleet/congestion/price controls must not be UI-only decoration."""
    storage.init_db()
    base = prepare(Scenario(duration_days=14))
    stress = prepare(Scenario(duration_days=60, price_shock_usd_bbl=20,
                              demand_change_pct=10, vessel_availability_pct=50,
                              port_congestion_pct=25))
    assert stress["brent"] == pytest.approx(base["brent"] + 20)
    assert sum(s["available_mb_d"] for s in stress["suppliers"]) == pytest.approx(
        sum(s["available_mb_d"] for s in base["suppliers"]) * 0.5, rel=1e-4)
    assert sum(r["demand_mb_d"] for r in stress["refineries"]) > \
        sum(r["demand_mb_d"] for r in base["refineries"])
    assert sum(r["capacity_mb_d"] for r in stress["refineries"]) < \
        sum(r["capacity_mb_d"] for r in base["refineries"])
    assert stress["commercial_usable_rate"] < base["commercial_usable_rate"]


def test_replay_can_pin_brent_without_reading_live_cache():
    data = prepare(Scenario(reference_brent_usd_bbl=70.84, price_shock_usd_bbl=5.0))
    assert data["brent"] == 75.84
    assert data["scenario_inputs"]["reference_brent_usd_bbl"] == 70.84


def test_plan_carries_route_eta_and_horizon():
    plan = solve(Scenario(duration_days=30), "balanced")
    assert plan.planning_horizon_days == 30
    assert all(p["arrival_day"] == p["transit_days"] for p in plan.purchases)
    assert all(p["transit_days"] <= prepare(Scenario())["window"] for p in plan.purchases)
