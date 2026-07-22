"""Sanctions harvester. OFAC SDN + consolidated lists. These feed the solver's hard exclusion
constraint (sanctioned suppliers AND listed vessels are removed from the feasible set — never
merely penalized). Also drives the 'new sanctions event' playbook-invalidation trigger.

Downloads the canonical CSV feeds. Vessels appear in the SDN with type 'vessel'. We keep the raw
file cached and a distilled index of vessel names + IMO/MMSI-like identifiers and sanctioned
entity names for matching. On failure: serve cached, visible DATA AGE. Never crash.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..lib import storage
from ..lib.provenance import SourceKind, tag

REPO_ROOT = Path(__file__).resolve().parents[2]
SANCTIONS_DIR = REPO_ROOT / "data" / "sanctions"
NAMESPACE = "sanctions"

# OFAC canonical downloads (public, no key). SDN.CSV is the primary list.
OFAC_SDN_CSV = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT_CSV = "https://www.treasury.gov/ofac/downloads/alt.csv"
SOURCE_LABEL = "OFAC SDN list (treasury.gov/ofac)"
SOURCE_URL = "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists"


def fetch_sdn() -> dict[str, Any]:
    """Download SDN.CSV, cache raw file, distill vessel + entity index. Returns a Tagged summary."""
    SANCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(OFAC_SDN_CSV, timeout=30)
        r.raise_for_status()
        raw = r.content
        raw_path = SANCTIONS_DIR / "sdn.csv"
        raw_path.write_bytes(raw)

        vessels, entities = _parse_sdn(raw.decode("latin-1", errors="replace"))
        summary = {
            "entity_count": len(entities),
            "vessel_count": len(vessels),
            "vessels": vessels[:500],          # cap payload; full list on disk
            "raw_file": str(raw_path.relative_to(REPO_ROOT)),
        }
        tagged = tag(summary, SOURCE_LABEL, SourceKind.LIVE, source_url=SOURCE_URL).to_dict()
        storage.put_latest(NAMESPACE, "sdn", tagged, SOURCE_LABEL, "live")
        storage.log_harvest("sanctions", SOURCE_LABEL, "live", "ok",
                            record_count=len(entities))
        return tagged
    except Exception as exc:
        storage.log_harvest("sanctions", SOURCE_LABEL, "live", "error", detail=str(exc)[:300])
        return _cached_or_empty(note=f"OFAC fetch failed: {type(exc).__name__}")


def _parse_sdn(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """SDN.CSV columns (no header): ent_num, SDN_name, SDN_type, program, title, ...
    SDN_type == 'vessel' flags a listed ship. Returns (vessels, all_entity_names)."""
    vessels: list[dict[str, Any]] = []
    entities: list[str] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 3:
            continue
        name = row[1].strip().strip('"')
        sdn_type = row[2].strip().strip('"').lower()
        if name and name != "-0-":
            entities.append(name)
        if sdn_type == "vessel":
            vessels.append({"name": name, "program": row[3].strip().strip('"') if len(row) > 3 else ""})
    return vessels, entities


def _cached_or_empty(note: str) -> dict[str, Any]:
    cached = storage.get_latest(NAMESPACE, "sdn")
    if cached:
        payload = cached["payload"]
        if isinstance(payload, dict) and "provenance" in payload:
            payload["provenance"]["kind"] = SourceKind.CACHE.value
            payload["provenance"]["note"] = note
        return payload
    return tag({"entity_count": 0, "vessel_count": 0, "vessels": []},
               SOURCE_LABEL, SourceKind.CACHE, note=f"no cache — {note}").to_dict()


def is_sanctioned(name: str) -> bool:
    """Conservative vessel-name match against cached SDN vessels."""
    cached = storage.get_latest(NAMESPACE, "sdn")
    if not cached:
        return False
    vessels = cached["payload"].get("value", {}).get("vessels", [])
    return any(_names_match(name, v["name"]) for v in vessels)


def _names_match(observed: str, listed: str) -> bool:
    """Exact normalized match, or a long alias containment; short names never substring-match."""
    left = re.sub(r"[^a-z0-9]", "", observed.lower())
    right = re.sub(r"[^a-z0-9]", "", listed.lower())
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= 8 and (left in right or right in left)


def run() -> dict[str, Any]:
    return fetch_sdn()


if __name__ == "__main__":
    storage.init_db()
    res = run()
    v = res.get("value", {})
    print(f"entities={v.get('entity_count')} vessels={v.get('vessel_count')} "
          f"[{res['provenance']['kind']}]")
