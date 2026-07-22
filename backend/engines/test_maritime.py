"""Like-for-like AIS pulse baselines must not mix geographic observation footprints."""
from __future__ import annotations

import pandas as pd

from . import maritime


def _frame(count: int, area: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame({
        "mmsi": [str(100000000 + index) for index in range(count)],
        "corridor": ["suez"] * count,
        "lat": [29.92] * count,
        "lon": [32.55] * count,
        "risk_observation": [True] * count,
    })
    if area is not None:
        frame["observation_area"] = area
    return frame


def test_snapshot_counts_compare_only_same_observation_area(tmp_path) -> None:
    legacy = tmp_path / "ais_1.parquet"
    same_area = tmp_path / "ais_2.parquet"
    other_area = tmp_path / "ais_3.parquet"
    _frame(7).to_parquet(legacy, index=False)
    _frame(2, "Suez south anchorage").to_parquet(same_area, index=False)
    _frame(9, "Port Said approach").to_parquet(other_area, index=False)

    assert maritime._snapshot_counts(
        [legacy, same_area, other_area], "suez", "Suez south anchorage",
    ) == [2]
