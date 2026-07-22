import React from 'react';
import { RISK_HEX } from '../lib/colors';

// 2025 standoff replay window + key event pips (matches data/replay/2025-standoff/evidence.jsonl).
const REPLAY_START = new Date('2025-05-01T00:00:00Z').getTime();
const REPLAY_END = new Date('2025-06-30T00:00:00Z').getTime();
const EVENTS = [
  { d: '2025-06-13', band: 'high', label: 'Israel strikes Iran' },
  { d: '2025-06-18', band: 'high', label: 'Hormuz closure threat' },
  { d: '2025-06-19', band: 'high', label: 'Brent $80.37 peak' },
  { d: '2025-06-22', band: 'high', label: 'US strikes' },
  { d: '2025-06-24', band: 'elev', label: 'Ceasefire' },
];

function Segmented<T extends string>({ options, value, onChange }: {
  options: T[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex bg-bg-inset rounded p-0.5 gap-0.5">
      {options.map((o) => (
        <button key={o} onClick={() => onChange(o)}
          className={`h-6 px-2 rounded-sm font-mono text-2xs font-semibold uppercase tracking-badge
            ${o === value ? 'bg-bg-3 border border-line-2 text-text-1' : 'text-text-3 border border-transparent'}`}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function BottomRail({
  onReplayTime,
}: {
  onReplayTime: (at: string) => void;
}) {
  const [scrub, setScrub] = React.useState(0.72); // position 0..1 within replay window
  const [speed, setSpeed] = React.useState<'×1' | '×4' | '×16'>('×4');
  const [playing, setPlaying] = React.useState(false);
  const scrubRef = React.useRef(scrub);
  scrubRef.current = scrub;

  React.useEffect(() => {
    if (!playing) return;
    const mult = speed === '×1' ? 1 : speed === '×4' ? 4 : 16;
    const t = setInterval(() => setScrub((s) => (s >= 1 ? 0 : Math.min(1, s + 0.0006 * mult))), 100);
    return () => clearInterval(t);
  }, [playing, speed]);

  React.useEffect(() => {
    const emit = () => {
      const at = new Date(REPLAY_START + scrubRef.current * (REPLAY_END - REPLAY_START));
      onReplayTime(at.toISOString());
    };
    emit();
    if (!playing) return;
    const t = setInterval(emit, 600);
    return () => clearInterval(t);
  }, [playing, onReplayTime]);

  const simTime = new Date(REPLAY_START + scrub * (REPLAY_END - REPLAY_START));
  const simLabel = `${simTime.toISOString().slice(0, 10)} ${simTime.toISOString().slice(11, 16)} UTC`;

  return (
    <div className="h-rail-b shrink-0 bg-bg-0 border-t border-line-1 flex items-center gap-3 px-3">
      <span className="hm-label !text-accent">Historical Replay</span>
      <button aria-label={playing ? 'Pause replay' : 'Play replay'} onClick={() => setPlaying(!playing)}
        className="h-7 w-7 rounded-sm border border-line-1 text-accent hover:border-accent flex items-center justify-center text-xs">
        {playing ? '❚❚' : '▶'}
      </button>
      <Segmented options={['×1', '×4', '×16']} value={speed} onChange={setSpeed} />

      {/* timeline scrubber */}
      <div className="flex-1 relative h-6 flex items-center">
        {/* event pips */}
        {EVENTS.map((e) => {
          const frac = (new Date(e.d).getTime() - REPLAY_START) / (REPLAY_END - REPLAY_START);
          return (
            <div key={e.d} title={e.label} className="absolute -top-0.5 w-1 h-1 rounded-sm"
              style={{ left: `${frac * 100}%`, background: (RISK_HEX as any)[e.band] }} />
          );
        })}
        <div className="w-full h-1.5 rounded-sm bg-bg-inset relative">
          <div className="absolute h-full rounded-sm"
            style={{ width: `${scrub * 100}%`, background: 'rgba(76,195,232,.45)' }} />
          <div className="absolute -top-1" style={{ left: `calc(${scrub * 100}% - 1px)` }}>
            <div className="w-0.5 h-4 bg-accent" style={{ boxShadow: 'var(--hm-glow-low)' }} />
          </div>
        </div>
        <input aria-label="Historical replay time" type="range" min={0} max={1000} value={Math.round(scrub * 1000)}
          onChange={(e) => setScrub(Number(e.target.value) / 1000)}
          onPointerUp={() => onReplayTime(simTime.toISOString())}
          onKeyUp={() => onReplayTime(simTime.toISOString())}
          className="absolute inset-0 opacity-0 cursor-pointer" />
      </div>

      <div className="text-right">
        <div className="hm-label !text-text-3">SIMULATION CLOCK</div>
        <div className="hm-num text-sm text-text-1">{simLabel}</div>
      </div>
      <span className="hm-num text-[9px] text-accent max-w-36 leading-3">SOURCED REPLAY<br />LEAKAGE GUARDED</span>
    </div>
  );
}
