# HEIMDALL — Phase Status

## ✅ Phase 0 — Foundation & data capture (COMPLETE 2026-07-21)

Gate: *`data/snapshots/` grows; every stored record carries source and timestamp.* **MET.**

Delivered:
- Repo scaffold, `.venv`, locked stack installed, git history with small commits.
- LLM stack switched Gemini→**Groq primary + GLM fallback** (both verified live; auto-failover; input-hash cache to protect Groq free-tier quota).
- Config YAMLs (corridors, risk_weights, cascade, mc, playbook_triggers) — every constant sourced/flagged; Risk Index documented as index≠probability.
- Curated datasets (spr, import_mix, suppliers, grades, refineries, ports) — all with source+date `_meta` headers.
- `lib/`: provenance (Tagged values + data-age badges), storage (SQLite state + parquet), llm (provider-neutral).
- Harvesters: prices (EIA authoritative + display cache), news (GDELT live lane), sanctions (OFAC),
  anomalies, and AIS (AISStream continuous primary with DataDocked snapshot + SIM fallbacks).
- FastAPI + APScheduler; `/api/health` data-age report; manual harvest triggers; `/api/latest` reads — all provenance-tagged.
- Replay: leakage guard, monotonic clock, and immutable 2025 dataset with **real EIA Brent**
  ($63→$80.37 peak 06-19→$69 post-ceasefire) plus 12 sourced chronological evidence records.
- `docs/sources.md`, `docs/leverage.md`, Makefile.

Carry-forward:
- **AIS: RESOLVED.** A user-owned AISStream key is backend-only and the continuous recorder is
  active with reconnect/backoff; the latest direct handshake reached upstream but returned HTTP
  503, so the UI truthfully stays on cache until a real frame arrives. **DataDocked** remains the
  refreshed 551-tanker real snapshot fallback (104 within comparable primary corridor circles).
  Expanded-area rows add map density without entering unlike-for-like pulse baselines; SIM
  augmentation stays separate and visibly flagged.
- GDELT DOC rate-limits hard on rapid sweeps; hourly scheduler cadence avoids it. Only hormuz landed live in the burst test; others degrade to cache cleanly (by design).

## ✅ Phase 1 — Core engines (COMPLETE 2026-07-22)

Gate: *`/api/risk` and `/api/cascade` return sane, explainable, provenance-tagged numbers.* **MET.**

Delivered:
- **engines/cascade.py** — deterministic India cascade twin (pure functions, sourced constants,
  multi-corridor). Hand-verified: Hormuz 50%/14d → deficit 0.839 mb/d, +$32/bbl, no shortage
  (97-day buffer); Red Sea full/30d → reroute-heavy, +$4.32; combined → 23.82% deficit. 6 tests.
- **engines/risk.py** — Corridor Risk Index 0-100 (evidence fusion, **NOT probability**) + SEPARATE
  confidence (signal count / agreement / freshness / completeness). Component breakdown,
  contradiction detection, missing-signal tracking. 11 hand-computed tests. Live: Hormuz 31.36/0.75.
- **engines/montecarlo.py** — seeded, reproducible MC over cascade; frequency-based probabilities
  (only licensed "probability" use). Discriminates: 14d holds, 60d full closure → P(shortage) 0.98.
  5 tests.
- **engines/evidence.py** — per-corridor bundle: index + components + affected suppliers/refineries
  (grade-class exposure) + freshness + contradictions + expected consequence (cascade preview) +
  LLM narrative (prose only, schema-validated, cached, never invents numbers). 4 tests.
- **API**: `/api/risk`, `/api/risk/{id}`, `/api/evidence/{id}`, `/api/cascade` (GET+POST multi),
  `/api/montecarlo` — all live, provenance-tagged. **36 tests pass.**

## ✅ Phase 2 — Optimisation (COMPLETE 2026-07-22)

Gate: *zero-constraint-violation suite passes; kill a corridor → all 3 plans provably avoid it.*
**MET** (24 gate tests + live demo).

