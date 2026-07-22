"""Deterministic India Cascade Twin (L3). Pure functions, sourced constants, target <2s.

Doctrine: the simulator CALCULATES consequences. No LLM touches these numbers. Every constant
traces to config/cascade_params.yaml or a curated data/ file, cited in the output's `sources`.

Chain (one corridor, or summed across corridors):
  scenario {corridor, severity 0-1, duration_days}
    -> throughput            = india_import * corridor_import_share
    -> gross_blocked         = throughput * severity
    -> deficit (mb/d)        = gross_blocked * unreroutable_fraction[corridor]
                               (the sustained physical shortfall; the reroutable share returns
                                delayed + at freight premium — priced, not counted as deficit)
    -> inventory buffer      = commercial_stock + usable SPR (bbl)
    -> inventory_days        = buffer / deficit
    -> net_shortfall (bbl)   = max(0, deficit*duration - buffer)
    -> landed_cost_pressure  = deficit_pct * usd_per_bbl_per_deficit_pct   [planning heuristic]
    -> retail_pressure RANGE = landed_pressure * [pass_through_low, pass_through_high]

All "pressure" figures are labelled planning heuristics, never econometric forecasts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import json
import yaml

from ..lib.provenance import SourceKind, tag

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPO_ROOT / "config"
DATA_ROOT = REPO_ROOT / "data"


@lru_cache(maxsize=1)
def _cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "cascade_params.yaml").read_text())


@lru_cache(maxsize=1)
def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


@lru_cache(maxsize=1)
def _spr() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "spr.json").read_text())


@lru_cache(maxsize=1)
def _import_mix() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "import_mix.json").read_text())


@lru_cache(maxsize=1)
def _suppliers() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "suppliers.json").read_text())["suppliers"]


@lru_cache(maxsize=1)
def _refineries() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "refineries.json").read_text())["refineries"]


@lru_cache(maxsize=1)
def _grades() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "grades.json").read_text())


# ---- derived buffer volumes (bbl, in millions) ----
def _commercial_stock_mb() -> float:
    c = _cfg()["india"]
    return c["commercial_stock_days"] * c["crude_import_mb_d"]


def _spr_usable_mb() -> float:
    spr = _spr()
    bpm = spr["barrels_per_mmt"]
    return sum(f["capacity_mmt"] for f in spr["facilities"]) * bpm


def _spr_max_drawdown_mb_d() -> float:
    spr = _spr()
    bpm = spr["barrels_per_mmt"]
    return sum(f["max_drawdown_mmt_per_day"] for f in spr["facilities"]) * bpm


@dataclass
class CorridorShock:
    corridor: str
    severity: float          # 0-1
    duration_days: float


@dataclass
class CascadeResult:
    scenario: list[dict[str, Any]]
    import_mb_d: float
    gross_blocked_mb_d: float
    deficit_mb_d: float
    deficit_pct: float
    commercial_stock_mb: float
    spr_usable_mb: float
    inventory_buffer_mb: float
    inventory_days_remaining: float
    spr_max_drawdown_mb_d: float
    drawdown_rate_binding: bool
    cumulative_deficit_mb: float
    net_shortfall_mb: float
    shortage_days: float
    landed_cost_pressure_usd_bbl: float
    retail_pressure_usd_bbl: dict[str, float]
    reroute: list[dict[str, Any]]
    affected_suppliers: list[dict[str, Any]]
    refinery_impacts: list[dict[str, Any]]
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _allocate_refinery_impacts(deficit_mb_d: float,
                               affected_suppliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Allocate the modeled physical deficit by refinery grade exposure and baseline run rate."""
    utilization = float(_cfg()["india"]["refinery_utilization_fraction"])
    grade_map = _grades()["grade_class_map"]
    supplier_by_id = {s["id"]: s for s in _suppliers()}
    affected_grades: list[tuple[str, float]] = []
    for item in affected_suppliers:
        supplier = supplier_by_id.get(item["supplier_id"])
        if supplier and supplier.get("grade_id") in grade_map:
            affected_grades.append((grade_map[supplier["grade_id"]], float(item["share_pct"])))

    candidates = []
    for refinery in _refineries():
        baseline = float(refinery["capacity_mb_d"]) * utilization
        exposed_share = sum(share for grade, share in affected_grades
                            if grade in refinery["accepts_classes"])
        # Some corridors in the aggregate import mix do not map to named suppliers. In that case,
        # allocate network-wide by baseline run rate and expose that weaker basis in the output.
        generic = not affected_grades
        weight = baseline * (exposed_share if exposed_share > 0 else (1.0 if generic else 0.0))
        candidates.append({"refinery": refinery, "baseline": baseline,
                           "exposed_share": exposed_share, "weight": weight,
                           "basis": "network-wide baseline allocation" if generic
                                    else "supplier-grade compatibility exposure"})

    total_weight = sum(c["weight"] for c in candidates)
    impacts = []
    for c in candidates:
        allocation = deficit_mb_d * c["weight"] / total_weight if total_weight > 1e-9 else 0.0
        allocation = min(c["baseline"], allocation)
        post_shock = max(0.0, c["baseline"] - allocation)
        refinery = c["refinery"]
        impacts.append({
            "refinery_id": refinery["id"], "name": refinery["name"],
            "baseline_run_mb_d": round(c["baseline"], 5),
            "modeled_run_mb_d": round(post_shock, 5),
            "run_rate_impact_mb_d": round(allocation, 5),
            "run_rate_impact_pct": round(allocation / c["baseline"] * 100.0, 3)
                                   if c["baseline"] > 1e-9 else 0.0,
            "below_min_run": post_shock < float(refinery["min_run_mb_d"]),
            "exposed_supplier_share_pct": round(c["exposed_share"], 3),
            "allocation_basis": c["basis"],
        })
    return sorted(impacts, key=lambda x: -x["run_rate_impact_mb_d"])


