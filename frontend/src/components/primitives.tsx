import React from 'react';

// ---------------------------------------------------------------- Card
export function Card({
  title, badge, selected, onClick, children, className = '',
}: {
  title?: React.ReactNode; badge?: React.ReactNode; selected?: boolean;
  onClick?: () => void; children?: React.ReactNode; className?: string;
}) {
  return (
    <div
      onClick={onClick}
      className={`relative bg-bg-2 border rounded-md p-4 transition-colors
        ${selected ? 'border-line-2' : 'border-line-1 hover:border-line-2'}
        ${onClick ? 'cursor-pointer' : ''} ${className}`}
    >
      {selected && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" />}
      {(title || badge) && (
        <div className="flex items-center justify-between gap-3 mb-3 min-w-0">
          {title && <div className="text-md font-sans font-semibold text-text-1">{title}</div>}
          {badge}
        </div>
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- Label
export function Label({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`hm-label ${className}`}>{children}</div>;
}

// ---------------------------------------------------------------- Badge
type BadgeTone =
  | 'neutral' | 'elev' | 'alert' | 'live' | 'replay' | 'sim' | 'demo'
  | 'pass' | 'marginal' | 'fail' | 'stale' | 'recomputing' | 'accent';

const toneClass: Record<BadgeTone, string> = {
  neutral: 'text-text-3 border-line-2',
  elev: 'text-risk-elev border-risk-elev bg-risk-elev-dim',
  alert: 'text-alert border-alert bg-alert-dim',
  live: 'text-risk-low border-risk-low bg-risk-low-dim',
  replay: 'text-accent border-accent bg-accent-dim',
  sim: 'text-sim border-sim bg-sim-dim',
  demo: 'text-sim border-sim',
  pass: 'text-risk-low border-risk-low bg-risk-low-dim',
  marginal: 'text-risk-elev border-risk-elev bg-risk-elev-dim',
  fail: 'text-alert border-alert bg-alert-dim',
  stale: 'text-stale border-stale bg-stale-dim',
  recomputing: 'text-accent border-accent bg-accent-dim animate-pulse',
  accent: 'text-accent border-accent bg-accent-dim',
};

export function Badge({
  tone = 'neutral', children, dot, className = '',
}: { tone?: BadgeTone; children: React.ReactNode; dot?: boolean; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 font-mono text-2xs font-semibold uppercase
        tracking-badge px-2 py-1 rounded-sm border leading-none whitespace-nowrap ${toneClass[tone]} ${className}`}
      style={{ borderColor: undefined }}
    >
      {dot && (
        <span className="w-1.5 h-1.5 rounded-full bg-risk-low animate-pulse" style={{ animationDuration: '1.2s' }} />
      )}
      {children}
    </span>
  );
}

// Data-age badge — flips tone by age. Doctrine: every number carries one.
export function DataAge({ hours, source }: { hours?: number | null; source?: string }) {
  const mins = hours == null ? null : hours * 60;
  const tone: BadgeTone = mins == null ? 'neutral' : mins > 60 ? 'alert' : mins > 15 ? 'elev' : 'neutral';
  const label = hours == null ? '—' : mins! < 1 ? 'NOW' : mins! < 60 ? `${Math.round(mins!)}M` : `${Math.floor(mins! / 60)}H`;
  return (
    <span className="inline-flex items-center gap-1">
      {source && <Badge tone="neutral">SRC {source}</Badge>}
      <Badge tone={tone}>DATA AGE {label}</Badge>
    </span>
  );
}

// ---------------------------------------------------------------- Button
export function Button({
  variant = 'ghost', children, onClick, disabled, arrow, className = '',
}: {
  variant?: 'primary' | 'ghost' | 'destructive'; children: React.ReactNode;
  onClick?: () => void; disabled?: boolean; arrow?: boolean; className?: string;
}) {
  const base = 'h-9 px-3.5 rounded font-mono text-xs font-semibold uppercase tracking-badge inline-flex items-center gap-1.5 transition-colors';
  const styles = {
    primary: 'bg-accent-dim text-accent border border-accent hover:bg-accent hover:text-bg-0',
    ghost: 'bg-transparent text-text-2 border border-line-1 hover:border-line-2 hover:text-text-1',
    destructive: 'bg-alert-dim text-alert border border-alert hover:bg-alert hover:text-bg-0',
  }[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles} ${disabled ? 'opacity-40 pointer-events-none' : ''} ${className}`}
    >
      {children}{arrow && <span>→</span>}
    </button>
  );
}

// ---------------------------------------------------------------- Micro-bar (component contribution)
export function MicroBar({ frac, tone = 'accent' }: { frac: number; tone?: 'accent' | 'low' | 'elev' | 'high' | 'sim' }) {
  const color = {
    accent: 'var(--hm-accent)', low: 'var(--hm-risk-low)', elev: 'var(--hm-risk-elev)',
    high: 'var(--hm-risk-high)', sim: 'var(--hm-sim)',
  }[tone];
  return (
    <div className="h-1 rounded-sm bg-bg-inset overflow-hidden">
      <div className="h-full rounded-sm" style={{ width: `${Math.max(0, Math.min(1, frac)) * 100}%`, background: color }} />
    </div>
  );
}

// ---------------------------------------------------------------- Segment bar (n discrete segments)
export function SegmentBar({ frac, segments = 10, color }: { frac: number; segments?: number; color: string }) {
  const filled = Math.round(Math.max(0, Math.min(1, frac)) * segments);
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: segments }).map((_, i) => (
        <div key={i} className="h-2 flex-1 rounded-sm"
          style={{ background: i < filled ? color : 'var(--hm-bg-inset)' }} />
      ))}
    </div>
  );
}