Delivered:
- **engines/routes.py** — searoute passage detection per supplier (real load ports). Gulf→Hormuz
  (no bypass, not reroutable); Russia/US→Suez/Red Sea (Cape-reroutable); Atlantic→Cape. Freight
  from distance. Labelled "strategic planning estimates" (Truth Constraint #5).
- **engines/allocator.py** — OR-Tools GLOP LP. Vars: supplier→refinery, SPR→refinery, commercial,
  shortage slack. **Hard constraints** (structural, never penalized): availability, route closure,
  port + refinery capacity, grade compatibility, arrival window, max SPR drawdown rate, OFAC
  exclusion, reserves-for-gaps-only, demand balance. Objective = weighted preset. 3 plans.
- **engines/greedy.py** — greedy feasible fallback behind the same interface (sanity baseline;
  LP proven ≤ greedy on cost).
- **engines/sanctions_screen.py** — OFAC hard exclusion (supplier + vessel-name screening).
- **config/solver_presets.yaml** — Cost-First / Security-First / Balanced weight sets.
- Reserves priced last-resort (strategic premium + scarcity-gap cap) → SPR not drained in calm.
- **API**: `POST /api/plans`, `POST /api/plans/greedy`, `GET /api/routes`.
- Live: Hormuz closed → 4 Gulf suppliers excluded ("no sea bypass"), zero Gulf in all plans, all
  OPTIMAL, cost $85→$96, presets distinct. **60 tests pass.**

## ✅ Phase 3 — Playbook lifecycle (COMPLETE 2026-07-22)

Gate: *drift an input past threshold → playbook goes STALE with reason and regenerates with an
updated certificate.* **MET** (live + 7 lifecycle tests).

Delivered:
- **engines/certify.py** — Robustness Certificate: stress each fixed plan through sampled futures
  (cheap eval, no re-solve, seeded). Pass rate + 95% CI, worst/expected shortfall, cost-at-risk,
  max delay, failure conditions, binding constraints. recommend() picks the recommended plan
  (≥80% pass), records rejected reasons + fallback. No plan recommended without a certificate.
  Concentration asymmetry emerges (Cost-First worst-shortfall > diversified).
- **engines/playbooks.py** — expiring certified playbooks (validity window + input snapshot + 3
  plans + certificates + recommended/fallback + pre-crisis no-regret actions). SQLite-persisted.
  check_staleness vs playbook_triggers.yaml (price/risk/sanctions/corridor/time); refresh() marks
  STALE with reason and regenerates. **Live gate verified.**
- **engines/packet.py** — auditable action packet on approval (AWAITING_HUMAN_AUTHORISATION;
  HEIMDALL never executes) + cost_of_delay() premium $/day range from cascade + MC.
- **engines/resilience.py** — decomposable National Energy Resilience Score over 6 stress
  scenarios (~89; surfaces real weakness — Sikka port outage strands 1.1 mb/d).
- allocator Scenario gains unavailable_suppliers + disabled_refineries.
- **API**: `/api/certify`, `/api/playbooks` (POST/GET/refresh), `/api/packet/{id}`,
  `/api/cost-of-delay`, `/api/resilience`. **78 tests pass.**

## ✅ Phase 4 — War Room UI (COMPLETE 2026-07-22)

Gate: *full demo runs end-to-end with networking disabled.* **MET at the substance level** —
engine flow (scenario → plans → certificate → packet + resilience) is pure Python over
config+data+cache with zero network calls (verified); map basemap is offline-safe (no remote tiles
required). Live badges degrade to cache age. Visual confirmation needs a real browser (headless
WebGL is OOM-killed in this environment; app builds clean and all consumed endpoints return 200).

Delivered — implements the HEIMDALL Design Language:
- **design/**: tokens.md + tokens.css + tailwind.config.js (binding visual contract). Dark
  mission-control, IBM Plex Sans/Mono, risk-band colors, square corners, and hairlines.
- **frontend/** (Vite + React 18 + TS + Tailwind + deck.gl + react-map-gl/maplibre):
  - WarMap — corridor risk halos, supplier→India flow arcs (real searoute load ports), tanker
    positions (live datadocked + flagged SIM). Offline-safe basemap.
  - RightRail — 64px resilience hero + decomposable breakdown; corridor risk cards (band-color
    index + SEPARATE confidence + 6-component bars + evidence expander); cost-of-delay ticking
    meter; expiring playbook shelf (countdown + robustness badge + STALE).
  - BottomRail — LIVE/REPLAY + 2025-standoff timeline scrubber + event pips + speed.
  - Drawer — scenario controls, 3-plan comparison (recommended accent + badge), certificate
    detail, action packet, evidence bundle.
  - primitives — Card/Badge/DataAge/Button/MicroBar/SegmentBar.
- backend `/api/tankers` (latest snapshot positions, SIM-flagged).
- Doctrine in UI: every number carries provenance; index≠probability; confidence separate; SIM flagged.

### War Room product pass — 2026-07-22

- Rebuilt the information hierarchy as an energy-specific situational-awareness surface using a
  clean-room interpretation of World Monitor patterns (no AGPL source copied): persistent layer
  matrix, situation ribbon, map-first theatre, command desk, and three-part intelligence dock.
- Added sourced India network layers: 8 refineries, 8 import terminals, and 3 SPR facilities via
  `/api/network`. Bundled public-domain Natural Earth boundaries so geography remains visible
  offline even when the Carto basemap is unavailable.
- Scenario inputs now stage locally and launch one deliberate optimizer/certification run instead
  of re-solving on every slider movement.
- Added comparative certified-plan workspace, full evidence component/freshness/source ledger,
  pre-crisis no-regret actions, and downloadable/printable human action packets.
- Wired the replay scrubber to `/api/replay/frame`: each frame is leakage-guarded and exposes only
  sourced evidence plus authoritative EIA Brent visible at the simulated timestamp.
- Added WorldMonitor-inspired source convergence, honest AIS pulse/status, refinery-run impacts,
  and real Scenario Lab controls for duration, price shock, demand, vessel availability, congestion,
  supplier failure, refinery outage, and corridor state.
- Production frontend build and real-browser end-to-end scenario flow pass.

**Run:** `make dev` (backend :8100) + `cd frontend && npm run dev` (:5174).

## ✅ Phase 5A — Historical proof (COMPLETE 2026-07-22)

- Implemented the spec-permitted curated immutable replay lane: 12 original source URLs/timestamps
  plus 41 authoritative EIA daily Brent prints. No live GDELT DOC data and no future records enter.
- `make replay-lock` SHA-256 locks six engine/config surfaces; `make backtest` refuses drift.
- Actual locked run: **1 calendar-day lead (0–2d precision band)**, **$230.157M planning
  counterfactual** under the stated $5.16/bbl × 3.186 mb/d × 14d assumption, **0 shortage days
  avoided** because buffers cover the horizon, and **~1.17s engine compute** for three plans plus
  80 fixed-plan futures per certificate. Full caveats and audit links live in `docs/metrics.md`.
- Replay mode reads `/api/replay/backtest` and displays those computed results with explicit
  counterfactual/precision labels.

## Phase 5B — Submission polish (NEXT)

Run the final resilience batch; rehearse the sourced replay arc; capture demo video; create the
architecture visual and deck. Do not use the old “47 days to 47 minutes” line as a measured result;
the locked proof supports the bounded numbers above.
