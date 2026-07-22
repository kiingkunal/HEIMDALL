import { riskBand } from '../api';

export const RISK_HEX = {
  low: '#00E68C', elev: '#FFB224', high: '#FF4E42',
};
export const ACCENT = '#00E68C';
export const ALERT = '#FF3B3B';
export const STALE = '#6A737B';
export const SIM = '#B48CFF';
export const TANKER_UNDERWAY = '#7A8C99';

export function riskHex(index: number): string {
  return RISK_HEX[riskBand(index)];
}
export function riskVar(index: number): string {
  return `var(--hm-risk-${riskBand(index)})`;
}
export function riskDimVar(index: number): string {
  return `var(--hm-risk-${riskBand(index)}-dim)`;
}

// hex -> [r,g,b,a] for deck.gl
export function rgb(hex: string, a = 255): [number, number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), a];
}
