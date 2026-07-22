"""HEIMDALL backend. FastAPI + APScheduler. Live monitoring lane + Phase 1 engine endpoints
(/api/risk, /api/cascade, /api/evidence, /api/montecarlo).

The scheduler runs the live monitoring lane. Every response carries provenance so the UI can show
DATA AGE and degrade to cache instead of ever showing stale data silently.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .engines import allocator as allocator_engine
from .engines import cascade as cascade_engine
from .engines import certify as certify_engine
from .engines import evidence as evidence_engine
from .engines import greedy as greedy_engine
from .engines import intelligence as intelligence_engine
from .engines import montecarlo as mc_engine
from .engines import packet as packet_engine
from .engines import playbooks as playbook_engine
from .engines import resilience as resilience_engine
from .engines import risk as risk_engine
from .engines import routes as routes_engine
from .engines.allocator import Scenario
from .harvesters import ais, anomalies, news, prices, sanctions, sim
from .lib import ais_keypool, llm, storage

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

scheduler: BackgroundScheduler | None = None

# Harvester cadences. Short in development; production cadences are noted inline.
PRICES_INTERVAL_MIN = int(os.getenv("PRICES_INTERVAL_MIN", "60"))     # hourly display refresh
NEWS_INTERVAL_MIN = int(os.getenv("NEWS_INTERVAL_MIN", "60"))         # hourly monitoring lane
SANCTIONS_INTERVAL_MIN = int(os.getenv("SANCTIONS_INTERVAL_MIN", "1440"))  # daily
ANOMALIES_INTERVAL_MIN = int(os.getenv("ANOMALIES_INTERVAL_MIN", "10"))    # on snapshot cadence


def _safe(fn, label: str):
    """Wrap a harvester so a scheduler job never dies on a transient error."""
    def job():
        try:
            fn()
        except Exception as exc:  # logged, never crashes the scheduler
            storage.log_harvest(label, label, "live", "error", detail=str(exc)[:300])
    return job


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    storage.init_db()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(_safe(prices.run, "prices"),
                      IntervalTrigger(minutes=PRICES_INTERVAL_MIN), id="prices",
                      next_run_time=None)
    scheduler.add_job(_safe(news.run, "news"),
                      IntervalTrigger(minutes=NEWS_INTERVAL_MIN), id="news",
                      next_run_time=None)
    scheduler.add_job(_safe(sanctions.run, "sanctions"),
                      IntervalTrigger(minutes=SANCTIONS_INTERVAL_MIN), id="sanctions",
                      next_run_time=None)
    scheduler.add_job(_safe(anomalies.run, "anomalies"),
                      IntervalTrigger(minutes=ANOMALIES_INTERVAL_MIN), id="anomalies",
                      next_run_time=None)
    scheduler.add_job(_safe(playbook_engine.refresh_all, "playbooks"),
                      IntervalTrigger(minutes=playbook_engine.refresh_interval_minutes()),
                      id="playbook_refresh", next_run_time=None)
    # DataDocked remains manual because area calls consume credits. AISStream is continuous when a
    # backend-only key is configured; its recorder owns reconnect/backoff and cache fallback.
    if ais.active_provider() == "aisstream" and not ais.is_dormant():
        scheduler.add_job(ais.run, id="ais", next_run_time=None)
    scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="HEIMDALL", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """System health + data-age report. The Phase 0 gate reads this to confirm provenance."""
    conn = storage.get_db()
    try:
        rows = conn.execute(
            "SELECT harvester, source, kind, status, fetched_at, record_count"
            " FROM harvest_log ORDER BY id DESC LIMIT 20"
        ).fetchall()
        recent = [dict(r) for r in rows]
        counts = conn.execute(
            "SELECT harvester, COUNT(*) c FROM harvest_log GROUP BY harvester"
        ).fetchall()
    finally:
        conn.close()
    return {
        "status": "ok",
        "llm": llm.health(),
        "ais": {
            "provider": ais.active_provider(),
            "dormant": ais.is_dormant(),
            "credits": ais_keypool.status() if ais.active_provider() == "datadocked" else None,
        },
        "harvest_counts": {r["harvester"]: r["c"] for r in counts},
        "recent_harvests": recent,
    }


@app.get("/api/latest/{namespace}")
def latest(namespace: str) -> dict[str, Any]:
    """All latest tagged values in a namespace (prices|news|sanctions|anomalies|ais)."""
    return {"namespace": namespace, "items": storage.get_namespace(namespace)}


@app.post("/api/harvest/{name}")
def trigger_harvest(name: str) -> dict[str, Any]:
    """Manually run one harvester now (dev + demo control)."""
    runners = {
        "prices": prices.run, "news": news.run, "sanctions": sanctions.run,
        "anomalies": anomalies.run,
        "ais": (lambda: ais.run(duration_s=20)) if ais.active_provider() == "aisstream" else ais.run,
        "sim": sim.run,
    }
    fn = runners.get(name)
    if not fn:
        return {"error": f"unknown harvester '{name}'", "available": list(runners)}
    return {"harvester": name, "result": fn()}


@app.get("/api/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/api/replay/frame")
def replay_frame(at: str = Query(..., description="ISO-8601 simulation timestamp")) -> dict[str, Any]:
    """Leakage-guarded replay frame: only evidence and EIA Brent visible at the simulation clock."""
    from datetime import datetime, timezone
    from .lib.provenance import SourceKind, tag
    from .replay.loader import ReplayDataset

    sim_now = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if sim_now.tzinfo is None:
        sim_now = sim_now.replace(tzinfo=timezone.utc)
    dataset = ReplayDataset()
    start, end = dataset.window()
    sim_now = min(max(sim_now, start), end)
    visible = dataset.evidence_at(sim_now)
    brent_series = dataset.brent_series_to(sim_now)
    latest = visible[-1] if visible else None
    raw = dataset.risk_raw_at(sim_now, "hormuz")
    replay_risk = risk_engine.compute("hormuz", raw).to_dict()
    return tag({
        "sim_now": sim_now.isoformat(), "window": [start.isoformat(), end.isoformat()],
        "latest_evidence": latest, "visible_evidence": visible,
        "brent_usd_bbl": dataset.brent_at(sim_now), "brent_series": brent_series,
        "risk": replay_risk,
        "dataset_status": "curated immutable sourced evidence + authoritative EIA Brent",
    }, "HEIMDALL chronological replay", SourceKind.REPLAY,
        note="leakage-guarded; source URLs preserved; replay tone is an explicit config rule").to_dict()


@app.get("/api/replay/backtest")
def replay_backtest() -> dict[str, Any]:
    """Serve the precomputed locked historical proof; never re-run the solver on a UI read."""
    import json
    from .lib.provenance import SourceKind, tag
    from .replay.backtest import RESULT_PATH

    if not RESULT_PATH.is_file():
        return {"error": "backtest result not generated; run `make replay-lock && make backtest`"}
    result = json.loads(RESULT_PATH.read_text())
    return tag(result, "HEIMDALL locked historical case study", SourceKind.REPLAY,
               note="single-event sourced replay; planning counterfactual, not booked savings").to_dict()


@app.get("/api/headlines")
def headlines() -> dict[str, Any]:
    """Real GDELT headlines for the live news panel. Cached in `latest` (30-min TTL) so the UI
    never hammers the rate-limited DOC API."""
    cached = storage.get_latest("news", "headlines")
    if cached:
        prov = cached["payload"].get("provenance", {})
        if (prov.get("age_hours") or 99) < 0.5:
            return cached["payload"]
    try:
        from gdeltdoc import GdeltDoc, Filters, near
        from .lib.provenance import SourceKind, tag as _tag
        f = Filters(keyword="Strait of Hormuz", near=near(20, "oil", "tanker"),
                    timespan="3d", num_records=12)
        arts = GdeltDoc().article_search(f)
        rows = []
        if arts is not None and not arts.empty:
            for _, a in arts.head(12).iterrows():
                rows.append({"title": str(a.get("title", ""))[:140],
                             "domain": a.get("domain", ""), "url": a.get("url", ""),
                             "seendate": str(a.get("seendate", ""))})
        payload = _tag({"articles": rows}, "GDELT DOC article search", SourceKind.LIVE,
                       source_url="https://api.gdeltproject.org/api/v2/doc/doc").to_dict()
        storage.put_latest("news", "headlines", payload, "GDELT DOC", "live")
        return payload
    except Exception:
        if cached:
            return cached["payload"]
        return {"value": {"articles": []}, "provenance": {"kind": "cache", "note": "gdelt unavailable"}}


@app.get("/api/brief")
def ai_brief() -> dict[str, Any]:
    """HEIMDALL BRIEF — LLM narrative for the highest-risk corridor (cached via llm cache)."""
    from .engines import evidence as ev
    from .engines import risk as rk
    risks = {cid: rk.compute(cid, rk.gather_raw(cid)).index
             for cid in rk._corridors() if not rk._corridors()[cid].get("reroute_reference")}
    top = max(risks, key=risks.get)
    return ev.build_bundle(top, with_narrative=True)


@app.get("/api/tankers")
def tankers() -> dict[str, Any]:
    """Latest tanker positions for the map. Prefers a live datadocked 'ais' snapshot; falls back to
    a flagged SIM 'ais_sim' snapshot. Rows carry source ('datadocked'|'sim') so the UI flags SIM."""
    import pandas as pd
    live = storage.latest_snapshot("ais")
    sim = storage.latest_snapshot("ais_sim")
    path = live or sim
    if path is None:
        return {"tankers": [], "source": None, "synthetic": False}
    df = pd.read_parquet(path)
    is_sim = str(path.name).startswith("ais_sim_")
    cols = [c for c in ("mmsi", "name", "lat", "lon", "sog", "cog", "heading",
                        "ship_type", "corridor", "source") if c in df.columns]
    rows = df[cols].where(pd.notna(df[cols]), None).to_dict("records")
    row_source = "sim" if is_sim else (
        str(df["source"].dropna().iloc[-1]) if "source" in df.columns and not df["source"].dropna().empty
        else "ais"
    )
    return {"tankers": rows, "source": row_source,
            "synthetic": is_sim, "count": len(rows), "snapshot": path.name}


@app.get("/api/ais/status")
def ais_status() -> dict[str, Any]:
    """Non-sensitive AIS provider/stream state; never returns credentials."""
    latest_stream = storage.get_latest("ais", "stream_status")
    live_snapshot = storage.latest_snapshot("ais")
    sim_snapshot = storage.latest_snapshot("ais_sim")
    snapshot_source = None
    if live_snapshot:
        try:
            import pandas as pd
            sources = pd.read_parquet(live_snapshot, columns=["source"])["source"].dropna()
            snapshot_source = str(sources.iloc[0]) if not sources.empty else None
        except Exception:
            snapshot_source = None
    return {
        "provider": ais.active_provider(),
        "configured": not ais.is_dormant(),
        "stream": latest_stream["payload"] if latest_stream else None,
        "live_snapshot": live_snapshot.name if live_snapshot else None,
        "snapshot_source": snapshot_source,
        "sim_fallback": sim_snapshot.name if sim_snapshot else None,
        "credential_exposed": False,
    }


# ------------------------------- Phase 1 engine endpoints -------------------------------
@app.get("/api/risk")
def risk_all() -> dict[str, Any]:
    """Corridor Risk Index (0-100, NOT a probability) + separate confidence, all corridors."""
    return {"corridors": risk_engine.risk_all()}


@app.get("/api/risk/{corridor_id}")
def risk_one(corridor_id: str) -> dict[str, Any]:
    return risk_engine.risk_for_corridor(corridor_id)


@app.get("/api/intelligence")
def corridor_intelligence() -> dict[str, Any]:
    """Cross-source convergence + explainable AIS pulse for all modeled corridors."""
    return intelligence_engine.intelligence_all()


@app.get("/api/evidence/{corridor_id}")
def evidence_one(corridor_id: str,
                 narrative: bool = Query(False, description="include LLM narrative")) -> dict[str, Any]:
    """Full evidence bundle behind a corridor alert. narrative=true adds schema-validated LLM prose."""
    return evidence_engine.build_bundle(corridor_id, with_narrative=narrative)


@app.get("/api/cascade")
def cascade(corridor: str = Query(..., description="corridor id"),
            severity: float = Query(..., ge=0.0, le=1.0),
            duration_days: float = Query(..., gt=0.0)) -> dict[str, Any]:
    """Deterministic cascade twin for a single corridor shock."""
    return cascade_engine.cascade_tagged(
        [cascade_engine.CorridorShock(corridor, severity, duration_days)])


@app.post("/api/cascade")
def cascade_multi(shocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Cascade for one or more simultaneous corridor shocks.
    Body: [{"corridor": "hormuz", "severity": 0.6, "duration_days": 14}, ...]"""
    parsed = [cascade_engine.CorridorShock(s["corridor"], float(s["severity"]),
                                           float(s["duration_days"])) for s in shocks]
    return cascade_engine.cascade_tagged(parsed)


