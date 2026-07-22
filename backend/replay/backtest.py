"""Leakage-guarded historical replay and cost-of-delay proof for the 2025 standoff.

This is a single-event historical case study, not a fitted model and not a statistical estimate of
precision. Thresholds/configs must be locked before the run. Every signal read flows through
ReplayDataset, the solver is pinned to the EIA Brent print visible at alert time, and the generated
metrics document keeps counterfactual assumptions next to the numbers they produce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..engines import allocator, cascade, certify, risk
from ..engines.allocator import PRESETS, Scenario
from .loader import CONFIG_ROOT, REPLAY_ROOT, ReplayDataset, _aware

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPLAY_ROOT / "config_lock.json"
RESULT_PATH = REPLAY_ROOT / "backtest_result.json"
METRICS_PATH = REPO_ROOT / "docs" / "metrics.md"


def _config() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "replay_backtest.yaml").read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for rel in _config()["config_lock_files"]:
        path = REPO_ROOT / rel
        if not path.is_file():
            raise FileNotFoundError(f"backtest lock input missing: {rel}")
        manifest[rel] = _sha256(path)
    return manifest


def _aggregate_hash(manifest: dict[str, str]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def create_config_lock(lock_path: Path = LOCK_PATH) -> dict[str, Any]:
    """Freeze the exact authored assumptions used by the historical case study."""
    manifest = _lock_manifest()
    payload = {
        "schema_version": 1,
        "dataset": _config()["dataset"],
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "aggregate_sha256": _aggregate_hash(manifest),
        "files": manifest,
        "note": "thresholds and engine assumptions locked before historical evaluation",
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def validate_config_lock(lock_path: Path = LOCK_PATH) -> dict[str, Any]:
    """Raise if a locked assumption changed after lock creation."""
    if not lock_path.is_file():
        raise RuntimeError("config lock missing; run `make replay-lock` before `make backtest`")
    locked = json.loads(lock_path.read_text())
    current = _lock_manifest()
    expected_hash = _aggregate_hash(current)
    if locked.get("files") != current or locked.get("aggregate_sha256") != expected_hash:
        changed = sorted(set(current) | set(locked.get("files", {})))
        changed = [p for p in changed if current.get(p) != locked.get("files", {}).get(p)]
        raise RuntimeError("backtest config lock mismatch: " + ", ".join(changed))
    return locked


def validate_dataset(dataset: ReplayDataset | None = None) -> dict[str, Any]:
    """Validate source URLs, chronology, coverage, and immutable dataset fingerprints."""
    ds = dataset or ReplayDataset()
    start, end = ds.window()
    evidence = ds._evidence  # validation owns the full immutable source, not an engine read
    if not evidence or not ds._brent:
        raise ValueError("replay requires both sourced evidence and EIA Brent")
    if any(_aware(evidence[i]["timestamp"]) > _aware(evidence[i + 1]["timestamp"])
           for i in range(len(evidence) - 1)):
        raise ValueError("replay evidence is not chronological")
    return {
        "window": [start.isoformat(), end.isoformat()],
        "evidence_records": len(evidence),
        "brent_records": len(ds._brent),
        "evidence_sha256": _sha256(ds.root / "evidence.jsonl"),
        "brent_sha256": _sha256(ds.root / "brent_daily.json"),
        "source_urls_preserved": all(str(row.get("source_url", "")).startswith("http")
                                     for row in evidence),
    }


def _first_alert(ds: ReplayDataset, cfg: dict[str, Any]) -> tuple[datetime, dict[str, Any]]:
    rule = cfg["alert_rule"]
    # Evaluate when new information becomes visible. Price dates and evidence timestamps are the
    # only state transitions; walking arbitrary intermediate times cannot create a new signal.
    ticks = {_aware(row["timestamp"]) for row in ds._brent}
    ticks.update(_aware(row["timestamp"]) for row in ds._evidence)
    for sim_now in sorted(ticks):
        result = risk.compute(cfg["corridor"], ds.risk_raw_at(sim_now, cfg["corridor"]))
        if (result.index >= float(rule["risk_index_threshold"])
                and result.confidence >= float(rule["confidence_min"])):
            return sim_now, result.to_dict()
    raise RuntimeError("alert rule never fired in the replay window")


def _reactive_print(ds: ReplayDataset, cfg: dict[str, Any]) -> tuple[dict[str, Any], float, float]:
    rule = cfg["reactive_baseline"]
    baseline_end = datetime.fromisoformat(str(rule["baseline_end_date"])).date()
    baseline = [float(row["value"]) for row in ds._brent
                if _aware(row["timestamp"]).date() <= baseline_end]
    if not baseline:
        raise RuntimeError("no EIA Brent prints in reactive baseline window")
    statistic = str(rule.get("statistic", "median"))
    if statistic != "median":
        raise ValueError(f"unsupported reactive baseline statistic: {statistic}")
    baseline_value = float(statistics.median(baseline))
    threshold = baseline_value + float(rule["brent_move_usd_bbl"])
    for row in ds._brent:
        if (_aware(row["timestamp"]).date() > baseline_end
                and float(row["value"]) >= threshold):
            return row, baseline_value, threshold
    raise RuntimeError("reactive Brent threshold never crossed in the replay window")


def _lead_time(alert_time: datetime, alert_event: dict[str, Any],
               reactive_row: dict[str, Any]) -> dict[str, Any]:
    # EIA daily data and a day-precision alert cannot support an exact intraday claim. Preserve the
    # normalized timestamps for audit, but headline the calendar-day difference with a precision
    # band that widens one day in either direction.
    reactive_time = _aware(reactive_row["timestamp"])
    days = (reactive_time.date() - alert_time.date()).days
    uncertain = alert_event.get("timestamp_precision") == "day"
    return {
        "calendar_days_point": days,
        "calendar_days_range": [max(0, days - 1), days + 1] if uncertain else [days, days + 1],
        "alert_normalized_at": alert_time.isoformat(),
        "reactive_eia_period": reactive_time.date().isoformat(),
        "precision_note": (
            "alert source is day-precision and Brent is a daily print; exact intraday lead is not claimed"
            if uncertain else "Brent is a daily print; exact intraday lead is not claimed"),
    }


def run_backtest(*, write_outputs: bool = True, require_lock: bool = True) -> dict[str, Any]:
    """Run the locked single-event case study and optionally write JSON + docs/metrics.md."""
    cfg = _config()
    ds = ReplayDataset()
    dataset_meta = validate_dataset(ds)
    lock = validate_config_lock() if require_lock else {
        "aggregate_sha256": _aggregate_hash(_lock_manifest()), "files": _lock_manifest()}

    alert_time, alert_risk = _first_alert(ds, cfg)
    alert_event = ds.latest_evidence(alert_time)
    if not alert_event:
        raise RuntimeError("alert fired without a visible evidence record")
    reactive_row, baseline_brent, reactive_threshold = _reactive_print(ds, cfg)
    alert_brent = ds.brent_at(alert_time)
    if alert_brent is None:
        raise RuntimeError("no leakage-safe EIA Brent print visible at alert time")

    scenario_cfg = cfg["response_scenario"]
    scenario = Scenario(
        corridor_states={cfg["corridor"]: "restricted"},
        restrict_severity=float(scenario_cfg["restrict_severity"]),
        duration_days=float(scenario_cfg["duration_days"]),
        live_risk={cfg["corridor"]: alert_risk["index"]},
        reference_brent_usd_bbl=float(alert_brent),
    )
    started = time.perf_counter()
    plans = {preset: allocator.solve(scenario, preset) for preset in PRESETS}
    recommendation = certify.recommend(
        plans, scenario, n_samples=int(scenario_cfg["monte_carlo_samples"]))
    engine_seconds = time.perf_counter() - started
    recommended_name = recommendation["recommended"]
    recommended_plan = plans[recommended_name]
    recommended_cert = recommendation["certificates"][recommended_name]

    horizon = float(cfg["counterfactual"]["premium_commitment_days"])
    reactive_brent = float(reactive_row["value"])
    price_delta = max(0.0, reactive_brent - float(alert_brent))
    purchase_mb_d = sum(float(p["volume_mb_d"]) for p in recommended_plan.purchases)
    # mb/d × $/bbl = $M/day; multiplying by days therefore yields $M.
    premium_avoided_musd = price_delta * purchase_mb_d * horizon
    unmitigated = cascade.single(
        cfg["corridor"], float(scenario_cfg["restrict_severity"]),
        float(scenario_cfg["duration_days"]))
    shortage_days_avoided = max(0.0, unmitigated.shortage_days)

    result = {
        "schema_version": 1,
        "dataset": cfg["dataset"],
        "run_at": datetime.now(timezone.utc).isoformat(),
        "case_study_scope": "single sourced historical event window; not statistical validation",
        "config_lock_sha256": lock["aggregate_sha256"],
        "dataset_fingerprints": dataset_meta,
        "alert": {
            "event_id": alert_event["id"], "headline": alert_event["headline"],
            "source": alert_event["source"], "source_url": alert_event["source_url"],
            "risk_index": alert_risk["index"], "confidence": alert_risk["confidence"],
            "threshold": cfg["alert_rule"],
        },
        "reactive_baseline": {
            "baseline_end_date": cfg["reactive_baseline"]["baseline_end_date"],
            "baseline_statistic": cfg["reactive_baseline"]["statistic"],
            "baseline_brent_usd_bbl": round(baseline_brent, 3),
            "trigger_brent_usd_bbl": round(reactive_threshold, 3),
            "first_crossing_period": reactive_row["period"],
            "first_crossing_brent_usd_bbl": reactive_brent,
        },
        "metrics": {
            "detection_lead": _lead_time(alert_time, alert_event, reactive_row),
            "alert_brent_usd_bbl": float(alert_brent),
            "reactive_brent_usd_bbl": reactive_brent,
            "price_delta_usd_bbl": round(price_delta, 3),
            "modeled_purchase_volume_mb_d": round(purchase_mb_d, 5),
            "premium_commitment_days": horizon,
            "counterfactual_premium_avoided_musd": round(premium_avoided_musd, 3),
            "shortage_days_avoided": round(shortage_days_avoided, 3),
            "signal_to_certified_plan_seconds": round(engine_seconds, 4),
            "recommended_plan": recommended_name,
            "recommended_robustness_pass_rate": recommended_cert["robustness_pass_rate"],
            "recommended_cost_at_risk_usd_bbl": recommended_cert["cost_at_risk_usd_bbl"],
            "plan_status": recommended_plan.status,
            "hard_constraint_violations": 0 if recommended_plan.status in {"OPTIMAL", "FEASIBLE"} else None,
        },
        "scenario": scenario.to_dict(),
        "plans": {name: plan.to_dict() for name, plan in plans.items()},
        "certificates": recommendation["certificates"],
        "limitations": [
            "One historical case study does not estimate alert precision or false-alert rate.",
            "Evidence is a curated immutable sourced lane, not a claim of GDELT bulk-derived tone.",
            "Premium avoided is a planning counterfactual, not booked savings: EIA price delta × modeled purchase volume × stated commitment horizon.",
            "Shortage-days avoided is zero when modeled national buffers already cover the scenario horizon.",
            "Runtime measures engine signal-to-certified-plan compute only; human approval time is not measured.",
        ],
    }
    if write_outputs:
        RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n")
        METRICS_PATH.write_text(_metrics_markdown(result))
    return result


def _metrics_markdown(result: dict[str, Any]) -> str:
    m = result["metrics"]
    lead = m["detection_lead"]
    return f"""# HEIMDALL — Historical Replay Metrics

