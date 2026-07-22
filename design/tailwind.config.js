/** HEIMDALL Tailwind config v1.0 — maps to design/tokens.css vars.
 *  Usage: bg-bg-2, text-risk-high, border-line-1, font-mono, text-hero, p-4 (=16px)…
 *  tokens.css must be imported before Tailwind utilities resolve. */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      bg: { 0: 'var(--hm-bg-0)', 1: 'var(--hm-bg-1)', 2: 'var(--hm-bg-2)', 3: 'var(--hm-bg-3)', inset: 'var(--hm-bg-inset)' },
      line: { 1: 'var(--hm-line-1)', 2: 'var(--hm-line-2)' },
      text: { 1: 'var(--hm-text-1)', 2: 'var(--hm-text-2)', 3: 'var(--hm-text-3)' },
      accent: { DEFAULT: 'var(--hm-accent)', dim: 'var(--hm-accent-dim)' },
      alert: { DEFAULT: 'var(--hm-alert)', dim: 'var(--hm-alert-dim)' },
      risk: {
        low: 'var(--hm-risk-low)', 'low-dim': 'var(--hm-risk-low-dim)',
        elev: 'var(--hm-risk-elev)', 'elev-dim': 'var(--hm-risk-elev-dim)',
        high: 'var(--hm-risk-high)', 'high-dim': 'var(--hm-risk-high-dim)',
      },
      stale: { DEFAULT: 'var(--hm-stale)', dim: 'var(--hm-stale-dim)' },
      sim: { DEFAULT: 'var(--hm-sim)', dim: 'var(--hm-sim-dim)' },
    },
    fontFamily: {
      sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
      mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
    },
    fontSize: {
      '2xs': ['10px', '14px'],
      xs: ['11px', '16px'],
      sm: ['12px', '18px'],
      base: ['13px', '20px'],
      md: ['15px', '22px'],
      lg: ['18px', '26px'],
      xl: ['22px', '28px'],
      '2xl': ['28px', '34px'],
      '3xl': ['40px', '44px'],
      hero: ['64px', '64px'],
    },
    spacing: {
      0: '0', px: '1px', 0.5: '2px', 1: '4px', 2: '8px', 3: '12px',
      4: '16px', 5: '20px', 6: '24px', 8: '32px', 10: '40px', 14: '56px',
    },
    borderRadius: { none: '0', sm: '2px', DEFAULT: '4px', md: '6px' },
    letterSpacing: { normal: '0', label: '.09em', badge: '.06em', tight: '-.02em' },
    boxShadow: {
      drawer: 'var(--hm-shadow-drawer)',
      'glow-low': 'var(--hm-glow-low)',
      'glow-elev': 'var(--hm-glow-elev)',
      'glow-high': 'var(--hm-glow-high)',
      'glow-alert': 'var(--hm-glow-alert)',
      none: 'none',
    },
    extend: {
      width: { rail: 'var(--hm-rail-right-w)', drawer: 'var(--hm-drawer-w)' },
      height: { 'rail-b': 'var(--hm-rail-bottom-h)' },
      keyframes: { 'hm-pulse': { '0%,100%': { opacity: '1' }, '50%': { opacity: '.35' } } },
      animation: { pulse: 'hm-pulse 1.2s ease-in-out infinite' },
    },
  },
  plugins: [],
};
