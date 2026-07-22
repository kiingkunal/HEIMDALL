"""Robustness certificate tests: reproducibility, concentration asymmetry, and the rule that no
plan is 'recommended' without clearing the certificate bar."""
from backend.engines.allocator import Scenario, solve, PRESETS
from backend.engines.certify import certify_plan, recommend, RECOMMEND_MIN_PASS_RATE
from backend.lib import storage


def _plans(sc):
    return {p: solve(sc, p) for p in PRESETS}


def test_certificate_reproducible():
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.7)
    pl = solve(sc, "cost_first")
    a = certify_plan(pl, sc, seed=7)
    b = certify_plan(pl, sc, seed=7)
    assert a.robustness_pass_rate == b.robustness_pass_rate
    assert a.worst_case_shortfall_mb_d == b.worst_case_shortfall_mb_d


def test_pass_rate_is_fraction_with_ci():
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "closed"})
    c = certify_plan(solve(sc, "cost_first"), sc)
    assert 0.0 <= c.robustness_pass_rate <= 1.0
    lo, hi = c.confidence_interval
    assert lo <= c.robustness_pass_rate <= hi


def test_concentration_has_higher_worst_case():
    """Cost-First (concentrated) must not be MORE robust than Security-First on worst-case shortfall."""
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "closed"})
    cost = certify_plan(solve(sc, "cost_first"), sc)
    sec = certify_plan(solve(sc, "security_first"), sc)
    assert cost.worst_case_shortfall_mb_d >= sec.worst_case_shortfall_mb_d


def test_recommend_sets_exactly_one_and_needs_certificate():
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.6)
    out = recommend(_plans(sc), sc)
    certs = out["certificates"]
    recs = [n for n, c in certs.items() if c["recommended"]]
    assert len(recs) == 1
    assert out["recommended"] == recs[0]
    # recommended plan carries a pass rate; rejected ones carry a reason
    assert certs[out["recommended"]]["rejected_reason"] is None
    for n, c in certs.items():
        if n != out["recommended"]:
            assert c["rejected_reason"]


def test_recommended_meets_bar_when_possible():
    storage.init_db()
    sc = Scenario()   # calm baseline -> at least one plan should clear the bar
    out = recommend(_plans(sc), sc)
    rec = out["certificates"][out["recommended"]]
    assert rec["robustness_pass_rate"] >= RECOMMEND_MIN_PASS_RATE


def test_fallback_differs_from_recommended():
    storage.init_db()
    sc = Scenario(corridor_states={"hormuz": "closed"})
    out = recommend(_plans(sc), sc)
    assert out["fallback"] != out["recommended"]


def test_longer_disruption_cannot_improve_fixed_plan_shortfall():
    storage.init_db()
    short = Scenario(corridor_states={"hormuz": "closed"}, duration_days=7)
    long = Scenario(corridor_states={"hormuz": "closed"}, duration_days=60)
    short_cert = certify_plan(solve(short, "cost_first"), short, seed=17)
    long_cert = certify_plan(solve(long, "cost_first"), long, seed=17)
    assert long_cert.expected_shortfall_mb_d >= short_cert.expected_shortfall_mb_d