@app.get("/api/montecarlo")
def montecarlo(corridor: str = Query(...), severity: float = Query(..., ge=0.0, le=1.0),
               duration_days: float = Query(..., gt=0.0),
               n: int = Query(None, description="samples (default from mc_params)")) -> dict[str, Any]:
    """Monte Carlo stress of a scenario. Outputs frequency-based probabilities (reproducible)."""
    return mc_engine.mc_tagged(
        [cascade_engine.CorridorShock(corridor, severity, duration_days)], n_samples=n)


# ------------------------------- Phase 2 response optimizer -------------------------------
@app.post("/api/plans")
def plans(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Three solver-generated response plans (Cost-First / Security-First / Balanced) for a scenario.
    Body: {"corridor_states": {"hormuz": "closed"}, "restrict_severity": 0.5}. Empty body = baseline."""
    return allocator_engine.three_plans(_scenario_from_body(body))


@app.post("/api/plans/greedy")
def plans_greedy(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Greedy fallback plan (sanity baseline) for the same scenario shape."""
    return greedy_engine.greedy_tagged(_scenario_from_body(body))


@app.get("/api/routes")
def routes() -> dict[str, Any]:
    """Per-supplier sea routes + traversed chokepoints (searoute — strategic planning estimates)."""
    return {"routes": routes_engine.compute_routes(),
            "note": "searoute routes are strategic planning estimates, not navigational"}


@app.get("/api/network")
def network() -> dict[str, Any]:
    """Curated India energy-twin nodes for the map, with source metadata kept alongside them."""
    import json
    from .lib.provenance import SourceKind, tag

    root = Path(__file__).resolve().parents[1] / "data"
    ports = json.loads((root / "ports.json").read_text())
    refineries = json.loads((root / "refineries.json").read_text())
    spr = json.loads((root / "spr.json").read_text())
    value = {
        "ports": ports["ports"],
        "refineries": refineries["refineries"],
        "spr": spr["facilities"],
        "sources": {
            "ports": ports["_meta"], "refineries": refineries["_meta"], "spr": spr["_meta"],
        },
    }
    return tag(value, "HEIMDALL curated energy network", SourceKind.CONFIG,
               note="public-source nodes; modeled capacities are labelled demo assumptions").to_dict()


def _scenario_from_body(body: dict[str, Any] | None) -> Scenario:  # noqa: F811 (extended form)
    body = body or {}
    defaults = Scenario()
    return Scenario(
        corridor_states=body.get("corridor_states", {}),
        restrict_severity=float(body.get("restrict_severity", 0.5)),
        live_risk=body.get("live_risk"),
        unavailable_suppliers=body.get("unavailable_suppliers", []),
        disabled_refineries=body.get("disabled_refineries", []),
        duration_days=float(body.get("duration_days", defaults.duration_days)),
        price_shock_usd_bbl=float(body.get("price_shock_usd_bbl", defaults.price_shock_usd_bbl)),
        demand_change_pct=float(body.get("demand_change_pct", defaults.demand_change_pct)),
        vessel_availability_pct=float(body.get("vessel_availability_pct", defaults.vessel_availability_pct)),
        port_congestion_pct=float(body.get("port_congestion_pct", defaults.port_congestion_pct)),
    )


@app.get("/api/scenario/options")
def scenario_options() -> dict[str, Any]:
    """Config-backed Scenario Lab bounds, suppliers, refineries, and corridors."""
    return allocator_engine.scenario_options()


# ------------------------------- Phase 3 playbook lifecycle -------------------------------
@app.post("/api/certify")
def certify(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Certify the three plans for a scenario; returns robustness certificates + recommended."""
    sc = _scenario_from_body(body)
    plans = {p: allocator_engine.solve(sc, p) for p in allocator_engine.PRESETS}
    return certify_engine.recommend_tagged(plans, sc)


@app.post("/api/playbooks")
def create_playbook(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate an expiring, certified playbook for a scenario."""
    return playbook_engine.generate_tagged(_scenario_from_body(body))


@app.get("/api/playbooks")
def list_playbooks() -> dict[str, Any]:
    return {"playbooks": playbook_engine.list_playbooks()}


@app.get("/api/playbooks/{playbook_id}")
def get_playbook(playbook_id: str) -> dict[str, Any]:
    pb = playbook_engine.get(playbook_id)
    return pb or {"error": f"playbook {playbook_id} not found"}


@app.post("/api/playbooks/{playbook_id}/refresh")
def refresh_playbook(playbook_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check triggers; if stale, mark STALE with reason and regenerate with an updated certificate.
    Optional body {"new_snapshot": {...}} to simulate drift (demo control)."""
    new_snap = (body or {}).get("new_snapshot")
    return playbook_engine.refresh(playbook_id, new_snapshot=new_snap)


@app.post("/api/packet/{playbook_id}")
def action_packet(playbook_id: str, preset: str = Query(...)) -> dict[str, Any]:
    """Assemble an action packet for the approved preset (recommendation only; human authorises)."""
    return packet_engine.build_packet(playbook_id, preset)


@app.get("/api/cost-of-delay")
def cost_of_delay(corridor: str = Query(...), severity: float = Query(..., ge=0.0, le=1.0),
                  duration_days: float = Query(..., gt=0.0)) -> dict[str, Any]:
    return packet_engine.cost_of_delay(corridor, severity, duration_days)


@app.get("/api/resilience")
def resilience(n: int = Query(None, description="MC samples per scenario")) -> dict[str, Any]:
    """National Energy Resilience Score over the six curated stress scenarios (decomposable)."""
    return resilience_engine.compute(n_samples=n)
