// Formatting helpers. Numbers are always mono/tabular in the UI (apply .hm-num on the element).

export function relAge(hours?: number | null): string {
  if (hours == null) return '—';
  const mins = Math.round(hours * 60);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function ageBadgeTone(hours?: number | null): 'neutral' | 'elev' | 'alert' {
  if (hours == null) return 'neutral';
  const mins = hours * 60;
  if (mins > 60) return 'alert';
  if (mins > 15) return 'elev';
  return 'neutral';
}

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—';
  return `${(n * 100).toFixed(digits)}%`;
}

export function validRemaining(validUntil: string): { label: string; frac: number } {
  const end = new Date(validUntil).getTime();
  const now = Date.now();
  const remMs = end - now;
  const totalMs = 12 * 3600 * 1000; // default validity window
  const frac = Math.max(0, Math.min(1, remMs / totalMs));
  if (remMs <= 0) return { label: 'EXPIRED', frac: 0 };
  const mins = Math.floor(remMs / 60000);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return { label: `VALID ${h}H ${m}M`, frac };
}
