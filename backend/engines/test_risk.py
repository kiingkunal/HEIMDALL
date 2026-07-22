"""Risk Index engine tests. Hand-computed against config/risk_weights.yaml.
weights: news_volume .25, tone .15, price_vol .20, anomaly .25, static .10, sanctions .05."""
import pytest

from backend.engines import risk


def test_norm_tone():
    assert risk.norm_tone(-10.0) == pytest.approx(1.0)
    assert risk.norm_tone(2.0) == pytest.approx(0.0)
    assert risk.norm_tone(-4.0) == pytest.approx(0.5)      # (2-(-4))/(2-(-10)) = 6/12
    assert risk.norm_tone(None) is None


def test_norm_static_hormuz():
    assert risk.norm_static("hormuz") == pytest.approx(0.42)   # 0.42 share * 1.0 weight


def test_norm_anomaly_and_price():
    assert risk.norm_anomaly(5) == pytest.approx(1.0)      # saturation=5
    assert risk.norm_anomaly(2) == pytest.approx(0.4)
    assert risk.norm_price_vol(0.80) == pytest.approx(1.0)  # cap=0.80
    assert risk.norm_price_vol(0.40) == pytest.approx(0.5)


def test_norm_news_volume_zscore():
    # series [1,1,1,1,4]: mu=1.6 sd=1.2 -> z(4)=2.0 -> /cap(3) = 0.6667
    n = risk.norm_news_volume(4.0, [1, 1, 1, 1, 4])
    assert n == pytest.approx(0.6667, abs=1e-3)
    assert risk.norm_news_volume(1.0, [1, 1, 1]) == pytest.approx(0.0)  # at/below mean -> 0


def test_fuse_index_hand_computed():
    normalized = {"news_volume": 0.8, "tone": 0.5, "price_vol": 0.4,
                  "anomaly": 0.6, "static": 0.42, "sanctions": 0.0}
    # .25*.8 + .15*.5 + .20*.4 + .25*.6 + .10*.42 + .05*0 = .20+.075+.08+.15+.042 = .547
    index, breakdown = risk.fuse(normalized)
    assert index == pytest.approx(54.7, abs=1e-2)
    assert len(breakdown) == 6


def test_fuse_all_max_is_100():
    normalized = {c: 1.0 for c in risk.COMPONENTS}
    index, _ = risk.fuse(normalized)
    assert index == pytest.approx(100.0)


def test_confidence_full_signals():
    # all 5 signals present and equal -> agreement 1, count 1, completeness 1, freshness 1 -> 1.0
    normalized = {k: 0.7 for k in risk.SIGNAL_KEYS}
    conf, bd = risk.confidence(normalized, freshness=1.0)
    assert conf == pytest.approx(1.0)
    assert bd["independent_signal_count"] == pytest.approx(1.0)


def test_confidence_sparse_lowers_score():
    normalized = {"tone": 0.5}   # only 1 of 5 signals
    conf, bd = risk.confidence(normalized, freshness=1.0)
    assert conf < 0.7
    assert bd["independent_signal_count"] == pytest.approx(0.2)


def test_index_is_not_probability_label():
    r = risk.compute("hormuz", {"tone": {"latest": -5.0}})
    assert "NOT a probability" in r.note
    assert 0 <= r.index <= 100
    assert 0 <= r.confidence <= 1


def test_missing_signals_tracked():
    r = risk.compute("hormuz", {"tone": {"latest": -5.0}})
    assert "tone" in r.present_signals
    assert "anomaly" in r.missing_signals and "news_volume" in r.missing_signals


def test_contradiction_detection():
    # news very high, price very low -> flagged mixed evidence
    r = risk.compute("hormuz", {
        "news_volume": {"latest": 10.0, "series": [1, 1, 1, 1, 1, 10]},
        "price_vol": {"annualized": 0.02},
    })
    assert r.contradictions
