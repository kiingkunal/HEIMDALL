"""OR-Tools response optimizer (L4). Turns a disruption scenario into a demonstrably FEASIBLE
crude-procurement plan. Three weight presets over the SAME model -> Cost-First, Security-First,
Balanced.

Doctrine: the OPTIMIZER makes quantities feasible. Hard constraints are structural (infeasible,
never penalized); shortage is the only slack and it is penalized, never hidden. Every plan that
comes out of here satisfies: supplier availability, route closure, port + refinery capacity, grade
compatibility, arrival window, minimum inventory floors, OFAC exclusion, max SPR drawdown rate,
and demand balance. The Phase 2 gate proves zero violations.

Model (scenario-horizon average rates in mb/d; LP via GLOP — continuous, fast, deterministic):
  vars  x[s,r]   supplier->refinery crude volume (only grade-compatible pairs)
        spr[f,r] SPR facility->refinery drawdown
        com[r]   commercial inventory -> refinery
        short[r] unmet demand slack (>=0)
        mbv      max diversification-bucket volume (concentration proxy)
  see constraints + objective inline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag
from . import routes
from .sanctions_screen import is_supplier_sanctioned

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
CONFIG_ROOT = REPO_ROOT / "config"


@lru_cache(maxsize=1)
def _suppliers() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "suppliers.json").read_text())["suppliers"]


@lru_cache(maxsize=1)
def _refineries() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "refineries.json").read_text())["refineries"]


@lru_cache(maxsize=1)
def _grades() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "grades.json").read_text())


@lru_cache(maxsize=1)
def _spr() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "spr.json").read_text())


@lru_cache(maxsize=1)
def _ports() -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in json.loads((DATA_ROOT / "ports.json").read_text())["ports"]}


@lru_cache(maxsize=1)
def _cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "solver_presets.yaml").read_text())


@lru_cache(maxsize=1)
def _cascade_cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "cascade_params.yaml").read_text())


@lru_cache(maxsize=1)
def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


# Strategic reserves are LAST RESORT, not a cheap source. We price them above market so the solver
# buys crude first, taps commercial next, and draws SPR only when supply genuinely cannot cover
# demand (the shortage penalty then makes it worthwhile). Premiums are shadow costs, not cash prices.
SPR_STRATEGIC_PREMIUM_USD_BBL = 40.0    # drawing national strategic reserve is expensive to justify
COMMERCIAL_PREMIUM_USD_BBL = 15.0       # using commercial buffer sits between purchases and SPR
# Reserves (SPR + commercial) exist for genuine supply GAPS, not routine optimisation. Cap total
# reserve draw at the actual scarcity (demand minus available purchasable supply) plus a small
# buffer for grade-mismatch friction (a sour-only refinery may need SPR even when aggregate supply
# looks sufficient). This stops the solver draining strategic reserves in calm markets.
RESERVE_OPS_BUFFER_MB_D = 0.5


def _grade_class(grade_id: str) -> str:
    return _grades()["grade_class_map"][grade_id]


def _brent() -> float:
    """Live/replay Brent if available, else the config default."""
    rec = storage.get_latest("prices", "brent_spot")
    if rec:
        v = rec["payload"].get("value", {})
        if v.get("price_usd_per_bbl"):
            return float(v["price_usd_per_bbl"])
    return _cfg()["pricing"]["default_brent_usd_bbl"]


def _route_risk(corridors_crossed: list[str], rerouted: bool,
                live_risk: dict[str, float] | None) -> float:
    """0-1 route risk = max risk over crossed corridors; a Cape reroute is treated as low-risk."""
    if rerouted or not corridors_crossed:
        return 0.05
    risks = []
    for c in corridors_crossed:
        if live_risk and c in live_risk:
            risks.append(live_risk[c] / 100.0)
        else:
            risks.append(_corridors().get(c, {}).get("strategic_weight", 0.5))
    return max(risks) if risks else 0.1


@dataclass
class Plan:
    preset: str
    label: str
    status: str                 # OPTIMAL | FEASIBLE | INFEASIBLE
    objective: float
    landed_cost_musd_day: float
    avg_landed_usd_bbl: float
    total_shortage_mb_d: float
    purchases: list[dict[str, Any]]      # supplier -> refinery volumes
    spr_drawdown: list[dict[str, Any]]
    commercial_use_mb_d: float
    supplier_mix: dict[str, float]
    bucket_mix: dict[str, float]
    excluded_suppliers: list[dict[str, str]]
    demand_mb_d: float
    served_mb_d: float
    solver: str
    sources: list[str]
    planning_horizon_days: float
    scenario_inputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Scenario:
    corridor_states: dict[str, str] = field(default_factory=dict)   # corridor -> open|restricted|closed
    restrict_severity: float = 0.5    # availability multiplier reduction for 'restricted' corridors
    live_risk: dict[str, float] | None = None   # optional corridor->risk index (0-100) for route risk
    unavailable_suppliers: list[str] = field(default_factory=list)  # suppliers forced out (e.g. producer outage)
    disabled_refineries: list[str] = field(default_factory=list)    # plants whose discharge port is out (capacity->0)
    duration_days: float = field(default_factory=lambda: float(
        _cfg()["scenario_controls"]["default_duration_days"]))
    price_shock_usd_bbl: float = field(default_factory=lambda: float(
        _cfg()["scenario_controls"]["default_price_shock_usd_bbl"]))
    demand_change_pct: float = field(default_factory=lambda: float(
        _cfg()["scenario_controls"]["default_demand_change_pct"]))
    vessel_availability_pct: float = field(default_factory=lambda: float(
        _cfg()["scenario_controls"]["default_vessel_availability_pct"]))
    port_congestion_pct: float = field(default_factory=lambda: float(
        _cfg()["scenario_controls"]["default_port_congestion_pct"]))
    # Internal replay/backtest pin. Live calls leave this unset and read the freshest cached Brent.
    # Historical evaluation sets it to the leakage-guarded EIA print visible at the sim clock so a
    # later live cache can never contaminate the past.
    reference_brent_usd_bbl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _bounded(value: float, controls: dict[str, Any], name: str) -> float:
    """Clamp one scenario control to its sourced min/max range."""
    return max(float(controls[f"min_{name}"]), min(float(controls[f"max_{name}"]), float(value)))


# ---------------- shared preparation (used by LP solver AND greedy fallback) ----------------
def prepare(scenario: Scenario) -> dict[str, Any]:
    """Resolve availability, routes, prices, demand, and exclusions under the scenario. Pure."""
    cfg = _cfg()
    controls = cfg["scenario_controls"]
    duration = _bounded(scenario.duration_days, controls, "duration_days")
    price_shock = _bounded(scenario.price_shock_usd_bbl, controls, "price_shock_usd_bbl")
    demand_change = _bounded(scenario.demand_change_pct, controls, "demand_change_pct")
    vessel_availability = _bounded(
        scenario.vessel_availability_pct, controls, "vessel_availability_pct")
    port_congestion = _bounded(scenario.port_congestion_pct, controls, "port_congestion_pct")
    reference_brent = (_brent() if scenario.reference_brent_usd_bbl is None
                       else float(scenario.reference_brent_usd_bbl))
    brent = max(0.0, reference_brent + price_shock)
    window = cfg["solver"]["arrival_window_days"]

    suppliers = []
    excluded = []
    for s in _suppliers():
        sid = s["id"]
        # OFAC exclusion (hard): sanctioned supplier is removed from the feasible set entirely.
        if s.get("ofac_flag") or is_supplier_sanctioned(s):
            excluded.append({"supplier_id": sid, "reason": "OFAC sanctions exclusion"})
            continue
        if sid in scenario.unavailable_suppliers:
            excluded.append({"supplier_id": sid, "reason": "supplier unavailable (producer/export outage)"})
            continue
        feas = routes.route_feasibility(sid, scenario.corridor_states)
        if not feas["available"]:
            excluded.append({"supplier_id": sid, "reason": feas["reason"]})
            continue
        if feas["transit_days"] > window:
            excluded.append({"supplier_id": sid,
                             "reason": f"transit {feas['transit_days']}d > window {window}d"})
            continue
        avail = s["available_mb_d"] * vessel_availability / 100.0
        # restricted corridor on the route throttles availability
        if any(scenario.corridor_states.get(c) == "restricted" for c in feas["route_corridors"]):
            avail *= (1.0 - scenario.restrict_severity)
        price = brent + s["base_price_usd_per_bbl"] + feas["freight_usd_bbl"]
        suppliers.append({
            "id": sid, "country": s["country"], "grade_class": _grade_class(s["grade_id"]),
            "available_mb_d": round(avail, 5), "price_usd_bbl": round(price, 3),
            "transit_days": feas["transit_days"], "rerouted": feas["rerouted"],
            "route_corridors": feas["route_corridors"], "bucket": s["diversification_bucket"],
            "route_risk": round(_route_risk(feas["route_corridors"], feas["rerouted"],
                                            scenario.live_risk), 3),
        })

    refineries = []
    utilization = float(_cascade_cfg()["india"]["refinery_utilization_fraction"])
    congestion_factor = 1.0 - port_congestion / 100.0
    demand_factor = 1.0 + demand_change / 100.0
    for r in _refineries():
        port = _ports().get(r["port_id"], {})
        cap = min(r["capacity_mb_d"], port.get("capacity_mb_d", r["capacity_mb_d"]))
        cap *= congestion_factor
        # a disabled discharge port zeroes intake capacity but demand persists -> forced shortage
        # (crude exists but cannot reach the plant), which is exactly a west-coast port outage.
        if r["id"] in scenario.disabled_refineries:
            cap = 0.0
        refineries.append({
            "id": r["id"], "name": r["name"], "capacity_mb_d": cap,
            "accepts": set(r["accepts_classes"]),
            "demand_mb_d": round(r["capacity_mb_d"] * utilization * demand_factor, 5),
        })

    # SPR facilities: stored crude modeled medium_sour; capped by both pump rate and the usable
    # stock above the strategic floor across this scenario horizon.
    bpm = _spr()["barrels_per_mmt"]
    spr_floor = float(cfg["floors"]["spr_min_fraction"])
    spr_facilities = []
    for f in _spr()["facilities"]:
        usable_mb = f["capacity_mmt"] * bpm * (1.0 - spr_floor)
        pump_rate = f["max_drawdown_mmt_per_day"] * bpm
        spr_facilities.append({
            "id": f["id"], "name": f["name"], "usable_mb": round(usable_mb, 5),
            "pump_rate_mb_d": round(pump_rate, 5),
            "max_rate_mb_d": round(min(pump_rate, usable_mb / duration), 5),
            "grade_class": "medium_sour",
        })

    # Commercial inventory usable rate over the scenario horizon (above the min-days floor).
    ci = _cascade_cfg()["india"]
    commercial_total_mb = ci["commercial_stock_days"] * ci["crude_import_mb_d"]
    floor_mb = cfg["floors"]["commercial_min_days"] * ci["crude_import_mb_d"]
    commercial_usable_mb = max(0.0, commercial_total_mb - floor_mb)
    commercial_usable_rate = commercial_usable_mb / duration

    scenario_inputs = {
        "duration_days": duration,
        "price_shock_usd_bbl": price_shock,
        "demand_change_pct": demand_change,
        "vessel_availability_pct": vessel_availability,
        "port_congestion_pct": port_congestion,
        "reference_brent_usd_bbl": round(reference_brent, 3),
    }

    return {
        "suppliers": suppliers, "refineries": refineries, "spr_facilities": spr_facilities,
        "commercial_usable_rate": round(commercial_usable_rate, 5),
        "commercial_usable_mb": round(commercial_usable_mb, 5), "brent": brent,
        "excluded": excluded, "window": window, "duration": duration,
        "scenario_inputs": scenario_inputs,
    }


# ------------------------------------- OR-Tools LP -------------------------------------
def solve(scenario: Scenario, preset: str) -> Plan:
    from ortools.linear_solver import pywraplp

    data = prepare(scenario)
    weights = _cfg()["presets"][preset]
    suppliers = data["suppliers"]
    refineries = data["refineries"]
    spr_fac = data["spr_facilities"]

    solver = pywraplp.Solver.CreateSolver("GLOP")
    solver.set_time_limit(_cfg()["solver"]["time_limit_ms"])
    INF = solver.infinity()

    # ---- variables ----
    x = {}   # (sid, rid) -> volume, only grade-compatible
    for s in suppliers:
        for r in refineries:
            if s["grade_class"] in r["accepts"]:
                x[(s["id"], r["id"])] = solver.NumVar(0.0, INF, f"x_{s['id']}_{r['id']}")
    spr = {}  # (fid, rid)
    for f in spr_fac:
        for r in refineries:
            if f["grade_class"] in r["accepts"]:
                spr[(f["id"], r["id"])] = solver.NumVar(0.0, INF, f"spr_{f['id']}_{r['id']}")
    com = {r["id"]: solver.NumVar(0.0, INF, f"com_{r['id']}") for r in refineries}
    short = {r["id"]: solver.NumVar(0.0, INF, f"short_{r['id']}") for r in refineries}
    mbv = solver.NumVar(0.0, INF, "max_bucket_vol")

    # ---- constraints ----
    # (1) demand balance per refinery (shortage is slack)
    for r in refineries:
        terms = [x[(s["id"], r["id"])] for s in suppliers if (s["id"], r["id"]) in x]
        terms += [spr[(f["id"], r["id"])] for f in spr_fac if (f["id"], r["id"]) in spr]
        solver.Add(solver.Sum(terms) + com[r["id"]] + short[r["id"]] == r["demand_mb_d"])

    # (2) supplier availability
    for s in suppliers:
        outs = [x[(s["id"], r["id"])] for r in refineries if (s["id"], r["id"]) in x]
        if outs:
            solver.Add(solver.Sum(outs) <= s["available_mb_d"])

    # (3) refinery + (4) port capacity (cap already min'd with port in prepare)
    for r in refineries:
        inflow = [x[(s["id"], r["id"])] for s in suppliers if (s["id"], r["id"]) in x]
        inflow += [spr[(f["id"], r["id"])] for f in spr_fac if (f["id"], r["id"]) in spr]
        inflow += [com[r["id"]]]
        solver.Add(solver.Sum(inflow) <= r["capacity_mb_d"])

    # (9) max SPR drawdown rate per facility
    for f in spr_fac:
        outs = [spr[(f["id"], r["id"])] for r in refineries if (f["id"], r["id"]) in spr]
        if outs:
            solver.Add(solver.Sum(outs) <= f["max_rate_mb_d"])

    # (7) commercial inventory floor (usable rate cap)
    solver.Add(solver.Sum(com.values()) <= data["commercial_usable_rate"])

    # (7b) reserves-for-gaps-only: total SPR + commercial <= actual scarcity + grade-friction buffer
    avail_total = sum(s["available_mb_d"] for s in suppliers)
    demand_total = sum(r["demand_mb_d"] for r in refineries)
    reserve_cap = max(0.0, demand_total - avail_total) + RESERVE_OPS_BUFFER_MB_D
    reserve_vars = list(spr.values()) + list(com.values())
    if reserve_vars:
        solver.Add(solver.Sum(reserve_vars) <= reserve_cap)

    # concentration proxy: mbv >= total volume from each diversification bucket
    buckets = {}
    for s in suppliers:
        buckets.setdefault(s["bucket"], []).append(s["id"])
    for bucket, sids in buckets.items():
        vol = [x[(sid, r["id"])] for sid in sids for r in refineries if (sid, r["id"]) in x]
        if vol:
            solver.Add(mbv >= solver.Sum(vol))

    # ---- objective ----
    obj = solver.Objective()
    for (sid, rid), var in x.items():
        s = next(z for z in suppliers if z["id"] == sid)
        cost = weights["w_cost"] * s["price_usd_bbl"]
        cost += weights["w_delay"] * s["transit_days"]
        cost += weights["w_route_risk"] * s["route_risk"]
        obj.SetCoefficient(var, cost)
    for (fid, rid), var in spr.items():
        # SPR shadow cost: above-market strategic premium + explicit depletion penalty
        obj.SetCoefficient(var, weights["w_cost"] * (data["brent"] + SPR_STRATEGIC_PREMIUM_USD_BBL)
                           + weights["w_spr_depletion"])
    for rid, var in com.items():
        obj.SetCoefficient(var, weights["w_cost"] * (data["brent"] + COMMERCIAL_PREMIUM_USD_BBL))
    for rid, var in short.items():
        obj.SetCoefficient(var, weights["w_shortage"])
    obj.SetCoefficient(mbv, weights["w_concentration"])
    obj.SetMinimization()

    status = solver.Solve()
    status_name = {pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE",
                   pywraplp.Solver.INFEASIBLE: "INFEASIBLE"}.get(status, "UNKNOWN")

    return _extract_plan(preset, weights["label"], status_name, solver, x, spr, com, short,
                         suppliers, refineries, data, "OR-Tools GLOP")


def _extract_plan(preset, label, status_name, solver, x, spr, com, short,
                  suppliers, refineries, data, solver_name) -> Plan:
    def val(v):
        return round(v.solution_value(), 6)

    purchases, spr_dd, supplier_mix, bucket_mix = [], [], {}, {}
    landed_musd = 0.0
    total_vol = 0.0
    for (sid, rid), var in x.items():
        v = val(var)
        if v > 1e-6:
            s = next(z for z in suppliers if z["id"] == sid)
            purchases.append({"supplier_id": sid, "country": s["country"], "refinery_id": rid,
                              "grade_class": s["grade_class"], "volume_mb_d": v,
                              "price_usd_bbl": s["price_usd_bbl"], "rerouted": s["rerouted"],
                              "route_corridors": s["route_corridors"],
                              "transit_days": s["transit_days"],
                              "arrival_day": s["transit_days"]})
            landed_musd += s["price_usd_bbl"] * v
            total_vol += v
            supplier_mix[sid] = round(supplier_mix.get(sid, 0.0) + v, 6)
            bucket_mix[s["bucket"]] = round(bucket_mix.get(s["bucket"], 0.0) + v, 6)
    com_use = sum(val(v) for v in com.values())
    for (fid, rid), var in spr.items():
        v = val(var)
        if v > 1e-6:
            spr_dd.append({"spr_id": fid, "refinery_id": rid, "volume_mb_d": v})
    total_short = round(sum(val(v) for v in short.values()), 6)
    demand = round(sum(r["demand_mb_d"] for r in refineries), 6)
    served = round(demand - total_short, 6)

    return Plan(
        preset=preset, label=label, status=status_name,
        objective=round(solver.Objective().Value(), 4) if status_name != "INFEASIBLE" else -1.0,
        landed_cost_musd_day=round(landed_musd, 4),
        avg_landed_usd_bbl=round(landed_musd / total_vol, 3) if total_vol > 1e-9 else 0.0,
        total_shortage_mb_d=total_short,
        purchases=sorted(purchases, key=lambda p: -p["volume_mb_d"]),
        spr_drawdown=spr_dd, commercial_use_mb_d=round(com_use, 6),
        supplier_mix=supplier_mix, bucket_mix=bucket_mix,
        excluded_suppliers=data["excluded"], demand_mb_d=demand, served_mb_d=served,
        solver=solver_name,
        sources=["data/suppliers.json", "data/refineries.json", "data/spr.json",
                 "config/solver_presets.yaml", "config/cascade_params.yaml",
                 "searoute (strategic planning estimates)"],
        planning_horizon_days=data["duration"], scenario_inputs=data["scenario_inputs"],
    )


PRESETS = ("cost_first", "security_first", "balanced")


def scenario_options() -> dict[str, Any]:
    """Config-backed controls and outage targets for the Scenario Lab."""
    corridors = [{"id": cid, "name": meta["name"]}
                 for cid, meta in _corridors().items() if not meta.get("reroute_reference")]
    suppliers = [{"id": s["id"], "name": s["country"]} for s in _suppliers()]
    refineries = [{"id": r["id"], "name": r["name"]} for r in _refineries()]
    return tag({"controls": _cfg()["scenario_controls"], "corridors": corridors,
                "suppliers": suppliers, "refineries": refineries},
               "HEIMDALL scenario configuration", SourceKind.CONFIG,
               note="control bounds are demo assumptions; outage targets come from curated data").to_dict()


def three_plans(scenario: Scenario) -> dict[str, Any]:
    """Solve all three presets; provenance-tagged for the API."""
    plans = {p: solve(scenario, p).to_dict() for p in PRESETS}
    return tag({"scenario": scenario.to_dict(),
                "plans": plans},
               "HEIMDALL response optimizer (OR-Tools)", SourceKind.ENGINE,
               note="feasible plans; searoute routes are strategic planning estimates").to_dict()


if __name__ == "__main__":
    storage.init_db()
    for label, sc in [("baseline (all open)", Scenario()),
                      ("Hormuz CLOSED", Scenario(corridor_states={"hormuz": "closed"}))]:
        print(f"\n=== {label} ===")
        for p in PRESETS:
            plan = solve(sc, p)
            print(f"  {plan.label:14s} status={plan.status} short={plan.total_shortage_mb_d} "
                  f"avg_landed=${plan.avg_landed_usd_bbl} buckets={plan.bucket_mix}")
