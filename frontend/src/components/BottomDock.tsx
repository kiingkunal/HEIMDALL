import React from 'react';
import { api, CascadeValue, Playbook, ReplayBacktest, Scenario, Tagged, riskBand } from '../api';
import { Badge, Button, Label, MicroBar } from './primitives';
import { CorridorRisk } from '../state';
import { fmt, pct } from '../lib/format';
import { RISK_HEX } from '../lib/colors';

function Panel({ title, badge, children, width }: {
  title: string; badge?: React.ReactNode; children: React.ReactNode; width?: string;
}) {
  return (
    <section className="hm-dock-panel min-w-0 border-r border-line-1 last:border-r-0 flex flex-col" style={{ flex: width || 1 }}>
      <div className="hm-dock-panel-header">
        <Label className="hm-dock-panel-title">{title}</Label>
        {badge && <div className="hm-dock-panel-badge">{badge}</div>}
      </div>
      <div className="hm-dock-panel-body">{children}</div>
    </section>
  );
}

function TabButton({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return <button onClick={onClick} className={`h-6 px-2 border hm-num text-2xs rounded-sm ${active
    ? 'border-accent bg-accent text-bg-0' : 'border-line-1 text-text-3 hover:text-text-1'}`}>{children}</button>;
}

function SignalFeed({ mode, replayFrame }: { mode: 'LIVE' | 'REPLAY'; replayFrame: Tagged<any> | null }) {
  const [tab, setTab] = React.useState<'news' | 'ais'>('news');
  const [news, setNews] = React.useState<any>(null);
  const [anomalies, setAnomalies] = React.useState<any>(null);

  React.useEffect(() => {
    const load = () => Promise.all([
      fetch('/api/headlines').then((r) => r.json()),
      api.latest('anomalies'),
    ]).then(([n, a]) => {
      setNews(n);
      setAnomalies(a.items.find((i) => i.key === 'latest')?.payload || null);
    }).catch(() => {});
    load();
    const timer = setInterval(load, 120000);
    return () => clearInterval(timer);
  }, []);

  const replayEvidence: any[] = replayFrame?.value?.visible_evidence || [];
  const articles: any[] = mode === 'REPLAY'
    ? replayEvidence.map((e) => ({ title: e.headline, domain: e.source, seendate: e.timestamp,
        url: e.source_url, replay: true }))
    : news?.value?.articles || [];
  const events: any[] = anomalies?.value?.anomalies || [];
  const live = news?.provenance?.kind === 'live';
  return (
    <Panel title="SIGNAL FEED" width="1.1" badge={mode === 'REPLAY'
      ? <Badge tone="replay">LEAKAGE-GUARDED REPLAY</Badge>
      : <Badge tone={live ? 'live' : 'stale'} dot={live}>{live ? 'LIVE SOURCES' : 'CACHE'}</Badge>}>
      <div className="flex items-center gap-1 p-2 border-b border-line-1 bg-bg-1 sticky top-0 z-[1]">
        <TabButton active={tab === 'news'} onClick={() => setTab('news')}>{mode === 'REPLAY' ? 'VISIBLE EVIDENCE' : 'GDELT NEWS'} {articles.length}</TabButton>
        <TabButton active={tab === 'ais'} onClick={() => setTab('ais')}>{mode === 'REPLAY' ? 'AIS FIXTURE' : 'AIS ANOMALIES'} {mode === 'REPLAY' ? 0 : events.length}</TabButton>
        <div className="flex-1" />
        <span className="hm-num text-[9px] text-text-3">AUTO REFRESH · 120S</span>
      </div>
      <div className="px-2">
        {tab === 'news' ? (
          articles.length ? articles.slice(0, 7).map((a, i) => (
            <a key={i} href={a.url || undefined} target={a.url ? '_blank' : undefined} rel={a.url ? 'noreferrer' : undefined}
              className="grid grid-cols-[18px_1fr_auto] gap-2 items-start border-b border-line-1 py-1.5 hover:bg-bg-3 px-1 -mx-1">
              <span className={`hm-num text-2xs ${i < 2 ? 'text-alert' : 'text-text-3'}`}>{String(i + 1).padStart(2, '0')}</span>
              <span className="text-xs text-text-1 leading-4 line-clamp-2">{a.title}</span>
              <span className="hm-num text-[9px] text-accent max-w-24 truncate">{mode === 'REPLAY' ? a.seendate?.slice(5, 16).replace('T', ' ') : a.domain}</span>
            </a>
          )) : <Empty text="Awaiting the GDELT monitoring lane." />
        ) : (
          mode === 'REPLAY' ? <Empty text="No replay AIS fixture loaded. AIS is not inferred from news." /> : events.length ? events.slice(0, 8).map((a, i) => (
            <div key={i} className="grid grid-cols-[10px_92px_1fr_auto] gap-2 items-center border-b border-line-1 py-1.5">
              <span className={`w-2 h-2 rounded-full ${a.type === 'CLUSTER_TURN' ? 'bg-alert shadow-glow-alert' : a.type === 'LOITERING' ? 'bg-risk-elev' : 'bg-stale'}`} />
              <span className="hm-num text-2xs text-text-1">{a.type.replace('_', ' ')}</span>
              <span className="hm-num text-2xs text-text-3 capitalize">{a.corridor?.replace(/_/g, ' ') || '—'}</span>
              <span className="hm-num text-2xs text-text-2">{a.vessel_count ? `${a.vessel_count} VESSELS` : '1 VESSEL'}</span>
            </div>
          )) : <Empty text="No AIS anomalies in the latest snapshot." />
        )}
      </div>
    </Panel>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="h-24 grid place-items-center hm-num text-2xs text-text-3">{text}</div>;
}

function Stat({ label, value, unit, tone }: { label: string; value: string; unit: string; tone?: 'alert' | 'elev' | 'normal' }) {
  return (
    <div className="bg-bg-inset border border-line-1 p-2.5 rounded min-w-0">
      <div className="hm-label !text-[9px] !text-text-2 truncate">{label}</div>
      <div className={`hm-num text-lg leading-6 font-bold mt-1 whitespace-nowrap ${tone === 'alert' ? 'text-alert' : tone === 'elev' ? 'text-risk-elev' : 'text-text-1'}`}>{value}</div>
      <div className="hm-num text-[9px] text-text-2 mt-0.5 whitespace-nowrap">{unit}</div>
    </div>
  );
}

function CascadeDesk({ risks, routes, scenario }: {
  risks: CorridorRisk[]; routes: Record<string, any>; scenario: Scenario;
}) {
  const top = [...risks].sort((a, b) => b.tagged.value.index - a.tagged.value.index)[0];
  const [cascade, setCascade] = React.useState<Tagged<CascadeValue> | null>(null);
  React.useEffect(() => {
    if (!top) return;
    const state = scenario.corridor_states?.[top.id];
    const severity = state === 'closed' ? 1 : state === 'restricted'
      ? scenario.restrict_severity ?? .5 : Math.max(0.3, top.tagged.value.index / 100);
    api.cascade(top.id, severity, scenario.duration_days ?? 14).then(setCascade).catch(() => {});
  }, [top?.id, top?.tagged.value.index, scenario]);
  const alternatives = Object.values(routes).filter((r: any) => !r.error && !r.corridors?.includes(top?.id))
    .sort((a: any, b: any) => a.freight_usd_bbl - b.freight_usd_bbl).slice(0, 4) as any[];
  const scenarioState = top ? scenario.corridor_states?.[top.id] : undefined;
  const displayedSeverity = top ? (scenarioState === 'closed' ? 1 : scenarioState === 'restricted'
    ? scenario.restrict_severity ?? .5 : Math.max(.3, top.tagged.value.index / 100)) : 0;
  const duration = scenario.duration_days ?? 14;

  return (
    <Panel title="INDIA CASCADE TWIN" width="1" badge={<Badge tone="accent">DETERMINISTIC</Badge>}>
      {!cascade || !top ? <Empty text="Computing operational consequences…" /> : (
        <div className="p-3">
          <div className="flex items-center gap-2 mb-2.5 min-w-0">
            <span className="hm-num text-2xs text-text-3">SCENARIO</span>
            <span className="hm-num text-2xs text-text-1">{top.id.replace(/_/g, ' ').toUpperCase()} · {Math.round(displayedSeverity * 100)}% · {duration}D</span>
            <Badge tone={riskBand(top.tagged.value.index) === 'high' ? 'fail' : 'marginal'}>INDEX {top.tagged.value.index.toFixed(0)}</Badge>
          </div>
          {cascade.value.refinery_impacts?.[0] && <div className="mb-2.5 px-2.5 py-1.5 border-l-2 border-risk-elev bg-risk-elev-dim flex justify-between gap-3 hm-num text-[9px] min-w-0">
            <span className="text-text-2 truncate">TOP MODELED REFINERY HIT · {cascade.value.refinery_impacts[0].name.toUpperCase()}</span>
            <span className="text-risk-elev shrink-0">−{fmt(cascade.value.refinery_impacts[0].run_rate_impact_mb_d, 3)} MB/D · {fmt(cascade.value.refinery_impacts[0].run_rate_impact_pct, 1)}%</span>
          </div>}
          <div className="grid grid-cols-5 gap-2">
            <Stat label="DAILY DEFICIT" value={fmt(cascade.value.deficit_mb_d, 2)} unit="MB/D" tone="alert" />
            <Stat label="SUPPLY GAP" value={fmt(cascade.value.deficit_pct, 1)} unit="PERCENT" tone="alert" />
            <Stat label="BUFFER COVER" value={fmt(cascade.value.inventory_days_remaining, 0)} unit="DAYS" />
            <Stat label="LANDED PRESSURE" value={`+$${fmt(cascade.value.landed_cost_pressure_usd_bbl, 1)}`} unit="USD/BBL" tone="elev" />
            <Stat label="NET SHORTFALL" value={fmt(cascade.value.net_shortfall_mb, 1)} unit="MILLION BBL" />
          </div>
          <div className="mt-2 border border-line-1 rounded-sm overflow-hidden">
            <div className="h-8 px-2.5 flex items-center justify-between gap-3 bg-bg-2 border-b border-line-1">
              <Label className="!text-[9px]">LOWEST-FREIGHT LANES OUTSIDE LEAD CORRIDOR</Label>
              <span className="hm-num text-[9px] text-text-3">SEAROUTE · PLANNING ESTIMATE</span>
            </div>
            <div className="hm-route-grid grid grid-cols-4 divide-x divide-line-1">
              {alternatives.map((r: any) => (
                <div key={r.supplier_id} className="hm-route-cell">
                  <div className="hm-num text-2xs text-text-1 uppercase truncate">{r.supplier_id.replace(/_/g, ' ')}</div>
                  <div className="hm-route-meta">
                    <span>{(r.distance_km / 1000).toFixed(1)}K KM</span>
                    <span>${fmt(r.freight_usd_bbl, 1)}/BBL</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}

function ResponseDesk({ playbook, mode, replayFrame, onOpen }: {
  playbook: Playbook | null; mode: 'LIVE' | 'REPLAY'; replayFrame: Tagged<any> | null; onOpen: () => void;
}) {
  const [brief, setBrief] = React.useState<any>(null);
  const [proof, setProof] = React.useState<Tagged<ReplayBacktest> | null>(null);
  React.useEffect(() => {
    if (mode === 'LIVE') fetch('/api/brief').then((r) => r.json()).then((d) => setBrief(d.value)).catch(() => {});
    if (mode === 'REPLAY') api.replayBacktest().then(setProof).catch(() => setProof(null));
  }, [mode]);
  const cert = playbook ? playbook.certificates[playbook.recommended] : null;
  const plan = playbook ? playbook.plans[playbook.recommended] : null;

  return (
    <Panel title="AI + RESPONSE CELL" width=".92" badge={mode === 'REPLAY'
      ? <Badge tone="replay">REPLAY FRAME</Badge>
      : <Badge tone={cert ? 'pass' : 'recomputing'}>{cert ? `CERTIFIED ${pct(cert.robustness_pass_rate)}` : 'PRECOMPUTING'}</Badge>}>
      <div className="p-2.5 space-y-2">
        {mode === 'REPLAY' ? <div className="border-l-2 border-accent bg-bg-2 px-2.5 py-1.5">
          <div className="flex items-center justify-between mb-1">
            <Label className="!text-accent">◈ HEIMDALL BRIEF</Label>
            <span className="hm-num text-[9px] text-text-3">STRAIT OF HORMUZ</span>
          </div>
          {replayFrame?.value?.latest_evidence ? <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs text-text-1 truncate flex-1">{replayFrame.value.latest_evidence.headline}</span>
            <span className="hm-num text-[8px] text-accent shrink-0">SOURCED · LEAKAGE GUARDED</span>
          </div> : <div className="hm-num text-2xs text-text-3">Move the simulation clock to reveal sourced evidence.</div>}
        </div> : <div className="border-l-2 border-accent bg-bg-2 p-2.5">
          <div className="flex items-center justify-between mb-1">
            <Label className="!text-accent">◈ HEIMDALL BRIEF</Label>
            {brief && <span className="hm-num text-[9px] text-text-3">{brief.corridor_name?.toUpperCase()}</span>}
          </div>
          {brief?.narrative ? <>
            <div className="text-sm text-text-1 leading-5">{brief.narrative.headline}</div>
            <div className="text-[11px] text-text-2 leading-4 mt-1 line-clamp-2">{brief.narrative.summary}</div>
          </> : <div className="hm-num text-2xs text-text-3">Narrative unavailable. Engine outputs remain active.</div>}
        </div>}

        {mode === 'REPLAY' ? (proof ? <HistoricalProof proof={proof.value} />
          : <Empty text="Loading locked historical proof…" />) : playbook && plan && cert ? (
          <div className="border border-line-1 rounded-sm overflow-hidden">
            <div className="px-2.5 h-8 flex items-center justify-between bg-bg-2 border-b border-line-1">
              <span className="hm-num text-xs text-text-1 font-bold">{plan.label.toUpperCase()}</span>
              <Badge tone={cert.recommended ? 'pass' : 'marginal'}>{cert.recommended ? 'RECOMMENDED' : 'FALLBACK'}</Badge>
            </div>
            <div className="grid grid-cols-3 divide-x divide-line-1 p-2">
              <div><div className="hm-label !text-[9px]">LANDED</div><div className="hm-num text-sm text-text-1">${fmt(plan.avg_landed_usd_bbl)}</div></div>
              <div className="pl-2"><div className="hm-label !text-[9px]">ROBUSTNESS</div><div className="hm-num text-sm text-risk-low">{pct(cert.robustness_pass_rate)}</div></div>
              <div className="pl-2"><div className="hm-label !text-[9px]">MAX DELAY</div><div className="hm-num text-sm text-text-1">{fmt(cert.max_delay_days, 1)}D</div></div>
            </div>
            <div className="px-2 pb-2">
              <MicroBar frac={cert.robustness_pass_rate} tone={cert.robustness_pass_rate >= .8 ? 'low' : 'elev'} />
              <Button variant="primary" arrow onClick={onOpen} className="w-full justify-center mt-2">OPEN DECISION WORKSPACE</Button>
            </div>
          </div>
        ) : <Empty text="Solving and certifying three response plans…" />}
      </div>
    </Panel>
  );
}

function HistoricalProof({ proof }: { proof: ReplayBacktest }) {
  const m = proof.metrics;
  const lead = m.detection_lead;
  return <div className="border border-line-1 rounded-sm overflow-hidden">
    <div className="h-7 px-2 flex items-center justify-between bg-bg-2 border-b border-line-1">
      <Label className="!text-[9px]">HISTORICAL PROOF · LOCKED RUN</Label>
      <Badge tone={m.hard_constraint_violations === 0 ? 'pass' : 'fail'}>
        {m.hard_constraint_violations} CONSTRAINT VIOLATIONS
      </Badge>
    </div>
    <div className="grid grid-cols-4 divide-x divide-line-1">
      <div className="p-2"><div className="hm-label !text-[8px]">DETECTION LEAD</div><div className="hm-num text-sm text-text-1">{lead.calendar_days_point}D</div><div className="hm-num text-[8px] text-text-3">{lead.calendar_days_range[0]}–{lead.calendar_days_range[1]}D BAND</div></div>
      <div className="p-2"><div className="hm-label !text-[8px]">PREMIUM AVOIDED*</div><div className="hm-num text-sm text-risk-low">${fmt(m.counterfactual_premium_avoided_musd, 1)}M</div><div className="hm-num text-[8px] text-text-3">COUNTERFACTUAL</div></div>
      <div className="p-2"><div className="hm-label !text-[8px]">ENGINE TIME</div><div className="hm-num text-sm text-accent">{fmt(m.signal_to_certified_plan_seconds, 2)}S</div><div className="hm-num text-[8px] text-text-3">3 PLANS + CERTS</div></div>
      <div className="p-2"><div className="hm-label !text-[8px]">SHORTAGE DAYS</div><div className="hm-num text-sm text-text-1">{fmt(m.shortage_days_avoided, 0)}</div><div className="hm-num text-[8px] text-text-3">BUFFERS COVER 14D</div></div>
    </div>
    <div className="px-2 py-1 border-t border-line-1 flex items-center justify-between hm-num text-[8px] text-text-3">
      <span>*EIA DELTA × MODELED PURCHASES × 14D · NOT BOOKED SAVINGS</span>
      <a href={proof.alert.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">SOURCE ↗</a>
    </div>
  </div>;
}

export function BottomDock({ risks, routes, playbook, scenario, mode, replayFrame, onOpenPlaybook }: {
  risks: CorridorRisk[]; routes: Record<string, any>; playbook: Playbook | null;
  scenario: Scenario;
  mode: 'LIVE' | 'REPLAY'; replayFrame: Tagged<any> | null; onOpenPlaybook: () => void;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  return (
    <div className="hm-intel-dock shrink-0 bg-bg-1 border-t border-line-1 flex flex-col overflow-hidden"
      style={{ height: collapsed ? 34 : 276 }}>
      <button onClick={() => setCollapsed(!collapsed)}
        className="h-[34px] shrink-0 w-full flex items-center px-4 border-b border-line-1 bg-bg-0 hover:bg-bg-2">
        <span className="hm-label !text-text-1">INTELLIGENCE & DECISION DOCK</span>
        <span className="ml-3 hm-num text-[9px] text-text-3">LIVE SIGNALS → ENGINE CONSEQUENCES → CERTIFIED RESPONSE</span>
        <span className="flex-1" />
        <span className="hm-num text-2xs text-text-3">{collapsed ? 'EXPAND ▴' : 'COLLAPSE ▾'}</span>
      </button>
      {!collapsed && <div className="flex-1 flex min-h-0"><SignalFeed mode={mode} replayFrame={replayFrame} /><CascadeDesk risks={risks} routes={routes} scenario={scenario} /><ResponseDesk playbook={playbook} mode={mode} replayFrame={replayFrame} onOpen={onOpenPlaybook} /></div>}
    </div>
  );
}
