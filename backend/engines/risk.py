"""Corridor Risk Index engine (L2).

TRUTH CONSTRAINT #3 (non-negotiable): the output is a **Corridor Risk Index (0-100)**, a weighted
evidence fusion — NOT a probability, NOT statistically calibrated. Confidence is a SEPARATE score;
it is never folded into the index. The word "probability" is reserved for the Monte Carlo layer.

  index = 100 * clamp( Σ w_i * norm_i , 0, 1 )   over {news_volume, tone, price_vol, anomaly,
                                                        static, sanctions}
  confidence = Σ cw_j * c_j   over {independent_signal_count, inter_signal_agreement,
                                    freshness, completeness}

Each component is normalized to 0-1 with parameters from config/risk_weights.yaml. The LLM never
touches these numbers; it only writes narrative around them (see engines/evidence.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPO_ROOT / "config"

COMPONENTS = ("news_volume", "tone", "price_vol", "anomaly", "static", "sanctions")
SIGNAL_KEYS = ("news_volume", "tone", "price_vol", "anomaly", "sanctions")  # 'static' always present


@lru_cache(maxsize=1)
def _cfg() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "risk_weights.yaml").read_text())


@lru_cache(maxsize=1)
def _corridors() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())["corridors"]


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ----------------------------- component normalizers (pure) -----------------------------
def norm_news_volume(latest: float | None, series: list[float] | None) -> float | None:
    """z-score latest vs series, keep positive spikes only, clamp to cap, map to 0-1."""
    if latest is None or not series or len(series) < 3:
        return None
    mu = sum(series) / len(series)
    var = sum((x - mu) ** 2 for x in series) / len(series)
    sd = math.sqrt(var)
    if sd < 1e-12:
        return 0.0
    z = (latest - mu) / sd
    cap = _cfg()["normalization"]["news_volume_z_cap"]
    return _clamp(z, 0.0, cap) / cap


def norm_tone(tone: float | None) -> float | None:
    """More negative tone -> higher risk. Linear between tone_floor (1.0) and tone_ceil (0.0)."""
    if tone is None:
        return None
    n = _cfg()["normalization"]
    floor, ceil = n["tone_floor"], n["tone_ceil"]
    return _clamp((ceil - tone) / (ceil - floor))


def norm_price_vol(annualized_vol: float | None) -> float | None:
    if annualized_vol is None:
        return None
    cap = _cfg()["normalization"]["price_vol_annualized_cap"]
    return _clamp(annualized_vol / cap)


def norm_anomaly(count: int | None) -> float | None:
    if count is None:
        return None
    sat = _cfg()["normalization"]["anomaly_saturation_count"]
    return _clamp(count / sat)


def norm_static(corridor_id: str) -> float:
    meta = _corridors().get(corridor_id, {})
    share = meta.get("india_crude_share_pct", 0.0) / 100.0
    weight = meta.get("strategic_weight", 0.0)
    return _clamp(share * weight)


def norm_sanctions(count: int | None) -> float | None:
    if count is None:
        return None
    return _clamp(count / 2.0)   # >=2 new corridor-linked sanctions events saturates


def annualized_vol_from_series(prices: list[float]) -> float | None:
    """Realized annualized volatility from a daily price series (log returns, *sqrt(252))."""
    if not prices or len(prices) < 5:
        return None
    rets = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]
    if len(rets) < 4:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


# ----------------------------- fusion + confidence (pure) -----------------------------
@dataclass
class RiskResult:
    corridor: str
    index: float                     # 0-100
    confidence: float                # 0-1 (SEPARATE from index)
    components: list[dict[str, Any]]
    present_signals: list[str]
    missing_signals: list[str]
    confidence_breakdown: dict[str, float]
    contradictions: list[str]
    note: str = "Corridor Risk Index 0-100 — weighted evidence fusion, NOT a probability"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def fuse(normalized: dict[str, float | None]) -> tuple[float, list[dict[str, Any]]]:
    """Weighted fusion of normalized components -> (index 0-100, breakdown). Missing -> 0 contribution."""
    weights = _cfg()["weights"]
    total = 0.0
    breakdown = []
    for comp in COMPONENTS:
        w = weights[comp]
        val = normalized.get(comp)
        contrib = (val or 0.0) * w
        total += contrib
        breakdown.append({
            "component": comp, "weight": w,
            "normalized": None if val is None else round(val, 4),
            "contribution": round(contrib, 4),
            "present": val is not None,
        })
    index = 100.0 * _clamp(total)
    return round(index, 2), breakdown


def confidence(normalized: dict[str, float | None], freshness: float) -> tuple[float, dict[str, float]]:
    """Confidence 0-1 from signal count, inter-signal agreement, freshness, completeness."""
    cw = _cfg()["confidence"]["weights"]
    present = [normalized.get(k) for k in SIGNAL_KEYS if normalized.get(k) is not None]
    n_present = len(present)
    count_score = n_present / len(SIGNAL_KEYS)

    # agreement: 1 - spread of present normalized values (all agreeing -> high). static excluded.
    if n_present >= 2:
        mu = sum(present) / n_present
        spread = sum(abs(x - mu) for x in present) / n_present   # mean absolute deviation, 0..~0.5
        agreement = _clamp(1.0 - 2.0 * spread)
    elif n_present == 1:
        agreement = 0.5
    else:
        agreement = 0.0

    completeness = count_score  # fraction of expected signal inputs actually present
    fresh = _clamp(freshness)

    score = (cw["independent_signal_count"] * count_score
             + cw["inter_signal_agreement"] * agreement
             + cw["freshness"] * fresh
             + cw["completeness"] * completeness)
    breakdown = {
        "independent_signal_count": round(count_score, 4),
        "inter_signal_agreement": round(agreement, 4),
        "freshness": round(fresh, 4),
        "completeness": round(completeness, 4),
    }
    return round(_clamp(score), 4), breakdown


def freshness_from_age_hours(age_hours: float | None) -> float:
    """Map data age to a 0-1 freshness per config horizon (<=full ->1, >=zero ->0)."""
    if age_hours is None:
        return 0.0
    c = _cfg()["confidence"]
    full, zero = c["freshness_full_hours"], c["freshness_zero_hours"]
    if age_hours <= full:
        return 1.0
    if age_hours >= zero:
        return 0.0
    return _clamp((zero - age_hours) / (zero - full))


def compute(corridor_id: str, raw: dict[str, Any]) -> RiskResult:
    """Compute the Risk Index for a corridor from raw signal values (pure given `raw`).

    raw shape (any key may be absent -> that signal is 'missing', lowers confidence):
      news_volume: {latest: float, series: [float]}
      tone:        {latest: float}
      price_vol:   {annualized: float}  OR  {series: [float]}
      anomaly:     {count: int}
      sanctions:   {count: int}
      _age_hours:  float   # newest data age across signals, for freshness
    """
    nv = raw.get("news_volume") or {}
    normalized: dict[str, float | None] = {
        "news_volume": norm_news_volume(nv.get("latest"), nv.get("series")),
        "tone": norm_tone((raw.get("tone") or {}).get("latest")),
        "price_vol": _price_vol_norm(raw.get("price_vol")),
        "anomaly": norm_anomaly((raw.get("anomaly") or {}).get("count")),
        "static": norm_static(corridor_id),
        "sanctions": norm_sanctions((raw.get("sanctions") or {}).get("count")),
    }
    index, breakdown = fuse(normalized)
    fresh = freshness_from_age_hours(raw.get("_age_hours"))
    conf, conf_bd = confidence(normalized, fresh)

    present = [c for c in SIGNAL_KEYS if normalized.get(c) is not None]
    missing = [c for c in SIGNAL_KEYS if normalized.get(c) is None]

    # contradictions: a signal pointing low-risk while the index is elevated (or vice-versa)
    contradictions = []
    live_vals = {c: normalized[c] for c in SIGNAL_KEYS if normalized.get(c) is not None}
    if live_vals:
        hi = [c for c, v in live_vals.items() if v >= 0.6]
        lo = [c for c, v in live_vals.items() if v <= 0.2]
        if hi and lo:
            contradictions.append(
                f"mixed evidence: {', '.join(hi)} elevated but {', '.join(lo)} calm")

    return RiskResult(
        corridor=corridor_id, index=index, confidence=conf, components=breakdown,
        present_signals=present, missing_signals=missing,
        confidence_breakdown=conf_bd, contradictions=contradictions,
    )


def _price_vol_norm(pv: dict[str, Any] | None) -> float | None:
    if not pv:
        return None
    if pv.get("annualized") is not None:
        return norm_price_vol(pv["annualized"])
    if pv.get("series"):
        return norm_price_vol(annualized_vol_from_series(pv["series"]))
    return None


# ----------------------------- storage-backed wrapper -----------------------------
def _age_hours(payload: dict[str, Any]) -> float | None:
    prov = (payload or {}).get("provenance", {})
    return prov.get("age_hours")


def gather_raw(corridor_id: str) -> dict[str, Any]:
    """Assemble raw signals for a corridor from the latest stored harvests. Missing -> absent."""
    raw: dict[str, Any] = {}
    ages: list[float] = []

    news = storage.get_latest("news", corridor_id)
    if news:
        v = news["payload"].get("value", {})
        series = [p["value"] for p in v.get("volume_series", []) if p.get("value") is not None]
        if v.get("latest_volume") is not None:
            raw["news_volume"] = {"latest": v["latest_volume"], "series": series}
        if v.get("latest_tone") is not None:
            raw["tone"] = {"latest": v["latest_tone"]}
        a = _age_hours(news["payload"])
        if a is not None:
            ages.append(a)

    prices = storage.get_latest("prices", "brent_history")
    if prices:
        series = [p["value"] for p in prices["payload"].get("value", []) if p.get("value") is not None]
        if series:
            raw["price_vol"] = {"series": series[:60]}
        a = _age_hours(prices["payload"])
        if a is not None:
            ages.append(a)

    anom = storage.get_latest("anomalies", "latest")
    if anom:
        counts = anom["payload"].get("value", {}).get("anomalies", [])
        cnt = sum(1 for a in counts if a.get("corridor") == corridor_id)
        raw["anomaly"] = {"count": cnt}
        a = _age_hours(anom["payload"])
        if a is not None:
            ages.append(a)

    # Corridor-linked sanctions evidence comes only from named vessels actually observed in the
    # corridor snapshot. A global OFAC list count would incorrectly raise every corridor equally.
    try:
        from . import maritime
        pulse = maritime.corridor_pulse(corridor_id)["value"]
        if pulse.get("snapshot"):
            raw["sanctions"] = {"count": int(pulse.get("sanctions_hits") or 0)}
        if pulse.get("snapshot") and pulse.get("data_age_hours") is not None:
            ages.append(float(pulse["data_age_hours"]))
    except Exception:
        # Missing/invalid AIS cannot invent a sanctions signal; it remains absent and confidence falls.
        pass

    if ages:
        raw["_age_hours"] = min(ages)
    return raw


def risk_for_corridor(corridor_id: str) -> dict[str, Any]:
    """Storage-backed Risk Index for one corridor, provenance-tagged for the API."""
    raw = gather_raw(corridor_id)
    result = compute(corridor_id, raw)
    return tag(result.to_dict(), "HEIMDALL risk index engine", SourceKind.ENGINE,
               note="index 0-100 is evidence fusion, NOT probability; confidence separate").to_dict()


def risk_all() -> dict[str, Any]:
    out = {}
    for cid, meta in _corridors().items():
        if meta.get("reroute_reference"):
            continue
        out[cid] = risk_for_corridor(cid)
    return out


if __name__ == "__main__":
    storage.init_db()
    for cid, t in risk_all().items():
        v = t["value"]
        print(f"{cid}: index={v['index']} confidence={v['confidence']} "
              f"present={v['present_signals']}")
