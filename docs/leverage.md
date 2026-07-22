# HEIMDALL — Leverage Log

Standing instruction: search GitHub/PyPI before hand-building any nontrivial subsystem. Record
what was adopted or rejected and why. Prefer `pip install` + thin adapter over reimplementation.

## Adopted

| Subsystem | Library | Why | License |
|---|---|---|---|
| Live news signal | **gdeltdoc** (`alex9smith/gdelt-doc-api`) | Wraps GDELT DOC timelinevol/timelinetone; keyword+near query builder. Saved hand-rolling the DOC query grammar. Adapter adds rate-limit backoff + provenance. | MIT |
| LLM access | **openai** SDK (provider-neutral) | Groq + GLM/Z.ai are both OpenAI-compatible; one SDK, switch base_url+key. No per-provider clients. | Apache-2.0 |
| Sea routes / chokepoints | **searoute** (`genthalili/searoute-py`) | `return_passages=True` detects Hormuz/Suez/Malacca/Bab-el-Mandeb. Planning-estimate labeling per Truth Constraint #5. Installed; wired in Phase 2. | MIT |
| Optimizer | **OR-Tools** | Pre-approved. Shipment allocation LP/MIP in Phase 2. | Apache-2.0 |
| Prices | **EIA Open Data API** (direct REST) | Authoritative Brent; thin `requests` adapter, no library needed. | Public API |
| Sanctions | **OFAC SDN CSV** (direct download) | Canonical, no key, one `requests` call + CSV parse. No library warranted. | Public data |
| Time series storage | **pyarrow/parquet** + **SQLite** | Locked stack. Survive dead venue wifi — the feature. | Apache-2.0 / public domain |

## Rejected / deferred

| Considered | Decision | Reason |
|---|---|---|
| Gemini (original spec LLM) | **Replaced** with Groq primary + GLM fallback | Session decision 2026-07-21; no Gemini anywhere. |
| aisstream.io live AIS | **Adopted as continuous primary; cache-backed** | User-owned key configured backend-only on 2026-07-22. Official decoded-JSON WebSocket needs no NMEA library. Recorder joins ShipStaticData to PositionReports by MMSI, filters tanker codes 80-89 locally, snapshots parquet, and reconnects with backoff. A direct verification handshake reached the service but returned HTTP 503, so the UI reports CACHE until an actual AIS frame is received. |
| **datadocked.com** REST AIS | **Adopted** as cache-backed AIS snapshot provider | `get-vessels-by-area` produced 551 unique real tanker positions in the bounded 2026-07-22 demo refresh. Thin `requests` adapter + credit-metered key pool; local tanker filtering and MMSI deduplication. Expanded density scans render on the map but are excluded from like-for-like corridor pulse baselines. Snapshot source, not continuous. |
| Marine Cadastre / Piraeus AIS bulk datasets | **Rejected for corridor AIS** | Marine Cadastre = US waters only; Piraeus = one Greek port. Neither covers Hormuz/Gulf, so useless for our corridors. SIM augmentation on real searoute paths covers demo density instead. |
| SIM augmentation (own) | **Built** | Synthetic tanker tracks on real searoute geometry, flagged + separate parquet prefix per the project specification. Gives temporal depth for the anomaly detector and demo density without burning AIS credits. |
| `pyais` (NMEA decode) | **Not needed yet** | aisstream delivers decoded JSON; raw-NMEA decoding unnecessary unless we switch to a raw feed. |
| Postgres/PostGIS + Docker | **Rejected** (recorded in the architecture decision log) | Zero demo value, nonzero setup + failure tax. SQLite + parquet chosen. |
| SupplyNetPy / miniSCOT (supply-chain DES) | **Deferred (stretch)** | Our deterministic cascade twin + Monte Carlo covers competition scope; full DES is over-engineering for the demo. |
| `gdelt`, `gdelt-py`, `gdelt-client`, and a public bulk-parser gist | **Reviewed; no new dependency adopted for replay** | These can fetch/parse the 15-minute archives, but pulling a broad two-month archive adds large download and venue-network risk. Truth Constraint #4 also permits a curated immutable evidence dataset with original URLs/timestamps. HEIMDALL uses that smaller, inspectable lane and explicitly does not claim GDELT tone or bulk provenance. |

## UI references (Phase 4)

| Project | Use | License note |
|---|---|---|
| koala73/worldmonitor | Visual/UX reference for the War Room: same map stack (deck.gl + MapLibre GL), dark situational-awareness aesthetic, layer patterns. | **AGPL-3.0 — copyleft.** Borrow patterns/look ONLY, never copy code (would force AGPL on HEIMDALL). The implementation follows the original `design/tokens.md` contract. |
| Natural Earth 1:110m countries (`nvkelso/natural-earth-vector`) | Bundled local GeoJSON supplies coastlines/country context when venue networking is unavailable. Loaded as a static map layer; Carto remains an optional online basemap. | Natural Earth data is public domain. |

World Monitor was re-evaluated on 2026-07-22 from its official repository and current dashboard
screenshot. Adopted patterns: persistent layer matrix, map-first hierarchy, compact situation ribbon,
three-part intelligence dock, source-convergence labels, chokepoint traffic pulse, visible time
windows, and command-desk cards. The changelog's enter/dwell/exit crossing model was evaluated but
**not claimed or copied**: HEIMDALL currently exposes snapshot population + rolling snapshot median
and labels it "not a certified crossing count." Rejected: copying AGPL source, its global feature
sprawl (aircraft, webcams, crypto, generic global panels), and its green-as-everything palette.
HEIMDALL uses a clean-room React implementation and retains the state-semantic colors in
`design/tokens.md`.

References reviewed: [WorldMonitor repository](https://github.com/koala73/worldmonitor),
[architecture](https://github.com/koala73/worldmonitor/blob/main/ARCHITECTURE.md), and
[changelog](https://github.com/koala73/worldmonitor/blob/main/CHANGELOG.md). The independent-origin
convergence gate is a HEIMDALL implementation: GDELT volume+tone count as one NEWS origin, while
market, AIS, and sanctions are separate origins. Three active origins are required for CONFIRMED;
this is a corroboration class, never a disruption probability.

## Historical replay leverage decision (Phase 5)

Reviewed [GDELT 2.0](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/),
the official [Event codebook](https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf),
and the `gdelt`, `gdelt-py`, and `gdelt-client` PyPI packages before implementing replay. The
competition build uses the spec-permitted curated lane because it is smaller, offline-reliable,
and directly auditable. `backend/replay/backtest.py` is intentionally a thin evaluator over the
existing loader/engines rather than a second simulation stack.
