"""National Energy Resilience Score (L4). Solver-backed, decomposable, always shown with its
breakdown. Deck framing: "HEIMDALL attacks itself daily" — it runs six curated stress scenarios,
solves + certifies a response for each, and scores how well the system holds.

Components (weights from the resilience specification):
  supply coverage 35% · playbook robustness 25% · supplier diversity 15% ·
  response cost 15% · playbook freshness 10%
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..lib.provenance import SourceKind, tag
from . import certify
from .allocator import Scenario, solve, PRESETS

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "solver_presets.yaml").read_text())

# Six curated stress scenarios (deck: the system attacks itself).
SCENARIOS = [
    {"id": "hormuz_50_14d", "name": "Hormuz 50% reduction, 14 days",
     "scenario": Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.5,
                          duration_days=14)},
    {"id": "hormuz_full_7d", "name": "Hormuz full closure, 7 days",
     "scenario": Scenario(corridor_states={"hormuz": "closed"}, duration_days=7)},
    {"id": "red_sea_30d", "name": "Red Sea closure, 30 days",
     "scenario": Scenario(corridor_states={"bab_el_mandeb": "closed", "suez": "closed"},
                          duration_days=30)},
    {"id": "major_supplier", "name": "Major supplier unavailable (Russia)",
     "scenario": Scenario(unavailable_suppliers=["russia"],
                          duration_days=_cfg()["resilience_scenarios"]["major_supplier_duration_days"])},
    {"id": "west_coast_port", "name": "Indian west-coast port outage (Sikka)",
     "scenario": Scenario(disabled_refineries=["jamnagar"],
                          duration_days=_cfg()["resilience_scenarios"]["west_coast_port_duration_days"])},
    {"id": "combined_shock", "name": "Combined corridor + price shock",
     "scenario": Scenario(corridor_states={"hormuz": "restricted", "bab_el_mandeb": "closed"},
                          restrict_severity=0.6,
                          duration_days=_cfg()["resilience_scenarios"]["combined_duration_days"],
                          price_shock_usd_bbl=_cfg()["resilience_scenarios"]["combined_price_shock_usd_bbl"])},
]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _diversity(bucket_mix: dict[str, float]) -> float:
    """1 - Herfindahl over supplier buckets. 0 = single bucket, ->1 = evenly spread."""
    total = sum(bucket_mix.values())
    if total <= 1e-9:
        return 0.0
    hhi = sum((v / total) ** 2 for v in bucket_mix.values())
    n = max(1, len(bucket_mix))
    # normalize so an even split across the available buckets scores ~1.0
    min_hhi = 1.0 / n
    return _clamp((1.0 - hhi) / (1.0 - min_hhi)) if n > 1 else 0.0


def compute(n_samples: int | None = None, fresh_fraction: float = 1.0) -> dict[str, Any]:
    """Run all six scenarios, solve + certify, aggregate into a decomposable 0-100 score."""
    scoring = _cfg()["resilience_scoring"]
    weights = scoring["weights"]
    cost_floor = float(scoring["cost_floor_usd_bbl"])
    cost_ceiling = float(scoring["cost_ceiling_usd_bbl"])
    per_scenario = []
    cov_acc = rob_acc = div_acc = cost_acc = 0.0

    for spec in SCENARIOS:
        sc = spec["scenario"]
        plans = {p: solve(sc, p) for p in PRESETS}
        cert_out = certify.recommend(plans, sc, n_samples=n_samples)
        rec = cert_out["recommended"]
        plan = plans[rec]

        coverage = _clamp(plan.served_mb_d / plan.demand_mb_d) if plan.demand_mb_d > 1e-9 else 0.0
        robustness = cert_out["certificates"][rec]["robustness_pass_rate"]
        diversity = _diversity(plan.bucket_mix)
        cost_score = _clamp((cost_ceiling - plan.avg_landed_usd_bbl)
                            / (cost_ceiling - cost_floor))

        cov_acc += coverage
        rob_acc += robustness
        div_acc += diversity
        cost_acc += cost_score
        per_scenario.append({
            "id": spec["id"], "name": spec["name"], "recommended": rec,
            "supply_coverage": round(coverage, 4), "robustness_pass_rate": round(robustness, 4),
            "supplier_diversity": round(diversity, 4), "cost_score": round(cost_score, 4),
            "avg_landed_usd_bbl": plan.avg_landed_usd_bbl,
            "shortfall_mb_d": plan.total_shortage_mb_d,
        })

    n = len(SCENARIOS)
    components = {
        "supply_coverage": round(cov_acc / n, 4),
        "playbook_robustness": round(rob_acc / n, 4),
        "supplier_diversity": round(div_acc / n, 4),
        "response_cost": round(cost_acc / n, 4),
        "playbook_freshness": round(_clamp(fresh_fraction), 4),
    }
    score = round(100.0 * sum(weights[k] * components[k] for k in weights), 2)

    return tag({
        "score": score,
        "components": {k: {"value": components[k], "weight": weights[k],
                           "contribution": round(100.0 * weights[k] * components[k], 2)}
                       for k in weights},
        "scenarios": per_scenario,
        "framing": "HEIMDALL attacks itself daily across six stress scenarios",
    }, "HEIMDALL national resilience score", SourceKind.ENGINE,
        note="solver-backed, decomposable; always shown with breakdown").to_dict()


if __name__ == "__main__":
    from ..lib import storage
    storage.init_db()
    out = compute(n_samples=100)["value"]
    print("National Energy Resilience Score:", out["score"])
    for k, c in out["components"].items():
        print(f"  {k:22s} value={c['value']} weight={c['weight']} contrib={c['contribution']}")
    print("  scenarios:")
    for s in out["scenarios"]:
        print(f"    {s['name']:38s} cov={s['supply_coverage']} rob={s['robustness_pass_rate']} "
              f"short={s['shortfall_mb_d']}")
