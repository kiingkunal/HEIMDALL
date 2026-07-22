"""Monte Carlo layer (L3). The SAME deterministic cascade, evaluated over N sampled futures.

TRUTH CONSTRAINT #3: this is the ONLY layer allowed to say "probability" — here it means frequency
over sampled futures, not a calibrated forecast. numpy, SEEDED, reproducible (mc_params.yaml seed).

Cost asymmetry (doctrine): evaluating a FIXED scenario/plan under a sampled future is a cheap
cascade recompute (afford hundreds). Re-SOLVING per future is expensive — that is NOT done here.
This module supplies the distribution machinery that engines/certify.py (Phase 3) uses to stress a
plan; for Phase 1 it stresses a bare scenario.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..lib.provenance import SourceKind, tag
from .cascade import (CorridorShock, _commercial_stock_mb, _spr_usable_mb, _cfg as _cascade_cfg,
                      run_cascade)

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=1)
def _mc_cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "mc_params.yaml").read_text())


def _sample(rng: np.random.Generator, spec: dict[str, Any]) -> float:
    t = spec["type"]
    if t == "uniform":
        return float(rng.uniform(spec["a"], spec["b"]))
    if t == "normal":
        return float(rng.normal(spec["mu"], spec["sigma"]))
    if t == "bernoulli":
        return float(rng.random() < spec["p"])
    raise ValueError(f"unknown distribution type: {t}")


@dataclass
class MCResult:
    n_samples: int
    seed: int
    scenario: list[dict[str, Any]]
    base_deficit_mb_d: float
    base_duration_days: float
    # outcome distributions
    prob_shortage: float
    prob_maintain_min_inventory: float
    expected_net_shortfall_mb: float
    worst_case_net_shortfall_mb: float
    p95_net_shortfall_mb: float
    expected_landed_cost_usd_bbl: float
    cost_at_risk_usd_bbl: float          # p95 landed-cost pressure
    max_landed_cost_usd_bbl: float
    binding_factors: dict[str, float]     # how often each stressor pushed toward shortage
    note: str = ("probabilities are frequencies over sampled futures (Monte Carlo), "
                 "not calibrated forecasts")

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def run_mc(shocks: list[CorridorShock], n_samples: int | None = None,
           seed: int | None = None) -> MCResult:
    """Evaluate a scenario across sampled futures. Pure given config; seeded -> reproducible."""
    mc = _mc_cfg()
    dists = mc["distributions"]
    n = n_samples or mc["monte_carlo"]["n_samples"]
    seed = seed if seed is not None else mc["monte_carlo"]["seed"]
    tol = mc["pass_criteria"]["max_shortage_mb_d"]
    rng = np.random.default_rng(seed)

    base = run_cascade(shocks)
    casc = _cascade_cfg()["cascade"]
    india = _cascade_cfg()["india"]
    import_mb_d = india["crude_import_mb_d"]
    buffer_mb = _commercial_stock_mb() + _spr_usable_mb()
    base_duration = max((s.duration_days for s in shocks), default=0.0)
    usd_per_pct = casc["landed_cost_usd_per_bbl_per_deficit_pct"]

    net_shortfalls = np.zeros(n)
    landed_costs = np.zeros(n)
    shortage_flags = np.zeros(n, dtype=bool)
    factor_hits = {"supplier_failure": 0, "secondary_port_closure": 0, "long_duration": 0}

    for i in range(n):
        dur_mult = _sample(rng, dists["duration_multiplier"])
        freight_mult = _sample(rng, dists["freight_multiplier"])
        arrival_delay = _sample(rng, dists["vessel_arrival_delay_days"])
        port_closure = _sample(rng, dists["secondary_port_closure"])
        demand_growth = _sample(rng, dists["demand_growth_pct"])
        supplier_fail = _sample(rng, dists["supplier_failure"])
        price_drift = _sample(rng, dists["price_drift_usd"])

        deficit = base.deficit_mb_d
        # a modeled supplier drops out -> add ~a mid-size supplier's daily share to the deficit
        if supplier_fail:
            deficit += 0.10 * import_mb_d      # ~10% supplier share, demo assumption
            factor_hits["supplier_failure"] += 1
        # a second Indian discharge port closes -> effective deficit rises
        if port_closure:
            deficit *= 1.15
            factor_hits["secondary_port_closure"] += 1
        # demand growth raises consumption -> buffers drain faster (treat as extra effective deficit)
        deficit *= max(0.5, 1.0 + demand_growth / 100.0)

        eff_duration = max(0.0, base_duration * dur_mult + arrival_delay)
        if eff_duration > base_duration * 1.2:
            factor_hits["long_duration"] += 1

        cumulative = deficit * eff_duration
        net_shortfall = max(0.0, cumulative - buffer_mb)
        net_shortfalls[i] = net_shortfall
        shortage_flags[i] = net_shortfall > tol

        deficit_pct = deficit / import_mb_d * 100.0
        landed = deficit_pct * usd_per_pct
        # freight premium on the reroutable share + Brent drift, both in $/bbl pressure
        reroute_mb = sum(r["reroutable_mb_d"] for r in base.reroute)
        freight_component = (reroute_mb / import_mb_d * 100.0) * usd_per_pct * (freight_mult - 1.0)
        landed_costs[i] = max(0.0, landed + freight_component + max(0.0, price_drift))

    car_pct = mc["pass_criteria"]["cost_at_risk_percentile"]
    return MCResult(
        n_samples=n, seed=seed, scenario=base.scenario,
        base_deficit_mb_d=base.deficit_mb_d, base_duration_days=base_duration,
        prob_shortage=round(float(shortage_flags.mean()), 4),
        prob_maintain_min_inventory=round(float(1.0 - shortage_flags.mean()), 4),
        expected_net_shortfall_mb=round(float(net_shortfalls.mean()), 4),
        worst_case_net_shortfall_mb=round(float(net_shortfalls.max()), 4),
        p95_net_shortfall_mb=round(float(np.percentile(net_shortfalls, 95)), 4),
        expected_landed_cost_usd_bbl=round(float(landed_costs.mean()), 3),
        cost_at_risk_usd_bbl=round(float(np.percentile(landed_costs, car_pct)), 3),
        max_landed_cost_usd_bbl=round(float(landed_costs.max()), 3),
        binding_factors={k: round(v / n, 4) for k, v in factor_hits.items()},
    )


def mc_tagged(shocks: list[CorridorShock], **kw: Any) -> dict[str, Any]:
    result = run_mc(shocks, **kw)
    return tag(result.to_dict(), "HEIMDALL Monte Carlo layer (seeded)", SourceKind.ENGINE,
               note="frequencies over sampled futures; reproducible via mc_params seed").to_dict()


if __name__ == "__main__":
    r = run_mc([CorridorShock("hormuz", 0.5, 14)])
    print(f"Hormuz 50pct/14d MC (n={r.n_samples} seed={r.seed}):")
    print("  P(shortage):", r.prob_shortage, "| P(maintain min inv):", r.prob_maintain_min_inventory)
    print("  E[net shortfall] mb:", r.expected_net_shortfall_mb,
          "| worst:", r.worst_case_net_shortfall_mb, "| p95:", r.p95_net_shortfall_mb)
    print("  E[landed $/bbl]:", r.expected_landed_cost_usd_bbl,
          "| cost-at-risk p95:", r.cost_at_risk_usd_bbl)
    print("  binding factors:", r.binding_factors)
    # reproducibility check
    r2 = run_mc([CorridorShock("hormuz", 0.5, 14)])
    assert r.expected_net_shortfall_mb == r2.expected_net_shortfall_mb, "MC not reproducible!"
    print("  reproducible: OK")
