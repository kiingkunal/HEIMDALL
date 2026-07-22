from pathlib import Path

from backend.lib import storage


def test_snapshot_prefixes_do_not_mix_live_and_sim(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SNAPSHOT_DIR", tmp_path)
    live = tmp_path / "ais_20260722T010000Z.parquet"
    sim = tmp_path / "ais_sim_20260722T020000Z.parquet"
    live.touch()
    sim.touch()
    assert storage.latest_snapshot("ais") == live
    assert storage.latest_snapshot("ais_sim") == sim
    assert storage.list_snapshots("ais") == [live]
