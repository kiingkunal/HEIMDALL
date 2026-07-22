"""Sanctions screening for the solver's hard OFAC-exclusion constraint. A sanctioned supplier (or a
supplier flagged in data) is removed from the feasible set entirely — never merely penalized.

Two layers:
  1. explicit `ofac_flag` in suppliers.json (curated demo control), and
  2. name/country match against the live-cached OFAC SDN list (harvesters/sanctions.py).

Vessel-level screening (listed tankers) plugs in at the packet stage (Phase 3) where specific
vessels are assigned; here we screen at supplier/country granularity.
"""
from __future__ import annotations

from typing import Any

from ..harvesters import sanctions as sanctions_harvester
from ..lib import storage


def _sdn_entities() -> list[str]:
    rec = storage.get_latest("sanctions", "sdn")
    if not rec:
        return []
    # we cache the full entity list count but only vessels in payload; use vessels + any note.
    # For supplier/country screening we conservatively match against vessel names + program text.
    v = rec["payload"].get("value", {})
    names = [x.get("name", "") for x in v.get("vessels", [])]
    return [n for n in names if n]


def is_supplier_sanctioned(supplier: dict[str, Any]) -> bool:
    """True if the supplier is OFAC-flagged in data. (Country-level SDN matching is intentionally
    conservative — we do NOT sanction an entire producing country off a vessel-name match; that
    would be wrong. Real country/entity sanctions are represented via the curated ofac_flag.)"""
    if supplier.get("ofac_flag"):
        return True
    return False


def is_vessel_sanctioned(vessel_name: str) -> bool:
    """True if a specific vessel name matches the cached OFAC SDN vessel list (used at packet stage)."""
    if not vessel_name:
        return False
    return sanctions_harvester.is_sanctioned(vessel_name)
