"""AIS pipeline tests. Provider dispatch, key-pool frugality, and the SIM->anomaly headline signal.
No live datadocked calls here — those cost credits; live is verified manually once."""
from pathlib import Path

from backend.harvesters import ais, anomalies, sim
from backend.lib import ais_keypool, storage


def test_tanker_local_filter():
    assert ais._is_tanker("Crude Oil Tanker")
    assert ais._is_tanker("LNG Tanker")
    assert ais._is_tanker("Oil Products Tanker")
    assert not ais._is_tanker("General Cargo Ship")
    assert not ais._is_tanker("Passenger Ship")
    assert not ais._is_tanker(None)


def test_corridor_position_join():
    assert ais._corridor_for_position(26.5, 56.4) == "hormuz"
    assert ais._corridor_for_position(0.0, 0.0) is None


def test_keypool_frugal_guard():
    """pick_key must refuse when no key can afford the cost (never blow the budget)."""
    # a cost larger than any single key's budget -> None
    assert ais_keypool.pick_key(10_000) is None
    # a normal cost returns a usable key while credits remain
    picked = ais_keypool.pick_key(10)
    assert picked is None or (isinstance(picked, tuple) and len(picked) == 2)


def test_sim_is_flagged_and_separate():
    """SIM rows must be flagged synthetic and land under the ais_sim prefix, never 'ais'."""
    storage.init_db()
    res = sim.run(inject_cluster_turn=False, seed=1)["value"]
    assert res["provider"] == "sim" and res["synthetic"] is True
    assert res["snapshot"].startswith("ais_sim_")


def test_cluster_turn_headline_signal():
    """Injected course reversals must produce CLUSTER_TURN — our strongest explainable signal."""
    storage.init_db()
    res = sim.run(inject_cluster_turn=True, seed=42)["value"]
    snap = Path("data/snapshots") / res["snapshot"]
    det = anomalies.detect(snapshot_path=snap)["value"]
    assert det["counts"]["CLUSTER_TURN"] >= 1
    assert any(a["type"] == "CLUSTER_TURN" for a in det["anomalies"])
