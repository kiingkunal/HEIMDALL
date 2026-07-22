"""Leakage guard is the honesty backbone (Truth Constraint #4: leakage is prohibited AND tested).
These tests are the 'tested for' half. Hand-computed expectations."""
from datetime import datetime, timezone

import pytest

from backend.replay import leakage_guard as lg
from backend.replay.loader import ReplayDataset


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_future_row_raises():
    with pytest.raises(lg.LeakageError):
        lg.guard_timestamp("2025-06-20T00:00:00Z", _t("2025-06-13T00:00:00"), context="unit")


def test_past_and_equal_row_ok():
    lg.guard_timestamp("2025-06-13T00:00:00Z", _t("2025-06-13T00:00:00"))   # equal -> allowed
    lg.guard_timestamp("2025-06-10T00:00:00Z", _t("2025-06-13T00:00:00"))   # past  -> allowed


def test_missing_timestamp_raises():
    with pytest.raises(lg.LeakageError):
        lg.guard_row({"id": "x"}, _t("2025-06-13T00:00:00"))


def test_guard_rows_filters_future():
    rows = [
        {"timestamp": "2025-06-10T00:00:00Z"},
        {"timestamp": "2025-06-13T00:00:00Z"},
        {"timestamp": "2025-06-20T00:00:00Z"},  # future relative to clock below
    ]
    visible = lg.guard_rows(rows, _t("2025-06-13T00:00:00"))
    assert len(visible) == 2


def test_replay_walk_never_leaks():
    """Walk the whole replay; at every tick, no visible evidence is after the clock."""
    ds = ReplayDataset()
    clock = ds.make_clock(step_hours=12)
    ticks = 0
    for now in clock.ticks():
        for ev in ds.evidence_at(now):
            assert lg._aware(ev["timestamp"]) <= now
        brent = ds.brent_at(now)
        assert brent is None or isinstance(brent, float)
        ticks += 1
    assert ticks > 0


def test_replay_brent_is_monotonic_visible():
    """Brent visible at the peak date includes the real $80.37 print; earlier does not."""
    ds = ReplayDataset()
    before_peak = ds.brent_at(_t("2025-06-12T00:00:00"))
    at_peak = ds.brent_at(_t("2025-06-19T00:00:00"))
    assert before_peak is not None and at_peak is not None
    assert at_peak >= before_peak
    assert at_peak == pytest.approx(80.37, abs=0.01)


def test_replay_window_includes_calm_price_baseline_before_first_evidence():
    start, end = ReplayDataset().window()
    assert start.date().isoformat() == "2025-05-01"
    assert end.date().isoformat() == "2025-06-30"


def test_replay_risk_inputs_do_not_include_future_evidence():
    ds = ReplayDataset()
    before = ds.risk_raw_at(_t("2025-06-12T11:59:00"))
    at = ds.risk_raw_at(_t("2025-06-12T12:00:00"))
    assert "news_volume" not in before
    assert at["news_volume"]["latest"] == 1.0
