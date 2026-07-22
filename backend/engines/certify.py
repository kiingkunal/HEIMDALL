"""Robustness Certificate engine (L4). Every playbook must EARN "recommended" by surviving sampled
futures — no certificate, no recommendation.

Doctrine + cost asymmetry: we evaluate a FIXED plan under each sampled future with a cheap recompute
(NOT a re-solve). A concentrated plan loses more when its one big supplier fails; a diversified plan
absorbs it. That asymmetry is the on-camera kill shot, and it emerges from the model, not a script.

certify_plan(plan, scenario) -> Certificate. recommend(plans, scenario) certifies all three, picks
the recommended one, records why the others were rejected, and names a fallback.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..lib.provenance import SourceKind, tag
from .allocator import Plan, Scenario, prepare

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _mc() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "mc_params.yaml").read_text())


def _sample(rng, spec):
    t = spec["type"]
    if t == "uniform":
        return float(rng.uniform(spec["a"], spec["b"]))
    if t == "normal":
        return float(rng.normal(spec["mu"], spec["sigma"]))
    if t == "bernoulli":
        return float(rng.random() < spec["p"])
    raise ValueError(t)


@dataclass
class Certificate:
    preset: str
    label: str
    n_samples: int
    seed: int
    robustness_pass_rate: float          # fraction of futures with shortfall <= tolerance
    confidence_interval: list[float]     # 95% CI on the pass rate
    worst_case_shortfall_mb_d: float
    expected_shortfall_mb_d: float
    expected_landed_cost_usd_bbl: float
    cost_at_risk_usd_bbl: float          # p95 landed cost under stress
    max_delay_days: float
    failure_conditions: dict[str, float]  # among failures, how often each stressor was active
    binding_constraints: list[str]
    recommended: bool = False            # set by recommend()
    rejected_reason: str | None = None   # set by recommend() for non-recommended plans
    note: str = "robustness = frequency of futures maintaining minimum inventory (Monte Carlo)"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def certify_plan(plan: Plan, scenario: Scenario, n_samples: int | None = None,
                 seed: int | None = None) -> Certificate:
    """Stress one fixed plan across sampled futures. Cheap per-future recompute, seeded."""
    mc = _mc()
    dists = mc["distributions"]
    n = n_samples or mc["monte_carlo"]["n_samples"]
    seed = seed if seed is not None else mc["monte_carlo"]["seed"]
    tol = mc["pass_criteria"]["max_shortage_mb_d"]
    car_pct = mc["pass_criteria"]["cost_at_risk_percentile"]
    rng = np.random.default_rng(seed)

    # plan facts
    supplier_vols = dict(plan.supplier_mix)                      # supplier -> mb/d committed
    supplier_ids = list(supplier_vols)
    delivered_base = sum(supplier_vols.values())
    # Shock absorber = the nation's usable reserve stock under stress, constrained by BOTH physical
    # pump rates and the sampled disruption horizon. This is not the plan's pre-committed draw: under
    # a sampled failure India may tap remaining buffers. Longer disruptions therefore reduce the
    # sustainable mb/d support instead of disappearing from the certificate math.
    prep = prepare(scenario)
    spr_usable_mb = sum(f["usable_mb"] for f in prep["spr_facilities"])
    spr_pump_rate = sum(f["pump_rate_mb_d"] for f in prep["spr_facilities"])
    commercial_usable_mb = prep["commercial_usable_mb"]
    base_duration = prep["duration"]
    window = float(prep["window"])
    demand = plan.demand_mb_d
    n_buckets = len({p["route_corridors"][0] if p["route_corridors"] else "atlantic"
                     for p in plan.purchases}) if plan.purchases else 0
    avg_price = plan.avg_landed_usd_bbl

    shortfalls = np.zeros(n)
    costs = np.zeros(n)
    fails = np.zeros(n, dtype=bool)
    delays = np.zeros(n)
    cond_hits = {"supplier_failure": 0, "secondary_port_closure": 0,
                 "demand_growth": 0, "long_delay": 0, "extended_duration": 0}

    for i in range(n):
        dur_mult = _sample(rng, dists["duration_multiplier"])
        freight_mult = _sample(rng, dists["freight_multiplier"])
        arrival_delay = _sample(rng, dists["vessel_arrival_delay_days"])
        port_closure = _sample(rng, dists["secondary_port_closure"])
        demand_growth = _sample(rng, dists["demand_growth_pct"])
        supplier_fail = _sample(rng, dists["supplier_failure"])
        price_drift = _sample(rng, dists["price_drift_usd"])
        delays[i] = arrival_delay
        effective_duration = max(1.0, base_duration * dur_mult)
        reserve_support = (min(spr_pump_rate, spr_usable_mb / effective_duration)
                           + commercial_usable_mb / effective_duration)

        delivered = delivered_base
        # a committed supplier drops out -> its whole volume is lost (no re-solve). Concentrated
        # plans (few big suppliers) lose more on average -> this is the robustness asymmetry.
        active_conditions = []
        if supplier_fail and supplier_ids:
            lost = supplier_vols[supplier_ids[rng.integers(0, len(supplier_ids))]]
            delivered -= lost
            active_conditions.append("supplier_failure")
        # a second discharge port closes -> lose a slice of throughput
        if port_closure:
            delivered *= 0.85
            active_conditions.append("secondary_port_closure")
        # arrival delay: a fraction of cargo misses the window
        if arrival_delay > 0:
            delivered *= max(0.0, 1.0 - arrival_delay / window)
        if arrival_delay > window * 0.15:
            active_conditions.append("long_delay")
        if dur_mult > 1.15:
            active_conditions.append("extended_duration")

        demand_eff = demand * max(0.5, 1.0 + demand_growth / 100.0)
        if demand_growth > 1.0:
            active_conditions.append("demand_growth")

        shortfall = max(0.0, demand_eff - delivered - reserve_support)
        shortfalls[i] = shortfall
        failed = shortfall > tol
        fails[i] = failed
        if failed:
            for c in active_conditions:
                if c in cond_hits:
                    cond_hits[c] += 1

        costs[i] = max(0.0, avg_price * freight_mult + max(0.0, price_drift))

    n_fail = int(fails.sum())
    pass_rate = 1.0 - n_fail / n
    ci = 1.96 * math.sqrt(max(0.0, pass_rate * (1 - pass_rate) / n))

    binding = []
    max_share = (max(supplier_vols.values()) / delivered_base) if delivered_base > 1e-9 else 0.0
    if max_share > 0.5:
        top = max(supplier_vols, key=supplier_vols.get)
        binding.append(f"high single-supplier concentration ({top} {max_share:.0%})")
    if n_buckets <= 1:
        binding.append("single-corridor / single-bucket reliance")
    if plan.total_shortage_mb_d > 1e-6:
        binding.append("baseline shortage before stress")
    if not binding:
        binding.append("diversified supply; no single point of failure dominates")

    return Certificate(
        preset=plan.preset, label=plan.label, n_samples=n, seed=seed,
        robustness_pass_rate=round(pass_rate, 4),
        confidence_interval=[round(max(0.0, pass_rate - ci), 4), round(min(1.0, pass_rate + ci), 4)],
        worst_case_shortfall_mb_d=round(float(shortfalls.max()), 4),
        expected_shortfall_mb_d=round(float(shortfalls.mean()), 4),
        expected_landed_cost_usd_bbl=round(float(costs.mean()), 3),
        cost_at_risk_usd_bbl=round(float(np.percentile(costs, car_pct)), 3),
        max_delay_days=round(float(delays.max()), 2),
        failure_conditions={k: (round(v / n_fail, 4) if n_fail else 0.0) for k, v in cond_hits.items()},
        binding_constraints=binding,
    )


# minimum pass rate to be eligible for "recommended"
RECOMMEND_MIN_PASS_RATE = 0.80


def recommend(plans: dict[str, Plan], scenario: Scenario,
              n_samples: int | None = None) -> dict[str, Any]:
    """Certify all plans, pick the recommended one, record rejected reasons + a fallback.

    Recommended = highest pass rate meeting the threshold; ties broken by lower cost-at-risk.
    """
    certs = {name: certify_plan(pl, scenario, n_samples=n_samples) for name, pl in plans.items()}

    eligible = [(name, c) for name, c in certs.items()
                if c.robustness_pass_rate >= RECOMMEND_MIN_PASS_RATE]
    if eligible:
        best = min(eligible, key=lambda kv: (-kv[1].robustness_pass_rate, kv[1].cost_at_risk_usd_bbl))
    else:
        # nobody clears the bar -> recommend the most robust available, flagged
        best = max(certs.items(), key=lambda kv: kv[1].robustness_pass_rate)
    best_name = best[0]
    certs[best_name].recommended = True

    for name, c in certs.items():
        if name == best_name:
            continue
        rec = certs[best_name]
        if c.robustness_pass_rate < rec.robustness_pass_rate - 1e-9:
            c.rejected_reason = (f"lower robustness ({c.robustness_pass_rate:.0%} vs "
                                 f"{rec.robustness_pass_rate:.0%})")
        elif c.cost_at_risk_usd_bbl > rec.cost_at_risk_usd_bbl + 1e-9:
            c.rejected_reason = (f"similar robustness but higher cost-at-risk "
                                 f"(${c.cost_at_risk_usd_bbl} vs ${rec.cost_at_risk_usd_bbl})")
        else:
            c.rejected_reason = "not selected (tie-break)"

    # fallback = next-best by pass rate that is not the recommended one
    ranked = sorted(certs.items(), key=lambda kv: -kv[1].robustness_pass_rate)
    fallback = next((name for name, _ in ranked if name != best_name), None)

    return {
        "recommended": best_name,
        "recommended_pass_rate": certs[best_name].robustness_pass_rate,
        "fallback": fallback,
        "certificates": {name: c.to_dict() for name, c in certs.items()},
    }


def recommend_tagged(plans: dict[str, Plan], scenario: Scenario, **kw) -> dict[str, Any]:
    return tag(recommend(plans, scenario, **kw), "HEIMDALL robustness certifier (Monte Carlo)",
               SourceKind.ENGINE, note="no plan recommended without a certificate").to_dict()


if __name__ == "__main__":
    from ..lib import storage
    from .allocator import solve, PRESETS
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.7)
    plans = {p: solve(sc, p) for p in PRESETS}
    out = recommend(plans, sc)
    print("recommended:", out["recommended"], "| fallback:", out["fallback"])
    for name, c in out["certificates"].items():
        print(f"  {c['label']:14s} pass={c['robustness_pass_rate']:.0%} "
              f"worst_short={c['worst_case_shortfall_mb_d']} car=${c['cost_at_risk_usd_bbl']} "
              f"rec={c['recommended']} rej={c['rejected_reason']}")
