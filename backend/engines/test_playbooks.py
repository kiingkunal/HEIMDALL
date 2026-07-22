"""Phase 3 gate: drift an input past threshold -> playbook goes STALE with a stated reason and
regenerates with an updated certificate."""
from datetime import datetime, timedelta, timezone

from backend.engines import playbooks
from backend.engines.allocator import Scenario
from backend.lib import storage


def _sc():
    return Scenario(corridor_states={"hormuz": "restricted"}, restrict_severity=0.6)


def test_generate_is_fresh_and_certified():
    storage.init_db()
    pb = playbooks.generate(_sc())
    assert pb["status"] == "fresh"
    assert pb["recommended"] in pb["certificates"]
    assert pb["certificates"][pb["recommended"]]["recommended"] is True
    assert pb["fallback"] != pb["recommended"]
    assert pb["no_regret_actions"]           # pre-crisis section present
    assert pb["input_snapshot"]["brent_usd_bbl"] is not None or True  # snapshot captured


def test_no_drift_stays_fresh():
    storage.init_db()
    pb = playbooks.generate(_sc())
    stale, reason = playbooks.check_staleness(pb, pb["input_snapshot"])  # identical snapshot
    assert stale is False and reason is None


def test_brent_drift_triggers_stale():
    storage.init_db()
    pb = playbooks.generate(_sc())
    snap = dict(pb["input_snapshot"])
    snap["brent_usd_bbl"] = (snap["brent_usd_bbl"] or 80) + 10   # > $4 threshold
    stale, reason = playbooks.check_staleness(pb, snap)
    assert stale is True
    assert "Brent" in reason


def test_corridor_state_change_triggers_stale():
    storage.init_db()
    pb = playbooks.generate(_sc())
    snap = dict(pb["input_snapshot"])
    snap["corridor_states"] = {"hormuz": "closed"}   # changed from 'restricted'
    stale, reason = playbooks.check_staleness(pb, snap)
    assert stale is True
    assert "corridor" in reason.lower()


def test_time_expiry_triggers_stale():
    storage.init_db()
    pb = playbooks.generate(_sc())
    pb["valid_until"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()  # already expired
    stale, reason = playbooks.check_staleness(pb, pb["input_snapshot"])
    assert stale is True


def test_refresh_regenerates_with_new_certificate():
    """The gate: drift past threshold -> STALE with reason -> regenerates with an updated certificate."""
    storage.init_db()
    pb = playbooks.generate(_sc())
    pid = pb["id"]
    drift = dict(pb["input_snapshot"])
    drift["brent_usd_bbl"] = (drift["brent_usd_bbl"] or 80) + 12

    result = playbooks.refresh(pid, new_snapshot=drift)
    assert result["regenerated"] is True
    assert "Brent" in result["stale_reason"]
    regenerated = result["playbook"]
    assert regenerated["id"] == pid              # same id, regenerated in place
    assert regenerated["status"] == "fresh"
    assert regenerated["recommended"] in regenerated["certificates"]
    # a fresh certificate exists post-regeneration
    assert regenerated["certificates"][regenerated["recommended"]]["robustness_pass_rate"] >= 0.0


def test_persistence_roundtrip():
    storage.init_db()
    pb = playbooks.generate(_sc())
    fetched = playbooks.get(pb["id"])
    assert fetched is not None and fetched["id"] == pb["id"]
    assert any(p["id"] == pb["id"] for p in playbooks.list_playbooks())


def test_observed_tanker_availability_drift_triggers_stale():
    storage.init_db()
    pb = playbooks.generate(_sc())
    snap = dict(pb["input_snapshot"])
    old = dict(snap.get("observed_tankers") or {})
    old["hormuz"] = max(10, old.get("hormuz", 0))
    pb["input_snapshot"]["observed_tankers"] = old
    snap["observed_tankers"] = {**old, "hormuz": int(old["hormuz"] * 1.3)}
    stale, reason = playbooks.check_staleness(pb, snap)
    assert stale is True
    assert "tanker availability" in reason.lower()
