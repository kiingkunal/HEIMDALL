import React from 'react';
import { IntelligenceResponse, Playbook, ResilienceValue, Tagged, riskBand } from '../api';
import { Badge, Button, Card, DataAge, Label, MicroBar, SegmentBar } from './primitives';
import { fmt, pct, validRemaining } from '../lib/format';
import { RISK_HEX } from '../lib/colors';
import { CorridorRisk } from '../state';

// ----------------------------------------------------- Resilience score
function ResilienceScore({ t }: { t: Tagged<ResilienceValue> }) {
  const v = t.value;
  const band = v.score < 40 ? 'high' : v.score < 70 ? 'elev' : 'low';
  const color = RISK_HEX[band];
  return (
    <Card title={<span className="hm-label !text-text-2">NATIONAL RESILIENCE</span>}
      badge={<DataAge hours={t.provenance.age_hours} source="ENGINE" />}>
      <div className="flex items-end gap-2 mb-3">
        <span className="hm-num font-bold" style={{ fontSize: 46, lineHeight: '48px', color }}>
          {v.score.toFixed(0)}
        </span>
        <span className="hm-num text-text-3 text-sm mb-1">/100</span>
      </div>
      <SegmentBar frac={v.score / 100} segments={20} color={color} />
      <div className="mt-3 space-y-2">
        {Object.entries(v.components).map(([k, c]) => (
          <div key={k} className="grid grid-cols-[124px_1fr_34px] items-center gap-2">
            <span className="hm-label !text-[9px] !text-text-2">{k.replace(/_/g, ' ')}</span>
            <MicroBar frac={c.value} tone={band === 'high' ? 'high' : band === 'elev' ? 'elev' : 'low'} />
            <span className="hm-num text-2xs text-text-2 text-right">{(c.value * 100).toFixed(0)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ----------------------------------------------------- Cost of delay (rate, not $0 ticker)
function CostOfDelay({ corridor, severity, duration }: { corridor: string; severity: number; duration: number }) {
  const [range, setRange] = React.useState<{ low: number; high: number; point: number } | null>(null);
  React.useEffect(() => {
    fetch(`/api/cost-of-delay?corridor=${corridor}&severity=${severity}&duration_days=${duration}`)
      .then((r) => r.json()).then((d) => setRange(d.value.premium_per_day_musd)).catch(() => {});
  }, [corridor, severity, duration]);
  if (!range) return null;
  return (
    <Card title={<span className="hm-label !text-text-2">COST OF DELAY</span>}
      badge={<Badge tone="alert">LIVE</Badge>}>
      <div className="flex items-baseline gap-1.5">
        <span className="hm-num font-bold" style={{ fontSize: 26, color: 'var(--hm-alert)', textShadow: 'var(--hm-glow-alert)' }}>
          ${fmt(range.point, 1)}M
        </span>
        <span className="hm-num text-2xs text-text-3">/ DAY UNMITIGATED</span>
      </div>
      <div className="hm-num text-2xs text-text-2 mt-1">
        band ${fmt(range.low, 1)}–${fmt(range.high, 1)}M · {corridor.replace(/_/g, ' ')} {Math.round(severity * 100)}% / {duration}d
      </div>
      <div className="h-1 rounded-sm bg-bg-inset mt-1.5 overflow-hidden">
        <div className="h-full" style={{ width: `${Math.min(100, (range.point / range.high) * 100)}%`, background: 'var(--hm-alert)' }} />
      </div>
    </Card>
  );
}

// ----------------------------------------------------- Playbook shelf
function PlaybookShelf({ pb, onOpen }: { pb: Playbook | null; onOpen: () => void }) {
  if (!pb) {
    return (
      <Card title={<span className="hm-label !text-text-2">ACTIVE PLAYBOOK</span>}
        badge={<Badge tone="recomputing">COMPUTING</Badge>}>
        <div className="text-2xs text-text-3">solving + certifying three plans…</div>
      </Card>
    );
  }
  const stale = pb.status !== 'fresh';
  const { label, frac } = validRemaining(pb.valid_until);
  const barColor = frac > 0.4 ? RISK_HEX.low : frac > 0.15 ? RISK_HEX.elev : RISK_HEX.high;
  const rec = pb.certificates[pb.recommended];
  const passTone = rec.robustness_pass_rate >= 0.8 ? 'pass' : rec.robustness_pass_rate >= 0.6 ? 'marginal' : 'fail';

  return (
    <Card selected={!stale}
      title={<span className="hm-label !text-text-2">{stale ? 'PLAYBOOK · STALE' : 'ACTIVE PLAYBOOK'}</span>}
      badge={stale ? <Badge tone="stale">STALE</Badge> :
        <Badge tone={passTone as any}>PASS {pct(rec.robustness_pass_rate)}</Badge>}>
      {stale && pb.stale_reason && <div className="text-2xs text-stale mb-1.5">{pb.stale_reason}</div>}
      <div className="flex items-center justify-between mb-1.5">
        <span className="hm-label !text-2xs">RECOMMENDED</span>
        <span className="hm-num text-sm text-accent font-semibold">{pb.plans[pb.recommended].label}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 hm-num text-2xs mb-2">
        <div><span className="hm-label !text-2xs block">AVG LANDED</span><span className="text-text-1">${fmt(pb.plans[pb.recommended].avg_landed_usd_bbl)}</span></div>
        <div><span className="hm-label !text-2xs block">COST-AT-RISK</span><span className="text-text-1">${fmt(rec.cost_at_risk_usd_bbl)}</span></div>
        <div><span className="hm-label !text-2xs block">WORST SHORT</span><span className="text-text-1">{fmt(rec.worst_case_shortfall_mb_d)} mb/d</span></div>
        <div><span className="hm-label !text-2xs block">FALLBACK</span><span className="text-text-1 capitalize">{pb.fallback.replace(/_/g, '-')}</span></div>
      </div>
      <div className="flex items-center justify-between border-t border-line-1 pt-1.5 mb-2">
        <span className="hm-label !text-2xs">NO-REGRET ACTIONS</span>
        <span className="hm-num text-2xs text-text-1">{pb.no_regret_actions.length} READY</span>
      </div>
      <div className="h-1 rounded-sm bg-bg-inset overflow-hidden">
        <div className="h-full" style={{ width: `${frac * 100}%`, background: stale ? 'var(--hm-stale)' : barColor }} />
      </div>
      <div className="flex justify-between mt-1 mb-2">
        <span className="hm-label !text-2xs">{stale ? 'EXPIRED' : 'VALIDITY'}</span>
        <span className="hm-num text-2xs text-text-2">{stale ? '—' : label}</span>
      </div>
      <Button variant="primary" arrow onClick={onOpen} className="w-full justify-center">COMPARE CERTIFIED PLANS</Button>
    </Card>
  );
}

// ----------------------------------------------------- Corridor instability list (worldmonitor style)
function CorridorRow({ r, intelligence, selected, onSelect }: {
  r: CorridorRisk; intelligence?: any; selected: boolean; onSelect: () => void;
}) {
  const v = r.tagged.value;
  const band = riskBand(v.index);
  const color = RISK_HEX[band];
  const name = r.id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const warn = v.contradictions.length > 0;
  const convergence = intelligence?.value?.convergence;
  const pulse = intelligence?.value?.pulse;
  const convergenceTone = convergence?.status === 'confirmed_convergence' ? 'alert'
    : convergence?.status === 'watch' ? 'elev' : 'neutral';
  return (
    <button onClick={onSelect}
      className={`w-full text-left p-3.5 rounded-md border transition-colors
        ${selected ? 'border-line-2 bg-bg-3' : 'border-line-1 bg-bg-2 hover:border-line-2'}`}>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
        <span className="text-sm font-semibold text-text-1 flex-1 truncate">{name}</span>
        {warn && <span className="text-risk-elev text-2xs" title={v.contradictions[0]}>⚠</span>}
        <span className="hm-num text-md font-bold" style={{ color }}>{v.index.toFixed(0)}</span>
      </div>
      <div className="mt-2.5 h-1.5 rounded-sm bg-bg-inset overflow-hidden">
        <div className="h-full" style={{ width: `${v.index}%`, background: color }} />
      </div>
      <div className="grid grid-cols-2 gap-3 mt-2 hm-num text-[10px] text-text-2">
        <span>Confidence <b className="text-text-1">{pct(v.confidence)}</b></span>
        <span className="text-right"><b className="text-text-1">{v.present_signals.length}/{v.present_signals.length + v.missing_signals.length}</b> signals</span>
      </div>
      {convergence && <div className="flex items-center justify-between gap-2 mt-2.5 pt-2.5 border-t border-line-1">
        <Badge tone={convergenceTone as any}>
          {convergence.status === 'confirmed_convergence' ? 'CONFIRMED' : convergence.status.toUpperCase()}
          {' '}{convergence.active_origin_count}/{convergence.available_origin_count}
        </Badge>
        <span className="hm-num text-[9px] text-text-3">
          AIS {pulse?.observed_tankers ?? 0} OBS{pulse?.baseline_delta_pct == null ? '' : ` · ${pulse.baseline_delta_pct > 0 ? '+' : ''}${pulse.baseline_delta_pct}%`}
        </span>
      </div>}
      <div className="flex justify-between gap-3 mt-2 hm-num text-[9px] text-text-2">
        <span className="truncate">{r.tagged.provenance.source}</span>
        <span className="shrink-0">Updated {r.tagged.provenance.age_hours == null ? '—' : `${Math.round(r.tagged.provenance.age_hours * 60)}m ago`}</span>
      </div>
    </button>
  );
}

// ----------------------------------------------------- Rail
export function RightRail({
  risks, resilience, playbook, intelligence, selectedCorridor, scenario, onSelectCorridor, onOpenPlaybook, onOpenScenario,
}: {
  risks: CorridorRisk[]; resilience: Tagged<ResilienceValue> | null; playbook: Playbook | null;
  intelligence: IntelligenceResponse | null;
  selectedCorridor: string | null; scenario: { corridor_states?: Record<string, string>; restrict_severity?: number };
  onSelectCorridor: (id: string) => void; onOpenPlaybook: () => void; onOpenScenario: () => void;
}) {
  const sorted = [...risks].sort((a, b) => b.tagged.value.index - a.tagged.value.index);
  const top = sorted[0];
  const sev = scenario.restrict_severity ?? 0.5;
  return (
    <aside className="hm-right-rail w-rail shrink-0 h-full bg-bg-1 border-l border-line-1 overflow-y-auto overflow-x-hidden">
      <div className="sticky top-0 z-10 h-11 px-4 bg-bg-2 border-b border-line-1 flex items-center justify-between gap-3">
        <Label>COMMAND DESK</Label>
        <span className="hm-num text-[9px] text-text-3">DECISION SUPPORT · HUMAN AUTHORISES</span>
      </div>
      <div className="p-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Button variant="primary" onClick={onOpenScenario} className="justify-center">RUN SCENARIO</Button>
          <Button variant="ghost" onClick={onOpenPlaybook} className="justify-center">COMPARE PLANS</Button>
        </div>
        {resilience && <ResilienceScore t={resilience} />}
        {top && <CostOfDelay corridor={top.id}
          severity={scenario.corridor_states?.[top.id] === 'closed' ? 1
            : scenario.corridor_states?.[top.id] === 'restricted' ? sev : Math.max(0.3, top.tagged.value.index / 100)}
          duration={(scenario as any).duration_days ?? 14} />}
        <PlaybookShelf pb={playbook} onOpen={onOpenPlaybook} />
        <section className="pt-1">
          <div className="flex items-center justify-between gap-3 mb-2.5 px-1">
            <div><Label className="!text-text-1">CORRIDOR RISK INDEX</Label><div className="text-[10px] text-text-2 mt-0.5">Evidence fusion · 0–100</div></div>
            <Badge tone="neutral">NOT A PROBABILITY</Badge>
          </div>
        <div className="space-y-2">
          {sorted.map((r) => (
            <CorridorRow key={r.id} r={r} intelligence={intelligence?.corridors[r.id]}
              selected={selectedCorridor === r.id}
              onSelect={() => onSelectCorridor(r.id)} />
          ))}
        </div></section>
      </div>
    </aside>
  );
}
