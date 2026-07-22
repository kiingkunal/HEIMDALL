# HEIMDALL design language v1.0 — `design/tokens.md`

Styling contract for the War Room UI (L5). Binding: implement from `design/tokens.css` + `design/tailwind.config.js`; do not freestyle. Live rendered spec: `HEIMDALL Design Language.dc.html` (screenshots go alongside this file).

**Voice:** dark mission-control. Serious, dense, high-signal. Square corners, hairline borders, mono numerals, uppercase tracked labels. No gradients, no illustration, no emoji. Color is *state*, never decoration — a colored element is making a claim about risk or data provenance.

## 1. Color

Surfaces darkest→elevated: `--hm-bg-0` (page/map underlay) → `bg-1` (rails) → `bg-2` (cards) → `bg-3` (drawer/hover). `--hm-bg-inset` for meter tracks and inputs. Borders: `--hm-line-1` hairline everywhere; `--hm-line-2` only for active/focus/hover.

Text: `--hm-text-1` values & titles, `--hm-text-2` body, `--hm-text-3` labels/units/annotations.

**Risk states** (Corridor Risk Index bands — it is an index, never "probability"):
- `--hm-risk-low` #3FCF8E — index 0–39
- `--hm-risk-elev` #FFB224 — index 40–69
- `--hm-risk-high` #FF4E42 — index 70–100

**Signal:**
- `--hm-accent` #4CC3E8 — the ONLY interactive color: buttons, selection, links, focused controls, REPLAY mode, flow arcs.
- `--hm-alert` #FF2E63 — klaxon. Reserved for: cost-of-delay live counter, certificate FAIL, CLUSTER_TURN markers, critical alarms. If everything is alert, nothing is.

**Data-state:** `--hm-stale` grey — expired playbooks, DARK_GAP (doctrine: possible gap, never proof, hence grey not red). `--hm-sim` violet — synthetic/SIM-augmented data, always visibly flagged.

Every risk/signal color has a `-dim` (~12% alpha) for chip/card fills. Rule: dim fill + 40%-alpha border + full-strength text.

**Map layers:** tanker underway `--hm-tanker-underway`; LOITERING = elev amber; DARK_GAP = stale grey; CLUSTER_TURN = alert. Flow arcs `--hm-map-arc`; alternative routes `--hm-map-route-alt`, dashed, labelled "strategic planning estimates". Corridor halos = risk color at 12–20% with matching `--hm-glow-*`.

## 2. Typography

- UI: **IBM Plex Sans** (400/500/600). Data: **IBM Plex Mono** (400/500/600).
- **Every numeral is mono with `font-variant-numeric: tabular-nums`** (class `.hm-num`). No exceptions — scores, prices, timestamps, counts, percentages.
- Labels: 11px mono, 600, uppercase, tracking `.09em`, `--hm-text-3`.
- Badges: 10px mono, 600, tracking `.06em`.
- Scale (px/lh): 10/14 · 11/16 · 12/18 · 13/20 (body) · 15/22 · 18/26 · 22/28 · 28/34 (corridor index) · 40/44 · 64/64 (resilience hero, tracking −.02em).
- Timestamps always `YYYY-MM-DD HH:MM IST` or relative (`2m`, `4h 12m`), mono.

## 3. Spacing, radius, layout

4px grid: 2/4/8/12/16/20/24/32/40. Density defaults: card padding 12–16px, gap between cards 8px, rail gutter 16px, section gap 24px. Radius: 2px badges/bars, 4px cards/buttons, 6px drawer. Never larger.

Layout constants: right rail 360px, bottom rail 56px, drawer 440px (slides over map from right, `--hm-shadow-drawer`).

## 4. Components

**Card** — `bg-2`, 1px `line-1`, r-4px, padding 12px. Header row: title (15px sans 600) + data-age badge right-aligned. Hover: border `line-2`. Selected: border `line-2` + 2px inset accent edge on the left.

**Badge** — 10px mono caps, 2px 6px padding, r-2px, dim fill + 40% border + solid text. Variants: `DATA AGE 2m` (neutral; flips elev >15m, alert >60m) · `SRC EIA` provenance · `LIVE` (green, pulsing 6px dot, 1.2s) · `REPLAY` (accent) · `SIM` (violet) · `DEMO ASSUMPTION` (violet outline) · robustness `PASS n%` / `MARGINAL n%` / `FAIL n%` (low/elev/high colors) · `STALE` (grey) · `RECOMPUTING` (accent, pulsing).

**Corridor risk card** — corridor name + 28px index numeral in band color + trend arrow; confidence shown as separate mono value with 10-segment micro-bar (never merged with the index); 6-component breakdown mini-bars (news vol, tone, price vol, anomaly, baseline, sanctions); evidence expander row (`▸ EVIDENCE (n)`); footer: data-age + affected suppliers/refineries count.

**Resilience score** — 64px hero numeral colored by band + `/100` unit + 24h delta; 20-segment bar (filled segments in band color, empty `bg-inset`); breakdown always visible: 5 rows (supply coverage 35, playbook robustness 25, supplier diversity 15, response cost 15, freshness 10) each with weight, micro-bar, score.

**Cost-of-delay meter** — alert-colored 28–32px mono ticking value + `--hm-glow-alert` text-shadow, range line beneath (`range ₹a–₹b cr`), provenance badge. Ticks once per second.

**Countdown bar (playbook validity)** — 4px track `bg-inset`, fill = time remaining: low-green >40%, elev-amber 15–40%, high-red <15%; label `VALID 4H 12M` mono right. STALE: whole card drops to grey, reason line + `RECOMPUTING` badge.

**Buttons** — height 32px, r-4px, 11px mono caps tracked. Primary: accent-dim fill, accent border+text; hover full accent fill, `bg-0` text. Ghost: transparent, `line-1` border, `text-2`. Destructive: alert-dim/alert. Disabled: 40% opacity. Approve action is primary + `→` glyph.

**Sliders (scenario/assumptions)** — 4px track `bg-inset`, filled portion accent, 12px square thumb (r-2px) `text-1` fill with `line-2` border; current value in mono chip right of label.

**Segmented control (LIVE/REPLAY, speed ×1/×4/×16)** — `bg-inset` container r-4px, 2px padding; active segment `bg-3` + `line-2` border + `text-1`; inactive `text-3`.

**Timeline scrubber** — 6px track, played portion accent at 45%, 2px×16px playhead in accent + glow; event pips 4px squares above track in risk color; date labels 10px mono `text-3`.

**Drawer** — `bg-3`, `--hm-shadow-drawer`, header 18px + close ✕ ghost button, sections separated by `line-1` hairlines, footer action bar right-aligned (ghost + primary). Plan-comparison: 3 columns, recommended plan gets accent left-edge + `RECOMMENDED` badge; certificate block renders pass rate, worst-case shortfall, cost-at-risk, max delay, failure conditions, binding constraints, fallback.

## 5. Doctrine hooks (non-negotiable in UI)

- Every rendered number carries a data-age or provenance badge within its card.
- Degraded source → cached value + `DATA AGE` badge in elev/alert; never blank, never silently stale.
- "Probability" wording only for Monte Carlo outputs; the corridor number is always "Risk Index".
- Confidence is always displayed separately from the index.
- Specimen/demo values are labelled `DEMO ASSUMPTION`.
