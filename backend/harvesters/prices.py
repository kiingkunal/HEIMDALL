"""Price harvester. EIA Open Data is the AUTHORITATIVE source for Brent history (replay + analysis).
yfinance is a LIVE-DISPLAY convenience only (per Technical Truth Constraint #6) and never feeds
the replay or the analytical price series.

On any source failure: serve the last cached value with a visible DATA AGE. Never crash.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from ..lib import storage
from ..lib.provenance import SourceKind, tag

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

EIA_API_KEY = os.getenv("EIA_API_KEY", "")
# EIA v2: Europe Brent Spot Price FOB, daily. series id RBRTE.
EIA_BRENT_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
EIA_BRENT_SERIES = "RBRTE"
SOURCE_LABEL = "EIA Open Data — Europe Brent Spot FOB (RBRTE), daily"
EIA_HELP_URL = "https://www.eia.gov/opendata/"

NAMESPACE = "prices"


def fetch_eia_brent(length: int = 60) -> dict[str, Any]:
    """Fetch recent daily Brent spot from EIA v2. Returns the newest observation as a Tagged dict.

    Stores the full recent window under latest['prices']['brent_history'] and the newest point
    under latest['prices']['brent_spot'] for the UI. On failure, returns cached with kind=cache.
    """
    if not EIA_API_KEY:
        return _cached_or_empty("brent_spot", note="EIA_API_KEY missing")

    params = {
        "api_key": EIA_API_KEY,
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": EIA_BRENT_SERIES,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": length,
    }
    try:
        r = requests.get(EIA_BRENT_URL, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()["response"]["data"]
        if not rows:
            return _cached_or_empty("brent_spot", note="EIA returned no rows")

        # rows sorted desc by period; newest first.
        series = [
            {"period": row["period"], "value": float(row["value"])}
            for row in rows if row.get("value") is not None
        ]
        newest = series[0]
        fetched = datetime.now(timezone.utc)

        hist_tagged = tag(series, SOURCE_LABEL, SourceKind.LIVE,
                          fetched_at=fetched, source_url=EIA_HELP_URL,
                          series=EIA_BRENT_SERIES).to_dict()
        spot_tagged = tag({"price_usd_per_bbl": newest["value"], "as_of": newest["period"]},
                          SOURCE_LABEL, SourceKind.LIVE, fetched_at=fetched,
                          source_url=EIA_HELP_URL).to_dict()

        storage.put_latest(NAMESPACE, "brent_history", hist_tagged, SOURCE_LABEL, "live")
        storage.put_latest(NAMESPACE, "brent_spot", spot_tagged, SOURCE_LABEL, "live")
        storage.log_harvest("prices", SOURCE_LABEL, "live", "ok", record_count=len(series))
        return spot_tagged
    except Exception as exc:
        storage.log_harvest("prices", SOURCE_LABEL, "live", "error", detail=str(exc)[:300])
        return _cached_or_empty("brent_spot", note=f"EIA fetch failed: {type(exc).__name__}")


def fetch_yfinance_display() -> dict[str, Any] | None:
    """LIVE-DISPLAY ONLY. BZ=F (Brent front-month) for the ticker. Never feeds analysis/replay."""
    try:
        import yfinance as yf  # optional dep; display convenience only
    except ImportError:
        return None
    try:
        t = yf.Ticker("BZ=F")
        px = t.fast_info.get("last_price")
        if px is None:
            return None
        tagged = tag({"price_usd_per_bbl": float(px), "ticker": "BZ=F"},
                     "yfinance BZ=F (live display only — not authoritative)",
                     SourceKind.LIVE, note="display convenience; EIA is authoritative").to_dict()
        storage.put_latest(NAMESPACE, "brent_display", tagged,
                           "yfinance BZ=F", "live")
        return tagged
    except Exception:
        return None


def _cached_or_empty(key: str, note: str) -> dict[str, Any]:
    cached = storage.get_latest(NAMESPACE, key)
    if cached:
        payload = cached["payload"]
        # re-tag provenance kind as cache so the UI shows DATA AGE from the original fetch
        if isinstance(payload, dict) and "provenance" in payload:
            payload["provenance"]["kind"] = SourceKind.CACHE.value
            payload["provenance"]["note"] = note
        return payload
    return tag(None, SOURCE_LABEL, SourceKind.CACHE, note=f"no cache available — {note}").to_dict()


def run() -> dict[str, Any]:
    """Scheduler entry point."""
    spot = fetch_eia_brent()
    fetch_yfinance_display()
    return spot


if __name__ == "__main__":
    storage.init_db()
    print(run())
