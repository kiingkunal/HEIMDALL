// Typed client for the HEIMDALL backend. All responses that carry engine numbers are wrapped in a
// Tagged envelope { value, provenance } so the UI can render DATA AGE / provenance badges.

export interface Provenance {
  source: string;
  kind: 'live' | 'cache' | 'config' | 'engine' | 'replay' | 'demo';
  fetched_at: string;
  source_url?: string | null;
  note?: string | null;
  age_hours?: number;
  freshness?: 'fresh' | 'aging' | 'stale';
}
export interface Tagged<T> { value: T; provenance: Provenance; }

const BASE = ''; // same-origin; vite proxies /api to backend

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

// ---- shapes (partial; only what the UI reads) ----
export interface RiskComponent {
  component: string; weight: number; normalized: number | null;
  contribution: number; present: boolean;
}
export interface RiskValue {
  corridor: string; index: number; confidence: number;
  components: RiskComponent[]; present_signals: string[]; missing_signals: string[];
  confidence_breakdown: Record<string, number>; contradictions: string[]; note: string;
}
export interface CascadeValue {
  deficit_mb_d: number; deficit_pct: number; inventory_days_remaining: number;
  net_shortfall_mb: number; landed_cost_pressure_usd_bbl: number;
  retail_pressure_usd_bbl: { low: number; high: number };
  affected_suppliers: { supplier_id: string; country: string; share_pct: number }[];
  refinery_impacts: {
    refinery_id: string; name: string; baseline_run_mb_d: number; modeled_run_mb_d: number;
    run_rate_impact_mb_d: number; run_rate_impact_pct: number; below_min_run: boolean;
    allocation_basis: string;
  }[];
  scenario: any[]; sources: string[];
}
export interface ResilienceValue {
  score: number;
  components: Record<string, { value: number; weight: number; contribution: number }>;
  scenarios: {
    id: string; name: string; recommended: string; supply_coverage: number;
    robustness_pass_rate: number; supplier_diversity: number; cost_score: number;
    avg_landed_usd_bbl: number; shortfall_mb_d: number;
  }[];
  framing: string;
}
export interface Plan {
  preset: string; label: string; status: string; avg_landed_usd_bbl: number;
  total_shortage_mb_d: number; supplier_mix: Record<string, number>;
  bucket_mix: Record<string, number>; purchases: any[]; spr_drawdown: any[];
  commercial_use_mb_d: number; excluded_suppliers: { supplier_id: string; reason: string }[];
  demand_mb_d: number; served_mb_d: number;
  planning_horizon_days: number; scenario_inputs: Record<string, number>;
}
export interface Certificate {
  preset: string; label: string; robustness_pass_rate: number; confidence_interval: number[];
  worst_case_shortfall_mb_d: number; expected_shortfall_mb_d: number;
  cost_at_risk_usd_bbl: number; max_delay_days: number;
  failure_conditions: Record<string, number>; binding_constraints: string[];
  recommended: boolean; rejected_reason: string | null;
}
export interface Playbook {
  id: string; generated_at: string; valid_until: string; status: string;
  scenario: Scenario;
  plans: Record<string, Plan>; certificates: Record<string, Certificate>;
  recommended: string; recommended_pass_rate: number; fallback: string;
  no_regret_actions: { action: string; option_value: string; reversible: boolean }[];
  stale_reason?: string;
}
export interface Scenario {
  corridor_states?: Record<string, string>;
  restrict_severity?: number;
  unavailable_suppliers?: string[];
  disabled_refineries?: string[];
  duration_days?: number;
  price_shock_usd_bbl?: number;
  demand_change_pct?: number;
  vessel_availability_pct?: number;
  port_congestion_pct?: number;
}
export interface CorridorIntelligence {
  corridor: string; risk_index: number; confidence: number;
  convergence: {
    status: 'observing' | 'watch' | 'confirmed_convergence'; active_origin_count: number;
    available_origin_count: number; active_origins: string[]; rule: string; note: string;
  };
  pulse: {
    observed_tankers: number; moving_tankers: number; slow_tankers: number;
    avg_speed_kt: number | null; baseline_median: number | null;
    baseline_delta_pct: number | null; baseline_samples: number; sanctions_hits: number;
    synthetic: boolean; data_age_hours: number | null; note: string;
  };
}
export interface IntelligenceResponse {
  corridors: Record<string, Tagged<CorridorIntelligence>>;
  confirmed_count: number; watch_count: number;
}
export interface ScenarioOptions {
  controls: Record<string, number>;
  corridors: { id: string; name: string }[];
  suppliers: { id: string; name: string }[];
  refineries: { id: string; name: string }[];
}
export interface ReplayBacktest {
  dataset: string;
  case_study_scope: string;
  config_lock_sha256: string;
  alert: { headline: string; source: string; source_url: string; risk_index: number; confidence: number };
  metrics: {
    detection_lead: {
      calendar_days_point: number; calendar_days_range: [number, number]; precision_note: string;
    };
    counterfactual_premium_avoided_musd: number;
    shortage_days_avoided: number;
    signal_to_certified_plan_seconds: number;
    recommended_plan: string;
    recommended_robustness_pass_rate: number;
    hard_constraint_violations: number;
  };
  limitations: string[];
}

