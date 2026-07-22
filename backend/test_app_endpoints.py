"""API adapter tests for the War Room's network and chronological replay surfaces."""
from datetime import datetime

from backend.app import (ais_status, corridor_intelligence, network, replay_backtest, replay_frame,
                         scenario_options)


def test_network_endpoint_exposes_curated_twin_nodes_with_provenance():
    payload = network()
    assert payload["provenance"]["kind"] == "config"
    assert len(payload["value"]["refineries"]) == 8
    assert len(payload["value"]["spr"]) == 3
    assert all("lat" in node and "lon" in node for node in payload["value"]["refineries"])


def test_replay_frame_is_chronological_and_uses_authoritative_brent():
    payload = replay_frame("2025-06-18T12:00:00Z")
    frame = payload["value"]
    sim_now = datetime.fromisoformat(frame["sim_now"])
    assert frame["brent_usd_bbl"] == 78.38
    assert frame["latest_evidence"]["id"] == "ev-2025-0617-whitehouse"
    assert all(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) <= sim_now
               for row in frame["visible_evidence"])
    assert frame["risk"]["note"].endswith("NOT a probability")
    assert payload["provenance"]["kind"] == "replay"


def test_intelligence_endpoint_keeps_convergence_separate_from_probability():
    payload = corridor_intelligence()
    assert set(payload["corridors"]) == {"hormuz", "bab_el_mandeb", "suez", "malacca"}
    for item in payload["corridors"].values():
        assert "NOT a disruption probability" in item["value"]["convergence"]["note"]


def test_ais_status_never_exposes_credentials():
    payload = ais_status()
    assert payload["credential_exposed"] is False
    assert "key" not in " ".join(payload).lower()


def test_scenario_options_are_config_backed():
    payload = scenario_options()
    assert payload["provenance"]["kind"] == "config"
    assert payload["value"]["controls"]["default_duration_days"] == 14
    assert len(payload["value"]["suppliers"]) >= 8
    assert len(payload["value"]["refineries"]) >= 6


def test_backtest_endpoint_serves_precomputed_proof_without_rerunning():
    payload = replay_backtest()
    if "error" in payload:  # clean checkout before `make backtest`
        assert "make replay-lock" in payload["error"]
        return
    assert payload["provenance"]["kind"] == "replay"
    assert payload["value"]["metrics"]["hard_constraint_violations"] == 0
    assert "planning counterfactual" in payload["provenance"]["note"]
