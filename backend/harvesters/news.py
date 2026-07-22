"""News signal harvester. gdeltdoc = live GDELT DOC API (timelinevol + timelinetone), LIVE
MONITORING LANE ONLY. The DOC API covers only ~the most recent 3 months (Truth Constraint #4),
so it MUST NOT be used to build the 2025 replay — that comes from GDELT 2.0 bulk archives.

Per-corridor keyword clusters produce a volume timeline and a tone timeline. The Risk Index engine
consumes the latest z-scored volume + tone negativity. The LLM later writes narrative around these
numbers; it never invents the numbers.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from ..lib import storage
from ..lib.provenance import SourceKind, tag

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
NAMESPACE = "news"
SOURCE_LABEL = "GDELT DOC API (gdeltdoc) — live monitoring lane"
SOURCE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Per-corridor query spec. GDELT DOC (via gdeltdoc) builds the query from a keyword phrase + a
# near() co-occurrence clause; it has no raw-query param. keyword = the corridor phrase (quoted
# multiword automatically), near_terms = context words that must appear within `near_window` words.
CORRIDOR_QUERIES: dict[str, dict[str, Any]] = {
    "hormuz":       {"keyword": "Strait of Hormuz", "near_terms": ["oil", "tanker"], "near_window": 20},
    "bab_el_mandeb":{"keyword": "Red Sea",          "near_terms": ["tanker", "attack"], "near_window": 20},
    "suez":         {"keyword": "Suez Canal",       "near_terms": ["tanker", "shipping"], "near_window": 20},
    "malacca":      {"keyword": "Strait of Malacca","near_terms": ["tanker", "shipping"], "near_window": 20},
}

# GDELT DOC API rate-limits aggressively (roughly 1 req / 5s, with burst penalties). Space calls
# generously; hourly scheduler cadence means these delays are invisible in production.
_CALL_SPACING_S = 8.0
_MAX_RETRIES = 4
_BACKOFF_S = 8.0


def _load_corridor_ids() -> list[str]:
    data = yaml.safe_load((CONFIG_ROOT / "corridors.yaml").read_text())
    return [cid for cid in data["corridors"] if cid in CORRIDOR_QUERIES]


def fetch_corridor(corridor_id: str, months: int = 2) -> dict[str, Any]:
    """Fetch volume + tone timelines for one corridor. Returns latest values as a Tagged dict.

    Stores the full timelines and a compact 'latest' summary for the Risk Index engine.
    """
    spec = CORRIDOR_QUERIES[corridor_id]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30 * months)
    try:
        from gdeltdoc import GdeltDoc, Filters, near

        f = Filters(
            keyword=spec["keyword"],
            near=near(spec["near_window"], *spec["near_terms"]),
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        gd = GdeltDoc()
        vol = _timeline_with_retry(gd, "timelinevol", f)
        time.sleep(_CALL_SPACING_S)
        tone = _timeline_with_retry(gd, "timelinetone", f)

        vol_series = _series_from_df(vol)
        tone_series = _series_from_df(tone)
        latest = {
            "corridor": corridor_id,
            "latest_volume": vol_series[-1]["value"] if vol_series else None,
            "latest_tone": tone_series[-1]["value"] if tone_series else None,
            "volume_series": vol_series[-60:],   # cap payload
            "tone_series": tone_series[-60:],
            "query": f"{spec['keyword']} NEAR{spec['near_window']}:{spec['near_terms']}",
        }
        tagged = tag(latest, SOURCE_LABEL, SourceKind.LIVE, source_url=SOURCE_URL,
                     coverage_note="DOC API ~3-month window; NOT for replay").to_dict()
        storage.put_latest(NAMESPACE, corridor_id, tagged, SOURCE_LABEL, "live")
        storage.log_harvest("news", f"{SOURCE_LABEL}:{corridor_id}", "live", "ok",
                            record_count=len(vol_series))
        return tagged
    except Exception as exc:
        storage.log_harvest("news", f"{SOURCE_LABEL}:{corridor_id}", "live", "error",
                            detail=str(exc)[:300])
        return _cached_or_empty(corridor_id, note=f"GDELT fetch failed: {type(exc).__name__}")


def _timeline_with_retry(gd, mode: str, filters):
    """GDELT timeline call with backoff on the library's RateLimitError."""
    from gdeltdoc.errors import RateLimitError
    last: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return gd.timeline_search(mode, filters)
        except RateLimitError as exc:
            last = exc
            time.sleep(_BACKOFF_S * (attempt + 1))
    raise last if last else RuntimeError("timeline retry exhausted")


def _series_from_df(df) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    # gdeltdoc returns a DataFrame with a datetime col + a value col (name varies by endpoint).
    cols = list(df.columns)
    date_col = cols[0]
    value_col = cols[1] if len(cols) > 1 else cols[0]
    out = []
    for _, row in df.iterrows():
        try:
            d = row[date_col]
            d = d.isoformat() if hasattr(d, "isoformat") else str(d)
            out.append({"date": d, "value": float(row[value_col])})
        except (ValueError, TypeError):
            continue
    return out


def _cached_or_empty(corridor_id: str, note: str) -> dict[str, Any]:
    cached = storage.get_latest(NAMESPACE, corridor_id)
    if cached:
        payload = cached["payload"]
        if isinstance(payload, dict) and "provenance" in payload:
            payload["provenance"]["kind"] = SourceKind.CACHE.value
            payload["provenance"]["note"] = note
        return payload
    return tag({"corridor": corridor_id, "latest_volume": None, "latest_tone": None},
               SOURCE_LABEL, SourceKind.CACHE, note=f"no cache — {note}").to_dict()


def run() -> dict[str, Any]:
    """Scheduler entry point — sweep all corridors."""
    out = {}
    for i, cid in enumerate(_load_corridor_ids()):
        if i:
            time.sleep(_CALL_SPACING_S)   # space corridors to respect GDELT limiter
        out[cid] = fetch_corridor(cid)
    return out


if __name__ == "__main__":
    storage.init_db()
    res = run()
    for cid, t in res.items():
        v = t.get("value", {})
        print(f"{cid}: vol={v.get('latest_volume')} tone={v.get('latest_tone')} "
              f"[{t['provenance']['kind']}]")
