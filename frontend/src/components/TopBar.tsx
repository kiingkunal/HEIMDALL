import React from 'react';
import { CorridorRisk } from '../state';
import { ResilienceValue, Tagged } from '../api';
import { RISK_HEX } from '../lib/colors';

export type TheatreId = 'arabian' | 'national' | 'hormuz';

const THEATRES: { id: TheatreId; label: string; detail: string }[] = [
  { id: 'arabian', label: 'Arabian Sea', detail: 'India–Gulf energy corridor' },
  { id: 'national', label: 'India Network', detail: 'Ports, refineries & reserves' },
  { id: 'hormuz', label: 'Hormuz Approach', detail: 'Chokepoint vessel watch' },
];

function BrandMark() {
  return <span className="hm-brand-mark" aria-hidden="true">
    <span className="hm-brand-orbit" />
    <span className="hm-brand-core" />
    <span className="hm-brand-sweep" />
  </span>;
}

function ActionButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button onClick={onClick} className="hm-top-action">{label}</button>;
}

export function TopBar({
  mode, onMode, online, resilience, risks, tankerCount, theatre, onTheatre, onScenario, onPlans,
}: {
  mode: 'LIVE' | 'REPLAY'; onMode: (m: 'LIVE' | 'REPLAY') => void; online: boolean;
  resilience: Tagged<ResilienceValue> | null; risks: CorridorRisk[]; tankerCount: number;
  theatre: TheatreId; onTheatre: (id: TheatreId) => void;
  onScenario: () => void; onPlans: () => void;
}) {
  const [theatreOpen, setTheatreOpen] = React.useState(false);
  const theatreRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!theatreRef.current?.contains(event.target as Node)) setTheatreOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const score = resilience?.value.score ?? null;
  const band = score == null ? 'elev' : score < 40 ? 'high' : score < 70 ? 'elev' : 'low';
  const color = RISK_HEX[band];
  const topRisk = [...risks].sort((a, b) => b.tagged.value.index - a.tagged.value.index)[0];
  const activeTheatre = THEATRES.find((item) => item.id === theatre) || THEATRES[0];

  return <header className="hm-topbar">
    <div className="hm-brand" translate="no">
      <BrandMark />
      <div className="min-w-0">
        <h1>Heimdall</h1>
        <p>Energy Resilience Command Twin</p>
      </div>
    </div>

    <div className={`hm-system-state ${online ? 'is-live' : 'is-cache'}`}>
      <span aria-hidden="true" />{online ? 'Live system' : 'Cache mode'}
    </div>

    <div ref={theatreRef} className="relative">
      <button className="hm-theatre-trigger" onClick={() => setTheatreOpen((open) => !open)}
        aria-haspopup="listbox" aria-expanded={theatreOpen}>
        <span className="hm-theatre-dot" aria-hidden="true" />
        <span className="min-w-0 text-left">
          <span className="hm-top-eyebrow">Theatre</span>
          <span className="hm-theatre-value">{activeTheatre.label}</span>
        </span>
        <span className="hm-chevron" aria-hidden="true">⌄</span>
      </button>
      {theatreOpen && <div className="hm-theatre-menu" role="listbox" aria-label="Map theatre">
        {THEATRES.map((item) => <button key={item.id} role="option" aria-selected={item.id === theatre}
          onClick={() => { onTheatre(item.id); setTheatreOpen(false); }}
          className={item.id === theatre ? 'is-active' : ''}>
          <span>{item.label}</span><small>{item.detail}</small>
        </button>)}
      </div>}
    </div>

    {topRisk && <div className="hm-lead-risk hidden xl:flex">
      <span className="hm-top-eyebrow">Lead Risk</span>
      <span>{topRisk.id.replace(/_/g, ' ')}</span>
      <strong style={{ color: RISK_HEX[topRisk.tagged.value.index < 40 ? 'low' : topRisk.tagged.value.index < 70 ? 'elev' : 'high'] }}>
        {topRisk.tagged.value.index.toFixed(0)}
      </strong>
    </div>}

    <div className="flex-1" />

    <div className="hm-resilience-pill hidden lg:flex" style={{ '--score-color': color } as React.CSSProperties}>
      <div><span>National</span><b>Resilience</b></div>
      <strong>{score == null ? '—' : score.toFixed(0)}</strong><small>/100</small>
    </div>

    <div className="hm-mode-toggle" aria-label="Data mode">
      {(['LIVE', 'REPLAY'] as const).map((item) => <button key={item} onClick={() => onMode(item)}
        className={item === mode ? 'is-active' : ''} aria-pressed={item === mode}>
        <span className="hm-mode-dot" aria-hidden="true" />{item === 'LIVE' ? 'Live' : 'Replay'}
      </button>)}
    </div>

    <ActionButton label="Scenario" onClick={onScenario} />
    <ActionButton label="Plans" onClick={onPlans} />
    <div className="hm-tanker-count" title="Tankers in the latest AIS-backed snapshot">
      <span aria-hidden="true">◈</span><strong>{tankerCount}</strong><small>tankers</small>
    </div>
  </header>;
}