def run_cascade(shocks: list[CorridorShock]) -> CascadeResult:
    """Deterministic cascade for one or more simultaneous corridor shocks. Pure; no I/O beyond config."""
    cfg = _cfg()
    corr = _corridors()
    india = cfg["india"]
    casc = cfg["cascade"]

    import_mb_d = india["crude_import_mb_d"]
    unrer = casc["unreroutable_fraction_by_corridor"]
    reroute_days = casc["reroute_extra_days"]

    gross_blocked = 0.0
    deficit = 0.0
    reroute_info: list[dict[str, Any]] = []
    scenario_echo: list[dict[str, Any]] = []
    affected_corridors: set[str] = set()

    for s in shocks:
        meta = corr.get(s.corridor)
        if not meta or meta.get("reroute_reference"):
            continue
        sev = _clamp(s.severity, 0.0, 1.0)
        share = meta["india_crude_share_pct"] / 100.0
        throughput = import_mb_d * share
        gb = throughput * sev
        uf = unrer.get(s.corridor, 0.5)
        d = gb * uf
        gross_blocked += gb
        deficit += d
        affected_corridors.add(s.corridor)
        rr_days = reroute_days.get(s.corridor, 0)
        reroutable_mb_d = gb * (1.0 - uf)
        if reroutable_mb_d > 1e-9:
            reroute_info.append({
                "corridor": s.corridor,
                "reroutable_mb_d": round(reroutable_mb_d, 5),
                "extra_transit_days": rr_days,
                "freight_multiplier": casc["freight_multiplier_on_reroute"],
            })
        scenario_echo.append({
            "corridor": s.corridor, "severity": sev, "duration_days": s.duration_days,
            "throughput_mb_d": round(throughput, 5), "gross_blocked_mb_d": round(gb, 5),
            "unreroutable_fraction": uf, "deficit_contribution_mb_d": round(d, 5),
        })

    duration = max((s.duration_days for s in shocks), default=0.0)

    commercial_mb = _commercial_stock_mb()
    spr_mb = _spr_usable_mb()
    buffer_mb = commercial_mb + spr_mb
    spr_rate = _spr_max_drawdown_mb_d()
    # commercial can be drawn quickly; SPR capped by pump rate. If deficit exceeds what inventory
    # can physically release per day, there is shortage even with barrels in the tank.
    max_release_rate = spr_rate + import_mb_d  # commercial effectively unrestricted intraday
    drawdown_binding = deficit > max_release_rate

    deficit_pct = (deficit / import_mb_d * 100.0) if import_mb_d else 0.0
    inv_days = (buffer_mb / deficit) if deficit > 1e-9 else float("inf")
    cumulative_deficit = deficit * duration
    net_shortfall = max(0.0, cumulative_deficit - buffer_mb)
    shortage_days = max(0.0, duration - inv_days) if inv_days != float("inf") else 0.0

    landed = deficit_pct * casc["landed_cost_usd_per_bbl_per_deficit_pct"]
    retail = {
        "low": round(landed * casc["retail_pass_through_low"], 3),
        "high": round(landed * casc["retail_pass_through_high"], 3),
    }

    # affected suppliers: those whose primary corridor is shocked
    mix = {m["supplier_id"]: m for m in _import_mix()["shares_pct"]}
    affected = [
        {"supplier_id": sid, "country": m["country"], "share_pct": m["share_pct"],
         "corridor": m["primary_corridor"]}
        for sid, m in mix.items() if m["primary_corridor"] in affected_corridors
    ]
    affected = sorted(affected, key=lambda x: -x["share_pct"])
    refinery_impacts = _allocate_refinery_impacts(deficit, affected)

    return CascadeResult(
        scenario=scenario_echo,
        import_mb_d=import_mb_d,
        gross_blocked_mb_d=round(gross_blocked, 5),
        deficit_mb_d=round(deficit, 5),
        deficit_pct=round(deficit_pct, 4),
        commercial_stock_mb=round(commercial_mb, 4),
        spr_usable_mb=round(spr_mb, 4),
        inventory_buffer_mb=round(buffer_mb, 4),
        inventory_days_remaining=round(inv_days, 3) if inv_days != float("inf") else -1.0,
        spr_max_drawdown_mb_d=round(spr_rate, 5),
        drawdown_rate_binding=drawdown_binding,
        cumulative_deficit_mb=round(cumulative_deficit, 4),
        net_shortfall_mb=round(net_shortfall, 4),
        shortage_days=round(shortage_days, 3),
        landed_cost_pressure_usd_bbl=round(landed, 3),
        retail_pressure_usd_bbl=retail,
        reroute=reroute_info,
        affected_suppliers=affected,
        refinery_impacts=refinery_impacts,
        sources=[
            "config/cascade_params.yaml", "config/corridors.yaml",
            "data/spr.json (ISPRL Phase I 5.33 MMT)", "data/import_mix.json (PPAC FY24-25)",
            "data/refineries.json", "data/suppliers.json", "data/grades.json",
        ],
    )


def cascade_tagged(shocks: list[CorridorShock]) -> dict[str, Any]:
    """Cascade result wrapped with engine provenance for the API boundary."""
    result = run_cascade(shocks)
    return tag(result.to_dict(), "HEIMDALL cascade twin (deterministic)", SourceKind.ENGINE,
               note="planning-heuristic pressures; constants sourced in result.sources").to_dict()


# convenience for a single corridor
def single(corridor: str, severity: float, duration_days: float) -> CascadeResult:
    return run_cascade([CorridorShock(corridor, severity, duration_days)])


if __name__ == "__main__":
    r = single("hormuz", 0.5, 14)
    print("Hormuz 50%/14d:")
    print("  deficit_mb_d:", r.deficit_mb_d, "| deficit_pct:", r.deficit_pct)
    print("  inventory_days:", r.inventory_days_remaining, "| net_shortfall_mb:", r.net_shortfall_mb)
    print("  landed_pressure $/bbl:", r.landed_cost_pressure_usd_bbl, "| retail:", r.retail_pressure_usd_bbl)
