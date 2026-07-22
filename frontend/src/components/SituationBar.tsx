import React from 'react';
import { IntelligenceResponse, Playbook } from '../api';
import { CorridorRisk } from '../state';

function Clock({ mode, replayTime }: { mode: 'LIVE' | 'REPLAY'; replayTime?: string }) {
  const [now, setNow] = React.useState(new Date());
  React.useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  const value = mode === 'REPLAY' && replayTime ? new Date(replayTime) : now;
  return <span className="hm-num text-xs text-text-1">{value.toISOString().slice(0, 19).replace('T', ' ')} UTC</span>;
}

export function SituationBar({
  mode, risks, playbook, solving, intelligence, aisStatus, replayTime, onDetect, onScenario, onAllocate, onPlans, onAuthorise,
}: {
  mode: 'LIVE' | 'REPLAY'; risks: CorridorRisk[]; playbook: Playbook | null; solving: boolean;
  intelligence: IntelligenceResponse | null; aisStatus: any | null;
  replayTime?: string;
  onDetect: () => void; onScenario: () => void; onAllocate: () => void; onPlans: () => void; onAuthorise: () => void;
}) {
  const hasSignals = risks.length > 0;
  const certified = !!playbook?.certificates?.[playbook.recommended];
  const receiving = !!aisStatus?.stream?.value?.receiving;
  const connected = !!aisStatus?.stream?.value?.connected;
  const aisLabel = receiving ? 'AIS RECEIVING' : connected ? 'AIS CONNECTING'
    : aisStatus?.live_snapshot ? 'AIS CACHE' : 'SIM FALLBACK';
  const stages = [
    { label: 'DETECT', done: hasSignals, active: !hasSignals, action: onDetect, hint: 'Open lead-risk evidence' },
    { label: 'CASCADE', done: hasSignals, active: false, action: onScenario, hint: 'Open cascade scenario' },
    { label: 'ALLOCATE', done: !!playbook, active: solving, action: onAllocate, hint: 'Inspect solver allocation' },
    { label: 'CERTIFY', done: certified, active: solving, action: onPlans, hint: 'Compare robustness certificates' },
    { label: 'AUTHORISE', done: false, active: certified && !solving, action: onAuthorise, hint: 'Assemble human action packet' },
  ];

  return (
    <div className="h-9 shrink-0 bg-bg-1 border-b border-line-1 flex items-center px-3 gap-3">
      <span className="hm-label !text-text-1 min-w-[190px]">INDIA ENERGY SITUATION</span>
      <div className="hidden md:flex items-center gap-1.5">
        {stages.map((stage, i) => (
          <React.Fragment key={stage.label}>
            <button onClick={stage.action} title={stage.hint}
              className={`hm-stage-button flex items-center gap-1.5 hm-num text-[9px] tracking-[.08em]
                ${stage.active ? 'text-accent' : stage.done ? 'text-text-1' : 'text-text-3'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${stage.active ? 'bg-accent animate-pulse' : stage.done ? 'bg-risk-low' : 'bg-line-2'}`} />
              {stage.label}
            </button>
            {i < stages.length - 1 && <span className="text-line-2">──</span>}
          </React.Fragment>
        ))}
      </div>
      {solving && <span className="hm-num text-2xs text-accent animate-pulse">SOLVER + ROBUSTNESS TEST RUNNING</span>}
      {intelligence && (intelligence.confirmed_count > 0 || intelligence.watch_count > 0) && (
        <span className={`hm-num text-[9px] px-2 py-1 border rounded-sm ${intelligence.confirmed_count
          ? 'text-alert border-alert bg-alert-dim' : 'text-risk-elev border-risk-elev bg-risk-elev-dim'}`}>
          {intelligence.confirmed_count ? `${intelligence.confirmed_count} CONFIRMED CONVERGENCE` : `${intelligence.watch_count} MULTI-SOURCE WATCH`}
        </span>
      )}
      <div className="flex-1" />
      {mode === 'LIVE' && <>
        <span className={`hm-num text-[9px] ${receiving ? 'text-risk-low' : 'text-text-3'}`}>● {aisLabel}</span>
        <span className="hm-num text-[9px] text-text-3">SYSTEM CLOCK</span>
        <Clock mode={mode} replayTime={replayTime} />
      </>}
    </div>
  );
}