Generated by the locked, leakage-guarded `2025-standoff` case study. These are engine outputs,
not presentation placeholders. Config lock: `{result['config_lock_sha256']}`.

## Result

| Metric | Computed result | Meaning |
|---|---:|---|
| Detection lead | **{lead['calendar_days_point']} calendar day** ({lead['calendar_days_range'][0]}–{lead['calendar_days_range'][1]} day precision band) | First sourced Risk Index alert vs first EIA daily Brent print crossing the locked reactive threshold |
| Counterfactual premium avoided | **${m['counterfactual_premium_avoided_musd']:.3f}M** | ${m['price_delta_usd_bbl']:.2f}/bbl historical price delta × {m['modeled_purchase_volume_mb_d']:.3f} mb/d modeled purchases × {m['premium_commitment_days']:.0f} days |
| Shortage days avoided | **{m['shortage_days_avoided']:.3f} days** | Zero is expected here: modeled commercial + SPR buffers cover this 14-day, 50% restriction horizon |
| Signal → certified plan compute | **{m['signal_to_certified_plan_seconds']:.4f}s** | Three OR-Tools plans plus {result['certificates'][m['recommended_plan']]['n_samples']} fixed-plan Monte Carlo futures per plan; excludes human approval time |
| Recommended robustness | **{m['recommended_robustness_pass_rate']:.1%}** | Frequency over sampled futures, not a calibrated probability forecast |
| Hard-constraint violations | **{m['hard_constraint_violations']}** | Solver returned `{m['plan_status']}` for the selected plan |

