import json

import pytest

from backend.replay.backtest import (create_config_lock, run_backtest, validate_config_lock,
                                     validate_dataset)


def test_dataset_is_sourced_chronological_and_fingerprinted():
    result = validate_dataset()
    assert result["source_urls_preserved"] is True
    assert result["evidence_records"] >= 10
    assert result["window"][0].startswith("2025-05-01")
    assert len(result["evidence_sha256"]) == 64


def test_lock_detects_tampering_without_changing_real_configs(tmp_path):
    path = tmp_path / "lock.json"
    lock = create_config_lock(path)
    assert validate_config_lock(path)["aggregate_sha256"] == lock["aggregate_sha256"]
    lock["files"][next(iter(lock["files"]))] = "0" * 64
    path.write_text(json.dumps(lock))
    with pytest.raises(RuntimeError, match="lock mismatch"):
        validate_config_lock(path)


def test_case_study_computes_metrics_without_writing_outputs():
    result = run_backtest(write_outputs=False, require_lock=False)
    metrics = result["metrics"]
    assert metrics["detection_lead"]["calendar_days_point"] >= 0
    assert metrics["counterfactual_premium_avoided_musd"] > 0
    assert metrics["shortage_days_avoided"] == 0
    assert metrics["hard_constraint_violations"] == 0
    assert len(result["certificates"]) == 3