export const api = {
  health: () => get<any>('/api/health'),
  replayFrame: (at: string) => get<Tagged<any>>(`/api/replay/frame?at=${encodeURIComponent(at)}`),
  replayBacktest: () => get<Tagged<ReplayBacktest>>('/api/replay/backtest'),
  risk: () => get<{ corridors: Record<string, Tagged<RiskValue>> }>('/api/risk'),
  riskOne: (c: string) => get<Tagged<RiskValue>>(`/api/risk/${c}`),
  intelligence: () => get<IntelligenceResponse>('/api/intelligence'),
  aisStatus: () => get<any>('/api/ais/status'),
  scenarioOptions: () => get<Tagged<ScenarioOptions>>('/api/scenario/options'),
  evidence: (c: string, narrative = false) =>
    get<Tagged<any>>(`/api/evidence/${c}?narrative=${narrative}`),
  cascade: (corridor: string, severity: number, duration_days: number) =>
    get<Tagged<CascadeValue>>(
      `/api/cascade?corridor=${corridor}&severity=${severity}&duration_days=${duration_days}`),
  montecarlo: (corridor: string, severity: number, duration_days: number) =>
    get<Tagged<any>>(
      `/api/montecarlo?corridor=${corridor}&severity=${severity}&duration_days=${duration_days}`),
  resilience: (n?: number) =>
    get<Tagged<ResilienceValue>>(`/api/resilience${n ? `?n=${n}` : ''}`),
  routes: () => get<{ routes: Record<string, any> }>('/api/routes'),
  network: () => get<Tagged<{ ports: any[]; refineries: any[]; spr: any[] }>>('/api/network'),
  latest: (ns: string) => get<{ namespace: string; items: any[] }>(`/api/latest/${ns}`),
  plans: (s: Scenario) => post<Tagged<{ scenario: any; plans: Record<string, Plan> }>>('/api/plans', s),
  certify: (s: Scenario) =>
    post<Tagged<{ recommended: string; fallback: string; certificates: Record<string, Certificate> }>>(
      '/api/certify', s),
  createPlaybook: (s: Scenario) => post<Tagged<Playbook>>('/api/playbooks', s),
  listPlaybooks: () => get<{ playbooks: any[] }>('/api/playbooks'),
  getPlaybook: (id: string) => get<Playbook>(`/api/playbooks/${id}`),
  refreshPlaybook: (id: string, new_snapshot?: any) =>
    post<any>(`/api/playbooks/${id}/refresh`, { new_snapshot }),
  packet: (id: string, preset: string) => post<Tagged<any>>(`/api/packet/${id}?preset=${preset}`),
  costOfDelay: (corridor: string, severity: number, duration_days: number) =>
    get<Tagged<any>>(
      `/api/cost-of-delay?corridor=${corridor}&severity=${severity}&duration_days=${duration_days}`),
};

export function riskBand(index: number): 'low' | 'elev' | 'high' {
  return index < 40 ? 'low' : index < 70 ? 'elev' : 'high';
}
