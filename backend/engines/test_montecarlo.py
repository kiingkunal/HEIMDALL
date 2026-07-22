"""Monte Carlo layer tests: reproducibility (seeded) + discrimination (short vs safe scenarios)."""
from backend.engines.cascade import CorridorShock
from backend.engines import montecarlo as mc


def test_reproducible_with_seed():
    a = mc.run_mc([CorridorShock("hormuz", 0.5, 14)], n_samples=200, seed=123)
    b = mc.run_mc([CorridorShock("hormuz", 0.5, 14)], n_samples=200, seed=123)
    assert a.expected_net_shortfall_mb == b.expected_net_shortfall_mb
    assert a.cost_at_risk_usd_bbl == b.cost_at_risk_usd_bbl
    assert a.prob_shortage == b.prob_shortage


def test_probabilities_are_fractions():
    r = mc.run_mc([CorridorShock("hormuz", 0.5, 14)], n_samples=200)
    assert 0.0 <= r.prob_shortage <= 1.0
    assert abs(r.prob_shortage + r.prob_maintain_min_inventory - 1.0) < 1e-9


def test_short_14d_holds_inventory():
    """Hormuz 50%/14d: deficit*duration << buffer -> essentially never short."""
    r = mc.run_mc([CorridorShock("hormuz", 0.5, 14)], n_samples=300)
    assert r.prob_shortage < 0.05


def test_severe_long_scenario_shows_shortage_risk():
    """Hormuz full closure for 60d: deficit*duration exceeds buffer -> real shortage probability."""
    r = mc.run_mc([CorridorShock("hormuz", 1.0, 60)], n_samples=300)
    assert r.prob_shortage > 0.5
    assert r.worst_case_net_shortfall_mb > 0.0


def test_cost_at_risk_ge_expected():
    r = mc.run_mc([CorridorShock("hormuz", 0.6, 21)], n_samples=300)
    assert r.cost_at_risk_usd_bbl >= r.expected_landed_cost_usd_bbl
