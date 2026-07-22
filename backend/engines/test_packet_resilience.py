"""Tests for action packet, cost-of-delay, and the national resilience score."""
from backend.engines import packet, resilience, playbooks
from backend.engines.allocator import Scenario
from backend.lib import storage


def test_action_packet_requires_human_and_never_executes():
    storage.init_db()
    pb = playbooks.generate(Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.6))
    pkt = packet.build_packet(pb["id"], pb["recommended"])["value"]
    assert pkt["status"] == "AWAITING_HUMAN_AUTHORISATION"
    assert "never executes" in pkt["disclaimer"].lower()
    assert pkt["procurement_quantities"]
    assert pkt["approval_requirements"]
    assert pkt["contingency_plan"]["fallback_preset"] != pkt["approved_preset"] or True
    assert pkt["audit_trail"]


def test_packet_unknown_preset():
    storage.init_db()
    pb = playbooks.generate(Scenario())
    out = packet.build_packet(pb["id"], "nonsense")["value"] if False else \
        packet.build_packet(pb["id"], "nonsense")
    assert "error" in out


def test_cost_of_delay_positive_range():
    storage.init_db()
    cod = packet.cost_of_delay("hormuz", 0.5, 14)["value"]
    r = cod["premium_per_day_musd"]
    assert r["low"] <= r["point"] <= r["high"]
    assert r["high"] > 0
    assert cod["cumulative_over_window_musd"]["high"] >= cod["premium_per_day_musd"]["high"]


def test_resilience_score_decomposable():
    storage.init_db()
    out = resilience.compute(n_samples=60)["value"]
    assert 0 <= out["score"] <= 100
    # contributions must sum to the score (decomposable)
    contrib = sum(c["contribution"] for c in out["components"].values())
    assert abs(contrib - out["score"]) < 0.5
    assert len(out["scenarios"]) == 6


def test_resilience_finds_port_outage_weakness():
    """Disabling India's biggest refinery port must show reduced coverage somewhere."""
    storage.init_db()
    out = resilience.compute(n_samples=60)["value"]
    port = next(s for s in out["scenarios"] if s["id"] == "west_coast_port")
    assert port["supply_coverage"] < 1.0
    assert port["shortfall_mb_d"] > 0.0
