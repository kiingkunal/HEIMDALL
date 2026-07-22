import React from 'react';
import { api, Certificate, Plan, Playbook, Scenario, ScenarioOptions } from '../api';
import { Badge, Button, DataAge, Label, MicroBar } from './primitives';
import { fmt, pct } from '../lib/format';
import { RISK_HEX } from '../lib/colors';

const FALLBACK_CORRIDORS = ['hormuz', 'bab_el_mandeb', 'suez', 'malacca'];
const STATES = ['open', 'restricted', 'closed'] as const;
const PRESETS = ['cost_first', 'balanced', 'security_first'];

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return <div className="hm-metric min-w-0">
    <div className="hm-label !text-[9px] !text-text-2">{label}</div>
    <div className={`hm-num text-sm leading-5 mt-1 break-words ${accent ? 'text-accent' : 'text-text-1'}`}>{value}</div>
  </div>;
}

function SectionHeader({ title, subtitle, badge }: { title: string; subtitle?: string; badge?: React.ReactNode }) {
  return <div className="hm-section-header">
    <div className="min-w-0"><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>{badge}
  </div>;
}

function ScenarioControl({ label, value, min, max, unit, signed, onChange }: {
  label: string; value: number; min: number; max: number; unit: string; signed?: boolean;
  onChange: (value: number) => void;
}) {
  const id = `scenario-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  const progress = max === min ? 0 : ((value - min) / (max - min)) * 100;
  return <div className="hm-control-card">
    <div className="flex items-center justify-between gap-3 mb-3">
      <label htmlFor={id} className="hm-label !text-[9px] !text-text-2">{label}</label>
      <output htmlFor={id} className="hm-control-value">
        {signed && value > 0 ? '+' : ''}{value}<span>{unit}</span>
      </output>
    </div>
    <input id={id} name={id} aria-label={label} type="range" min={min} max={max} step={1} value={value}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-full hm-slider" style={{ '--hm-range': `${progress}%` } as React.CSSProperties} />
    <div className="flex justify-between hm-num text-[9px] text-text-2 mt-2"><span>{min}</span><span>{max}</span></div>
  </div>;
}

function ScenarioLab({ scenario, solving, onRun }: {
  scenario: Scenario; solving: boolean; onRun: (value: Scenario) => void;
}) {
  const [draft, setDraft] = React.useState<Scenario>(scenario);
  const [options, setOptions] = React.useState<ScenarioOptions | null>(null);
  React.useEffect(() => setDraft(scenario), [scenario]);
  React.useEffect(() => { api.scenarioOptions().then((response) => setOptions(response.value)).catch(() => {}); }, []);
  const states = draft.corridor_states || {};
  const changed = JSON.stringify(draft) !== JSON.stringify(scenario);
  const corridors = options?.corridors || FALLBACK_CORRIDORS.map((id) => ({ id, name: id.replace(/_/g, ' ') }));
  const control = (key: string, fallback: number) => options?.controls[key] ?? fallback;
  const setState = (corridor: string, state: string) => {
    const next = { ...states };
    if (state === 'open') delete next[corridor]; else next[corridor] = state;
    setDraft({ ...draft, corridor_states: next });
  };
  const setOne = (key: 'unavailable_suppliers' | 'disabled_refineries', value: string) =>
    setDraft({ ...draft, [key]: value ? [value] : [] });
  const severity = Math.round((draft.restrict_severity ?? .5) * 100);

  return <div className="space-y-5">
    <section className="hm-drawer-section">
      <SectionHeader title="Corridor Assumptions" subtitle="Choose the physical state for each maritime corridor."
        badge={<Badge tone={changed ? 'elev' : 'neutral'}>{changed ? 'CHANGES STAGED' : 'BASELINE'}</Badge>} />
      <div className="divide-y divide-line-1">
        {corridors.map((corridor) => <div key={corridor.id} className="hm-corridor-control">
          <div className="min-w-0"><h4>{corridor.name}</h4><p>Maritime corridor state</p></div>
          <div className="hm-state-control" aria-label={`${corridor.name} state`}>
            {STATES.map((state) => {
              const active = (states[corridor.id] || 'open') === state;
              return <button key={state} onClick={() => setState(corridor.id, state)}
                className={`${active ? `is-active is-${state}` : ''}`} aria-pressed={active}>{state}</button>;
            })}
          </div>
        </div>)}
      </div>
    </section>

    <section className="hm-drawer-section">
      <SectionHeader title="Cascade Horizon & Market Stress"
        subtitle="Every control enters the solver or certificate calculation."
        badge={<Badge tone="accent">CONFIG BOUNDED</Badge>} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 p-3">
        <ScenarioControl label="Disruption Duration" value={draft.duration_days ?? control('default_duration_days', 14)}
          min={control('min_duration_days', 1)} max={control('max_duration_days', 60)} unit="days"
          onChange={(value) => setDraft({ ...draft, duration_days: value })} />
        <ScenarioControl label="Brent Price Shock" value={draft.price_shock_usd_bbl ?? control('default_price_shock_usd_bbl', 0)}
          min={control('min_price_shock_usd_bbl', -20)} max={control('max_price_shock_usd_bbl', 80)} unit="$/bbl" signed
          onChange={(value) => setDraft({ ...draft, price_shock_usd_bbl: value })} />
        <ScenarioControl label="Demand Change" value={draft.demand_change_pct ?? control('default_demand_change_pct', 0)}
          min={control('min_demand_change_pct', -15)} max={control('max_demand_change_pct', 20)} unit="%" signed
          onChange={(value) => setDraft({ ...draft, demand_change_pct: value })} />
        <ScenarioControl label="Tanker Availability" value={draft.vessel_availability_pct ?? control('default_vessel_availability_pct', 100)}
          min={control('min_vessel_availability_pct', 20)} max={control('max_vessel_availability_pct', 100)} unit="%"
          onChange={(value) => setDraft({ ...draft, vessel_availability_pct: value })} />
        <ScenarioControl label="Port Congestion" value={draft.port_congestion_pct ?? control('default_port_congestion_pct', 0)}
          min={control('min_port_congestion_pct', 0)} max={control('max_port_congestion_pct', 80)} unit="%"
          onChange={(value) => setDraft({ ...draft, port_congestion_pct: value })} />
        <div className="hm-control-card grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="min-w-0"><span className="hm-label !text-[9px] !text-text-2 block mb-2">Supplier Failure</span>
            <select name="supplier-failure" autoComplete="off" value={draft.unavailable_suppliers?.[0] || ''}
              onChange={(event) => setOne('unavailable_suppliers', event.target.value)} className="hm-select w-full">
              <option value="">None</option>{options?.suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
            </select></label>
          <label className="min-w-0"><span className="hm-label !text-[9px] !text-text-2 block mb-2">Refinery Outage</span>
            <select name="refinery-outage" autoComplete="off" value={draft.disabled_refineries?.[0] || ''}
              onChange={(event) => setOne('disabled_refineries', event.target.value)} className="hm-select w-full">
              <option value="">None</option>{options?.refineries.map((refinery) => <option key={refinery.id} value={refinery.id}>{refinery.name}</option>)}
            </select></label>
          <p className="sm:col-span-2 hm-num text-[9px] text-text-2">Outages are hard constraints. Sanctioned options remain excluded.</p>
        </div>
      </div>
    </section>

    <section className="hm-drawer-section p-4">
      <div className="flex items-end justify-between gap-4 mb-4">
        <div><h3 className="hm-drawer-card-title">Restriction Severity</h3><p className="hm-drawer-card-copy">Applied only to corridors marked Restricted.</p></div>
        <div className="hm-num text-3xl font-bold text-risk-elev">{severity}<span className="text-sm ml-1">%</span></div>
      </div>
      <input aria-label="Restriction severity" type="range" min={0} max={100} value={severity}
        onChange={(event) => setDraft({ ...draft, restrict_severity: Number(event.target.value) / 100 })}
        className="w-full hm-slider" style={{ '--hm-range': `${severity}%` } as React.CSSProperties} />
      <div className="flex justify-between hm-num text-[9px] text-text-2 mt-2"><span>0% · Open</span><span>50% · Half Flow</span><span>100% · Closed</span></div>
    </section>

    <div className="hm-run-strip">
      <div className="min-w-0"><h3>Generate 3 feasible response plans</h3><p>Cost-First, Balanced & Security-First are solved once, then stress-tested.</p></div>
      <Button variant="primary" arrow disabled={solving} onClick={() => onRun(draft)}>
        {solving ? 'SOLVING & CERTIFYING…' : 'RUN RESPONSE ENGINE'}
      </Button>
    </div>
  </div>;
}

function PlanSummary({ plan, cert, selected, recommended, onClick }: {
  plan: Plan; cert: Certificate; selected: boolean; recommended: boolean; onClick: () => void;
}) {
  const pass = cert.robustness_pass_rate >= .8;
  const marginal = cert.robustness_pass_rate >= .6;
  const tone = pass ? 'pass' : marginal ? 'marginal' : 'fail';
  return <button onClick={onClick} className={`hm-plan-summary ${selected ? 'is-selected' : ''}`}>
    <div className="flex items-start justify-between gap-3 min-w-0">
      <div className="min-w-0"><h3>{plan.label}</h3><p>{plan.status}</p></div>
      <Badge tone={tone}>{pass ? 'PASS' : marginal ? 'MARGINAL' : 'FAIL'} {pct(cert.robustness_pass_rate)}</Badge>
    </div>
    <div className="grid grid-cols-3 gap-2 mt-4">
      <Metric label="Landed" value={`$${fmt(plan.avg_landed_usd_bbl)}`} />
      <Metric label="Shortage" value={`${fmt(plan.total_shortage_mb_d, 2)}`} />
      <Metric label="Max Delay" value={`${fmt(cert.max_delay_days, 1)}d`} />
    </div>
    <div className="mt-3"><MicroBar frac={cert.robustness_pass_rate} tone={pass ? 'low' : marginal ? 'elev' : 'high'} /></div>
    {recommended && <div className="hm-num text-[9px] text-accent mt-3">◆ Recommended by certificate engine</div>}
  </button>;
}

function PlanDetail({ plan, cert, recommended, onApprove }: {
  plan: Plan; cert: Certificate; recommended: boolean; onApprove: () => void;
}) {
  const suppliers = Object.entries(plan.supplier_mix).sort((a, b) => b[1] - a[1]);
  const maxSupplier = Math.max(...suppliers.map(([, volume]) => volume), 1);
  return <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
    <section className="hm-drawer-section">
      <SectionHeader title={`${plan.label} Allocation`} badge={recommended && <Badge tone="accent">RECOMMENDED</Badge>} />
      <div className="p-4 space-y-3">
        {suppliers.map(([supplier, volume]) => <div key={supplier} className="grid grid-cols-[120px_1fr_72px] items-center gap-3 min-w-0">
          <span className="hm-num text-[10px] text-text-2 capitalize truncate">{supplier.replace(/_/g, ' ')}</span>
          <MicroBar frac={volume / maxSupplier} tone="accent" />
          <span className="hm-num text-[10px] text-text-1 text-right whitespace-nowrap">{fmt(volume, 2)} mb/d</span>
        </div>)}
        <div className="grid grid-cols-2 gap-3 border-t border-line-1 pt-4 mt-4">
          <Metric label="Demand Served" value={`${fmt(plan.served_mb_d, 2)} mb/d`} />
          <Metric label="Commercial Use" value={`${fmt(plan.commercial_use_mb_d, 2)} mb/d`} />
          <Metric label="Planning Horizon" value={`${fmt(plan.planning_horizon_days, 0)} days`} />
          <Metric label="Latest Arrival" value={`${fmt(Math.max(...plan.purchases.map((purchase) => purchase.arrival_day || 0), 0), 1)} days`} />
        </div>
      </div>
    </section>
    <section className="hm-drawer-section">
      <SectionHeader title="Robustness Certificate" badge={<Badge tone="accent">MC TESTED</Badge>} />
      <div className="p-4">
        <div className="grid grid-cols-2 gap-4">
          <Metric label="Pass Rate" value={pct(cert.robustness_pass_rate)} accent />
          <Metric label="95% Interval" value={`${pct(cert.confidence_interval[0])}–${pct(cert.confidence_interval[1])}`} />
          <Metric label="Worst Shortfall" value={`${fmt(cert.worst_case_shortfall_mb_d, 2)} mb/d`} />
          <Metric label="Cost at Risk" value={`$${fmt(cert.cost_at_risk_usd_bbl)}/bbl`} />
        </div>
        <div className="border-t border-line-1 mt-4 pt-4"><Label className="!text-[9px] !text-text-2 mb-2">Binding Constraints</Label>
          {cert.binding_constraints.length ? cert.binding_constraints.map((item, index) => <div key={index} className="text-[11px] leading-5 text-text-2">• {item}</div>) : <div className="text-[11px] text-text-2">No reported binding constraints.</div>}
        </div>
        {cert.rejected_reason && <div className="mt-3 text-[11px] leading-5 text-risk-elev border border-risk-elev bg-risk-elev-dim p-3 rounded">{cert.rejected_reason}</div>}
        <Button variant={recommended ? 'primary' : 'ghost'} arrow onClick={onApprove} className="w-full justify-center mt-4">ASSEMBLE ACTION PACKET</Button>
      </div>
    </section>
  </div>;
}

function PlanWorkspace({ playbook, onApprove }: { playbook: Playbook | null; onApprove: (preset: string) => void }) {
  const [selected, setSelected] = React.useState('balanced');
  React.useEffect(() => { if (playbook?.recommended) setSelected(playbook.recommended); }, [playbook?.id]);
  if (!playbook) return <div className="h-64 grid place-items-center"><div className="hm-num text-xs text-accent animate-pulse">PRECOMPUTING 3 PLANS & CERTIFICATES…</div></div>;
  const preset = playbook.plans[selected] ? selected : playbook.recommended;
  return <div className="space-y-4">
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
      {PRESETS.filter((name) => playbook.plans[name]).map((name) => <PlanSummary key={name} plan={playbook.plans[name]} cert={playbook.certificates[name]}
        selected={name === preset} recommended={name === playbook.recommended} onClick={() => setSelected(name)} />)}
    </div>
    <PlanDetail plan={playbook.plans[preset]} cert={playbook.certificates[preset]}
      recommended={preset === playbook.recommended} onApprove={() => onApprove(preset)} />
    <section className="hm-drawer-section">
      <SectionHeader title="Pre-Crisis No-Regret Actions" subtitle="Reversible options available before disruption." />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 p-3">
        {playbook.no_regret_actions.map((action, index) => <div key={index} className="hm-option-card"><span>{index + 1}</span><h4>{action.action}</h4><p>{action.option_value}</p></div>)}
      </div>
    </section>
  </div>;
}

function PacketView({ packet, onBack }: { packet: any; onBack: () => void }) {
  const download = () => {
    const blob = new Blob([JSON.stringify(packet, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = `${packet.packet_id}.json`; link.click();
    URL.revokeObjectURL(url);
  };
  return <div className="space-y-4">
    <div className="hm-authorisation-banner">
      <div><h3>Human Authorisation Required</h3><p>{packet.disclaimer}</p></div>
      <Badge tone="elev">AWAITING APPROVAL</Badge>
    </div>
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
      <div className="hm-summary-tile"><Metric label="Packet ID" value={packet.packet_id} /></div>
      <div className="hm-summary-tile"><Metric label="Plan" value={packet.plan_label} /></div>
      <div className="hm-summary-tile"><Metric label="Avg Landed" value={`$${fmt(packet.avg_landed_usd_bbl)}/bbl`} /></div>
      <div className="hm-summary-tile"><Metric label="Shortage" value={`${fmt(packet.total_shortage_mb_d)} mb/d`} /></div>
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-[1.25fr_.75fr] gap-4">
      <section className="hm-drawer-section">
        <SectionHeader title="Procurement Quantities" subtitle={`${packet.procurement_quantities.length} supplier-to-refinery allocations`} />
        <div className="hm-procurement-table">
          <div className="hm-procurement-head"><span>Supplier & Refinery</span><span>ETA</span><span>Volume</span></div>
          {packet.procurement_quantities.map((purchase: any, index: number) => <div key={index} className="hm-procurement-row">
            <div><strong>{purchase.supplier_id.replace(/_/g, ' ')}</strong><span>→ {purchase.refinery_id.replace(/_/g, ' ')}</span></div>
            <span className="text-accent">{fmt(purchase.arrival_day, 1)} days</span>
            <span>{fmt(purchase.volume_mb_d, 3)} mb/d</span>
          </div>)}
        </div>
      </section>
      <div className="space-y-4">
        <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Approval Checklist</h3>
          <div className="mt-3 space-y-3">{packet.approval_requirements.map((item: string, index: number) => <label key={index} className="hm-check-row"><input type="checkbox" /><span>{item}</span></label>)}</div>
        </section>
        <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Operational Timeline</h3>
          <div className="mt-3 space-y-3">{packet.operational_timeline.map((item: any, index: number) => <div key={index} className="hm-timeline-row"><span>T+{item.t_plus_days}d</span><p>{item.milestone}</p></div>)}</div>
        </section>
      </div>
    </div>
    <div className="flex flex-wrap gap-2"><Button variant="primary" onClick={download}>DOWNLOAD JSON</Button><Button variant="ghost" onClick={() => window.print()}>PRINT / SAVE PDF</Button><Button variant="ghost" onClick={onBack}>← BACK TO CERTIFICATES</Button></div>
  </div>;
}

function EvidenceView({ corridor }: { corridor: string }) {
  const [evidence, setEvidence] = React.useState<any>(null);
  React.useEffect(() => { setEvidence(null); api.evidence(corridor, true).then((response) => setEvidence(response.value)).catch(() => setEvidence({ error: true })); }, [corridor]);
  if (!evidence) return <div className="h-64 grid place-items-center hm-num text-xs text-accent animate-pulse">ASSEMBLING EVIDENCE LEDGER…</div>;
  if (evidence.error) return <div className="text-xs text-alert">Evidence is unavailable. Close this panel and retry.</div>;
  const band = evidence.risk_index < 40 ? 'low' : evidence.risk_index < 70 ? 'elev' : 'high';
  return <div className="space-y-4">
    <div className="grid grid-cols-2 gap-3">
      <div className="hm-evidence-score"><Label>Risk Index</Label><strong style={{ color: RISK_HEX[band] }}>{fmt(evidence.risk_index, 1)}</strong><p>0–100 evidence fusion · not a probability</p></div>
      <div className="hm-evidence-score"><Label>Confidence</Label><strong>{pct(evidence.confidence)}</strong><p>Separate evidence-quality score</p></div>
      <div className="hm-evidence-narrative col-span-2"><Label className="!text-accent">Evidence Interpretation</Label><h3>{evidence.narrative?.headline || 'Narrative unavailable.'}</h3><p>{evidence.narrative?.summary}</p><div>Watch: {evidence.narrative?.recommended_watch || 'engine signals'}</div></div>
    </div>

    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Risk Component Breakdown</h3>
        <div className="mt-4 space-y-3">{evidence.components.map((component: any) => <div key={component.component} className="grid grid-cols-[120px_1fr_48px] gap-3 items-center min-w-0">
          <span className="hm-num text-[10px] text-text-2 capitalize truncate">{component.component.replace(/_/g, ' ')}</span><MicroBar frac={component.normalized || 0} tone={component.present ? 'accent' : 'sim'} /><span className="hm-num text-[10px] text-text-1 text-right">{fmt(component.contribution, 1)}</span>
        </div>)}</div>
        {evidence.contradictions.length > 0 && <div className="mt-4 border border-risk-elev bg-risk-elev-dim rounded p-3 text-[11px] leading-5 text-risk-elev"><strong>Contradictory evidence:</strong> {evidence.contradictions.join(' · ')}</div>}
      </section>
      <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Freshness & Provenance</h3>
        <div className="mt-3">{Object.entries(evidence.freshness).map(([signal, freshness]: [string, any]) => <div key={signal} className="hm-freshness-row"><div><strong>{signal}</strong><span>{freshness.source}</span></div><DataAge hours={freshness.age_hours} /></div>)}</div>
        <div className="mt-4"><Label className="!text-[9px] !text-text-2 mb-2">Source Ledger</Label>{evidence.evidence_links.map((link: any, index: number) => link.url ? <a key={index} href={link.url} target="_blank" rel="noreferrer" className="hm-source-link"><span>{link.signal} · {link.source}</span><b>OPEN ↗</b></a> : null)}</div>
      </section>
    </div>

    <section className="hm-drawer-section">
      <SectionHeader title="Expected Operational Consequence" subtitle={evidence.expected_consequence.assumption} />
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 p-4"><Metric label="Deficit" value={`${fmt(evidence.expected_consequence.deficit_mb_d, 3)} mb/d`} /><Metric label="Inventory" value={`${fmt(evidence.expected_consequence.inventory_days_remaining, 0)} days`} /><Metric label="Landed Pressure" value={`+$${fmt(evidence.expected_consequence.landed_cost_pressure_usd_bbl)}/bbl`} /><Metric label="Retail Range" value={`+$${fmt(evidence.expected_consequence.retail_pressure_usd_bbl.low)}–${fmt(evidence.expected_consequence.retail_pressure_usd_bbl.high)}`} /></div>
    </section>

    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Affected Suppliers</h3><div className="mt-3">{evidence.affected_suppliers.length ? evidence.affected_suppliers.map((supplier: any) => <div key={supplier.supplier_id} className="hm-list-row"><span>{supplier.country}</span><b>{supplier.grade_id} · {supplier.share_pct}%</b></div>) : <p className="text-[11px] text-text-2 mt-3">No named supplier is directly mapped to this corridor.</p>}</div></section>
      <section className="hm-drawer-section p-4"><h3 className="hm-drawer-card-title">Modeled Refinery Run Impact</h3><div className="mt-3">{(evidence.expected_consequence.refinery_impacts || []).slice(0, 8).map((refinery: any) => <div key={refinery.refinery_id} className="hm-list-row grid grid-cols-[1fr_auto_auto] gap-3"><span className="truncate">{refinery.name}</span><b className="!text-risk-elev">−{fmt(refinery.run_rate_impact_mb_d, 3)} mb/d</b><small>{fmt(refinery.run_rate_impact_pct, 1)}%</small></div>)}</div></section>
    </div>
  </div>;
}

export function Drawer({ open, mode, playbook, scenario, selectedCorridor, onScenario, onPlans, onClose, solving }: {
  open: boolean; mode: 'scenario' | 'plans' | 'packet' | 'evidence' | null; playbook: Playbook | null;
  scenario: Scenario; selectedCorridor: string | null; solving: boolean;
  onScenario: (scenario: Scenario) => void; onPlans: () => void; onClose: () => void;
}) {
  const [packet, setPacket] = React.useState<any>(null);
  const [packetFailed, setPacketFailed] = React.useState(false);
  const [section, setSection] = React.useState<'scenario' | 'plans'>('plans');
  React.useEffect(() => {
    setPacket(null);
    setPacketFailed(false);
    if (mode === 'scenario' || mode === 'plans') setSection(mode);
    if (mode === 'packet' && playbook) {
      api.packet(playbook.id, playbook.recommended)
        .then((response) => setPacket(response.value))
        .catch(() => setPacketFailed(true));
    }
  }, [mode, selectedCorridor, playbook?.id]);
  const approve = async (preset: string) => { if (playbook) { const response = await api.packet(playbook.id, preset); setPacket(response.value); } };
  if (!open) return null;
  const isEvidence = mode === 'evidence' && selectedCorridor;
  const isPacket = mode === 'packet';
  const corridorTitle = selectedCorridor?.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  const title = isEvidence ? `${corridorTitle} Evidence` : isPacket || packet ? 'Human Action Packet' : 'Decision Workspace';
  return <div className="absolute inset-0 z-20 bg-black/55" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="hm-drawer" aria-label={title}>
      <header className="hm-drawer-header">
        <div className="min-w-0"><span className="hm-top-eyebrow">HEIMDALL</span><h2>{title}</h2></div>
        {!isEvidence && !isPacket && !packet && <div className="hm-workspace-tabs">
          <button onClick={() => setSection('scenario')} className={section === 'scenario' ? 'is-active' : ''}>1 <span>Scenario</span></button>
          <button onClick={() => setSection('plans')} className={section === 'plans' ? 'is-active' : ''}>2 <span>Certified Plans</span></button>
        </div>}
        <div className="flex-1" />
        <span className="hm-num text-[9px] text-text-2 hidden sm:block">ESC TO CLOSE</span>
        <button aria-label={`Close ${title}`} onClick={onClose} className="hm-close-button">✕</button>
      </header>
      <div className="hm-drawer-body">
        {isEvidence ? <EvidenceView corridor={selectedCorridor!} />
          : packet ? <PacketView packet={packet} onBack={isPacket ? onPlans : () => setPacket(null)} />
          : isPacket && packetFailed ? <div className="h-64 grid place-items-center text-center"><div><p className="text-sm text-alert">Action packet could not be assembled.</p><Button variant="ghost" onClick={onPlans} className="mt-4">BACK TO CERTIFICATES</Button></div></div>
          : isPacket ? <div className="h-64 grid place-items-center hm-num text-xs text-accent animate-pulse">ASSEMBLING HUMAN ACTION PACKET…</div>
          : section === 'scenario' ? <ScenarioLab scenario={scenario} solving={solving} onRun={(value) => { onScenario(value); setSection('plans'); }} />
          : <PlanWorkspace playbook={playbook} onApprove={approve} />}
      </div>
    </aside>
  </div>;
}
