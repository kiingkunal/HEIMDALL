"""Cross-source corridor convergence gate inspired by OSINT corroboration tradecraft."""
from __future__ import annotations

from typing import Any

from ..lib.provenance import SourceKind, tag
from . import maritime, risk


def classify_origins(components: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Group normalized components into independent origins and classify corroboration."""
    values = {c["component"]: c.get("normalized") for c in components}

    def max_present(*items: str) -> float | None:
        present = [values[name] for name in items if values.get(name) is not None]
        return max(present) if present else None

    origins = {
        "news": max_present("news_volume", "tone"),  # one provider origin; never double-count
        "market": values.get("price_vol"),
        "ais": values.get("anomaly"),
        "sanctions": values.get("sanctions"),
    }
    threshold = float(config["active_origin_threshold"])
    active = [name for name, value in origins.items() if value is not None and value >= threshold]
    available = [name for name, value in origins.items() if value is not None]
    if len(active) >= int(config["confirmed_min_origins"]):
        status = "confirmed_convergence"
    elif len(active) >= int(config["watch_min_origins"]):
        status = "watch"
    else:
        status = "observing"
    return {
        "status": status,
        "active_origin_count": len(active),
        "available_origin_count": len(available),
        "active_origins": active,
        "origins": {name: None if value is None else round(float(value), 4)
                    for name, value in origins.items()},
        "rule": f"confirmed only at {config['confirmed_min_origins']}+ independent origins",
        "note": "corroboration class, NOT a disruption probability",
    }


def corridor_intelligence(corridor_id: str) -> dict[str, Any]:
    """Assemble risk, AIS pulse and independent-origin convergence for one corridor."""
    raw = risk.gather_raw(corridor_id)
    risk_result = risk.compute(corridor_id, raw)
    pulse = maritime.corridor_pulse(corridor_id)
    convergence = classify_origins(risk_result.components, risk._cfg()["convergence"])
    value = {
        "corridor": corridor_id,
        "risk_index": risk_result.index,
        "confidence": risk_result.confidence,
        "convergence": convergence,
        "pulse": pulse["value"],
        "pulse_provenance": pulse["provenance"],
    }
    return tag(value, "HEIMDALL cross-source intelligence engine", SourceKind.ENGINE,
               note="independent-origin convergence + explainable AIS pulse").to_dict()


def intelligence_all() -> dict[str, Any]:
    corridors = {
        corridor_id: corridor_intelligence(corridor_id)
        for corridor_id, meta in risk._corridors().items()
        if not meta.get("reroute_reference")
    }
    confirmed = sum(
        1 for item in corridors.values()
        if item["value"]["convergence"]["status"] == "confirmed_convergence"
    )
    watches = sum(
        1 for item in corridors.values()
        if item["value"]["convergence"]["status"] == "watch"
    )
    return {"corridors": corridors, "confirmed_count": confirmed, "watch_count": watches}
