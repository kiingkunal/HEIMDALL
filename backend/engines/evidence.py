"""Evidence bundle builder (L2). Assembles the full, defensible evidence package behind every
corridor alert: the Risk Index + its component breakdown, affected suppliers/refineries, per-signal
freshness, contradictory evidence, the expected operational consequence (a cascade preview), source
links, and an OPTIONAL LLM narrative.

Doctrine split: engines produce every number; the LLM only writes prose AROUND them and is
schema-validated. If the LLM is unavailable, the bundle still returns (narrative=None) — never crash.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import json as _json

from ..lib import llm, storage
from ..lib.provenance import SourceKind, tag
from . import risk
from .cascade import CorridorShock, run_cascade

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"


@lru_cache(maxsize=1)
def _suppliers() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "suppliers.json").read_text())["suppliers"]


@lru_cache(maxsize=1)
def _grades() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "grades.json").read_text())


@lru_cache(maxsize=1)
def _refineries() -> list[dict[str, Any]]:
    return json.loads((DATA_ROOT / "refineries.json").read_text())["refineries"]


@lru_cache(maxsize=1)
def _import_mix() -> dict[str, Any]:
    return json.loads((DATA_ROOT / "import_mix.json").read_text())


def _affected_suppliers(corridor_id: str) -> list[dict[str, Any]]:
    mix = {m["supplier_id"]: m for m in _import_mix()["shares_pct"]}
    out = []
    for s in _suppliers():
        if s["corridor"] == corridor_id:
            share = mix.get(s["id"], {}).get("share_pct")
            out.append({"supplier_id": s["id"], "country": s["country"],
                        "grade_id": s["grade_id"], "share_pct": share})
    return sorted(out, key=lambda x: -(x["share_pct"] or 0))


def _affected_refineries(corridor_id: str) -> list[dict[str, Any]]:
    """Refineries fed by the disrupted crude: affected suppliers -> grade classes -> refineries
    that accept those classes. This is why the disruption bites these specific plants."""
    gmap = _grades()["grade_class_map"]
    affected_classes = {gmap[s["grade_id"]] for s in _suppliers()
                        if s["corridor"] == corridor_id and s["grade_id"] in gmap}
    out = []
    for r in _refineries():
        overlap = affected_classes & set(r["accepts_classes"])
        if overlap:
            out.append({"id": r["id"], "name": r["name"], "coast": r["coast"],
                        "capacity_mb_d": r["capacity_mb_d"],
                        "exposed_grade_classes": sorted(overlap)})
    return sorted(out, key=lambda x: -x["capacity_mb_d"])


def _freshness_map(corridor_id: str) -> dict[str, Any]:
    """Per-signal age + freshness pulled from stored harvest provenance."""
    out: dict[str, Any] = {}
    def _grab(ns: str, key: str, label: str):
        rec = storage.get_latest(ns, key)
        if rec:
            prov = rec["payload"].get("provenance", {})
            out[label] = {"age_hours": prov.get("age_hours"), "freshness": prov.get("freshness"),
                          "fetched_at": prov.get("fetched_at"), "source": prov.get("source"),
                          "kind": prov.get("kind")}
    _grab("news", corridor_id, "news")
    _grab("prices", "brent_spot", "price")
    _grab("anomalies", "latest", "anomaly")
    _grab("sanctions", "sdn", "sanctions")
    return out


def _evidence_links(corridor_id: str) -> list[dict[str, Any]]:
    links = []
    news = storage.get_latest("news", corridor_id)
    if news:
        prov = news["payload"].get("provenance", {})
        links.append({"signal": "news", "source": prov.get("source"),
                      "url": prov.get("source_url"), "kind": prov.get("kind")})
    prices = storage.get_latest("prices", "brent_spot")
    if prices:
        prov = prices["payload"].get("provenance", {})
        links.append({"signal": "price", "source": prov.get("source"),
                      "url": prov.get("source_url"), "kind": prov.get("kind")})
    sanc = storage.get_latest("sanctions", "sdn")
    if sanc:
        prov = sanc["payload"].get("provenance", {})
        links.append({"signal": "sanctions", "source": prov.get("source"),
                      "url": prov.get("source_url"), "kind": prov.get("kind")})
    return links


def _narrative(bundle_numbers: dict[str, Any]) -> dict[str, Any] | None:
    """LLM prose around the numbers. Schema-validated + cached. Returns None on any failure."""
    try:
        prompt = llm.load_prompt("evidence_narrative").replace(
            "{bundle_json}", _json.dumps(bundle_numbers, ensure_ascii=False))
        data = llm.complete_json(
            [{"role": "user", "content": prompt}],
            schema_keys=["headline", "summary", "recommended_watch"],
            temperature=0.2, max_tokens=400, prompt_name="evidence_narrative")
        return {k: data[k] for k in ("headline", "summary", "recommended_watch")}
    except Exception as exc:
        return None


def build_bundle(corridor_id: str, with_narrative: bool = True) -> dict[str, Any]:
    """Full evidence bundle for one corridor. Numbers from engines; prose optional + validated."""
    risk_result = risk.compute(corridor_id, risk.gather_raw(corridor_id))
    corr_meta = risk._corridors().get(corridor_id, {})

    # expected operational consequence: a cascade preview scaled to CURRENT risk (index/100),
    # 14-day window — links the alert to a concrete, engine-computed consequence.
    preview_severity = round(risk_result.index / 100.0, 3)
    preview = run_cascade([CorridorShock(corridor_id, max(0.05, preview_severity), 14)])
    expected_consequence = {
        "assumption": f"proportional {int(preview_severity*100)}% disruption for 14 days "
                      f"(scaled to current Risk Index)",
        "deficit_mb_d": preview.deficit_mb_d,
        "deficit_pct": preview.deficit_pct,
        "inventory_days_remaining": preview.inventory_days_remaining,
        "landed_cost_pressure_usd_bbl": preview.landed_cost_pressure_usd_bbl,
        "retail_pressure_usd_bbl": preview.retail_pressure_usd_bbl,
        "refinery_impacts": preview.refinery_impacts,
    }

    numbers = {
        "corridor": corridor_id,
        "corridor_name": corr_meta.get("name", corridor_id),
        "risk_index": risk_result.index,
        "confidence": risk_result.confidence,
        "components": risk_result.components,
        "present_signals": risk_result.present_signals,
        "missing_signals": risk_result.missing_signals,
        "contradictions": risk_result.contradictions,
        "corridor_share_pct": corr_meta.get("india_crude_share_pct"),
        "affected_suppliers": _affected_suppliers(corridor_id),
        "affected_refineries": _affected_refineries(corridor_id),
        "expected_consequence": expected_consequence,
    }

    bundle = dict(numbers)
    bundle["confidence_breakdown"] = risk_result.confidence_breakdown
    bundle["freshness"] = _freshness_map(corridor_id)
    bundle["evidence_links"] = _evidence_links(corridor_id)
    bundle["narrative"] = _narrative(numbers) if with_narrative else None
    bundle["index_note"] = ("Corridor Risk Index 0-100 is a weighted evidence fusion, "
                            "NOT a probability. Confidence is a separate score.")

    return tag(bundle, "HEIMDALL evidence engine", SourceKind.ENGINE,
               note="numbers from engines; narrative is schema-validated LLM prose").to_dict()


def bundles_all(with_narrative: bool = False) -> dict[str, Any]:
    out = {}
    for cid, meta in risk._corridors().items():
        if meta.get("reroute_reference"):
            continue
        out[cid] = build_bundle(cid, with_narrative=with_narrative)
    return out


if __name__ == "__main__":
    storage.init_db()
    b = build_bundle("hormuz", with_narrative=True)["value"]
    print("Hormuz bundle:")
    print("  index:", b["risk_index"], "conf:", b["confidence"])
    print("  affected suppliers:", [s["supplier_id"] for s in b["affected_suppliers"]])
    print("  affected refineries:", [r["id"] for r in b["affected_refineries"]])
    print("  expected consequence deficit_mb_d:", b["expected_consequence"]["deficit_mb_d"])
    print("  narrative:", b["narrative"])
