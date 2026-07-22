"""Cross-source convergence is deterministic and never labeled as probability."""
from backend.engines.intelligence import classify_origins


CFG = {"active_origin_threshold": 0.35, "confirmed_min_origins": 3, "watch_min_origins": 2}


def _components(**values):
    return [
        {"component": name, "normalized": value, "present": value is not None}
        for name, value in values.items()
    ]


def test_news_volume_and_tone_are_one_origin():
    out = classify_origins(_components(
        news_volume=0.9, tone=0.8, price_vol=0.1, anomaly=0.1, sanctions=0.0,
    ), CFG)
    assert out["active_origins"] == ["news"]
    assert out["status"] == "observing"


def test_three_independent_origins_confirm_convergence():
    out = classify_origins(_components(
        news_volume=0.8, tone=0.2, price_vol=0.6, anomaly=0.7, sanctions=0.0,
    ), CFG)
    assert out["status"] == "confirmed_convergence"
    assert out["active_origin_count"] == 3
    assert "NOT a disruption probability" in out["note"]


def test_two_origins_are_watch_not_confirmed():
    out = classify_origins(_components(
        news_volume=0.5, tone=None, price_vol=0.5, anomaly=0.1, sanctions=None,
    ), CFG)
    assert out["status"] == "watch"
    assert out["active_origin_count"] == 2