## Audit trail

- Alert: [{result['alert']['headline']}]({result['alert']['source_url']}) — Risk Index {result['alert']['risk_index']:.2f}, confidence {result['alert']['confidence']:.1%}.
- Alert-time EIA Brent: **${m['alert_brent_usd_bbl']:.2f}/bbl**.
- Reactive threshold: median Brent through {result['reactive_baseline']['baseline_end_date']} plus $10/bbl = **${result['reactive_baseline']['trigger_brent_usd_bbl']:.2f}/bbl**.
- First crossing: **{result['reactive_baseline']['first_crossing_period']} at ${m['reactive_brent_usd_bbl']:.2f}/bbl**.
- Recommended response: **{m['recommended_plan'].replace('_', ' ').title()}**, certified at {m['recommended_robustness_pass_rate']:.1%} across the seeded futures.
- Timing honesty: {lead['precision_note']}.

## What this does not prove

""" + "".join(f"- {item}\n" for item in result["limitations"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", action="store_true", help="create/replace the config lock")
    parser.add_argument("--validate", action="store_true", help="validate the immutable dataset")
    args = parser.parse_args()
    if args.lock:
        lock = create_config_lock()
        print(f"locked {len(lock['files'])} config files: {lock['aggregate_sha256']}")
        return
    if args.validate:
        print(json.dumps(validate_dataset(), indent=2))
        return
    result = run_backtest()
    print(json.dumps(result["metrics"], indent=2))
    print(f"wrote {RESULT_PATH.relative_to(REPO_ROOT)} and {METRICS_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
