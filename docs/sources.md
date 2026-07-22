# HEIMDALL — Source Registry

Every data source, its authority level, and its honesty constraint. If a number is on screen, it
traces to a row here or to an engine that computed it from these. Updated as sources are added.

## Live / authoritative sources

| Source | Used for | Authority | Cadence | Honesty constraint | Status |
|---|---|---|---|---|---|
| EIA Open Data API v2 (series RBRTE, Europe Brent Spot FOB) | Brent price history + spot; replay price series | **Authoritative** (Truth Constraint #6) | daily | The only price source allowed to feed replay/analysis | ✅ live, verified 2026-07-21 (Brent $81.62) |
| yfinance (BZ=F) | Live ticker display only | Convenience | hourly | Never feeds replay or analysis; labeled "live display only" | ✅ wired |
| GDELT DOC API (via `gdeltdoc`) | Live news volume + tone per corridor | Live monitoring lane | hourly | **~3-month coverage only — NEVER used for replay** (Truth Constraint #4) | ✅ live, hormuz verified (57 recs) |
| OFAC SDN list (treasury.gov/ofac/downloads/sdn.csv) | Sanctioned suppliers + vessels; solver hard exclusion | Authoritative (screening) | daily | Real screening in the solver, not decoration | ✅ live, verified (19,169 entities / 1,517 vessels) |
| **datadocked.com** `get-vessels-by-area` | Live tanker positions per corridor chokepoint | Live (satellite+terrestrial AIS) | manual/snapshot (10 cr/call) | Returns ALL vessel types; tanker filter is LOCAL on `typeSpecific` (Truth Constraint #1). Credit-metered via key pool. Expanded demo-density circles remain visible but are excluded from like-for-like pulse baselines. | ✅ **live, refreshed 2026-07-22 — 551 unique real tanker positions; 104 in four consistent primary observation circles** |
| aisstream.io WebSocket | Continuous tanker positions (primary when frames arrive) | Live (beta, no SLA) | continuous | Subscription requests only bboxes + message types. ShipStaticData is joined to PositionReports by MMSI; tanker type codes 80-89 are filtered LOCALLY (Truth Constraint #1). UI says CACHE until a frame is actually received. | ⚠️ key configured 2026-07-22; direct verification reached upstream but handshake returned HTTP 503; recorder reconnect/backoff active |
| **SIM augmentation** | Synthetic tanker density for offline/rehearsed demo | Synthetic (DEMO) | on demand | Rows flagged `synthetic=True`, separate `ais_sim` parquet prefix, never mixed with live per the project specification | ✅ tracks on real searoute paths; drives CLUSTER_TURN in demo |

## Curated static extracts (`data/*.json`, source+date headers)

| File | Source | Notes |
|---|---|---|
| `spr.json` | ISPRL / MoPNG public figures | Phase I 5.33 MMT (Vizag 1.33, Mangaluru 1.5, Padur 2.5) ≈ 9.5 days cover |
| `import_mix.json` | PPAC + trade press, FY2024-25 | Supplier shares; Hormuz-dependent ≈ 45% |
| `suppliers.json` | Public assay refs (EIA/OPEC/NOC); availability = demo assumption | 9 suppliers, grade/API/sulphur/corridor |
| `grades.json` | Standard petroleum classification | Grade→class map for compatibility constraint |
| `refineries.json` | Operator public capacities (RIL/IOCL/BPCL/HPCL/NRL) | 8 refineries, coast + accepted grade classes |
| `ports.json` | World Port Index subset | Import terminals + reference load ports |

## Replay dataset (`data/replay/2025-standoff/`)

| File | Source | Status |
|---|---|---|
| `brent_daily.json` | EIA RBRTE, 2025-05-01→06-30 | **Real, immutable.** $63→$80.37 (06-19)→$69 (post-ceasefire 06-24) |
| `evidence.jsonl` | Curated immutable public-record lane: IAEA, UN, IMO-linked maritime reporting, official statements, and dated Reuters reports | **Sourced and immutable.** Original URL + timestamp precision on every row; no GDELT-tone claim |
| `config_lock.json` | SHA-256 manifest over risk/corridor/cascade/MC/solver/backtest configs | Backtest refuses post-lock config drift |
| `backtest_result.json` | Chronological risk → OR-Tools → certificate case-study output | Computed; premium clearly labelled a counterfactual, not booked savings |

Primary replay evidence links are retained row-by-row in `evidence.jsonl`, including the IAEA
Board resolution, UN Security Council meeting records, the IMO maritime bibliography, UKMTO-linked
electronic-interference warning, Qatar ceasefire statement, and dated Reuters reporting. The live
GDELT DOC API remains excluded from replay.

## API keys (backend-only, in `.env`, gitignored)

`EIA_API_KEY` ✅ · `GROQ_API_KEY` ✅ (primary LLM) · `GLM_API_KEY` ✅ (fallback LLM) ·
`DATADOCKED_API_KEYS` ✅ (16-key pool; 160 credits remain after the bounded demo refresh) · `AISSTREAM_API_KEY` ✅
(backend-only; configured 2026-07-22, upstream frame receipt not yet verified because the direct
handshake returned HTTP 503).

**Credit discipline (datadocked):** area call = 10 credits. The 2026-07-22 demo refresh used 140
credits and produced `ais_20260722T171022Z.parquet`: 551 MMSI-deduplicated, real Data Docked rows
with no SIM mixing. AIS remains a manual snapshot source, never a fast polling loop. Expanded port
and anchorage circles add map density, while `risk_observation` restricts pulse comparisons to one
consistent 50 km circle per corridor. The SQLite key pool records spend and refuses unaffordable
calls. SIM augmentation remains separate for chronological replay and sparse/offline conditions.
