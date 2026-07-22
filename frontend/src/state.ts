import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api, IntelligenceResponse, Playbook, ResilienceValue, RiskValue, Scenario, Tagged,
} from './api';

export interface CorridorRisk { id: string; tagged: Tagged<RiskValue>; }

export interface HeimdallState {
  online: boolean;
  mode: 'LIVE' | 'REPLAY';
  risks: CorridorRisk[];
  resilience: Tagged<ResilienceValue> | null;
  intelligence: IntelligenceResponse | null;
  aisStatus: any | null;
  tankers: any[];
  routes: Record<string, any>;
  network: { ports: any[]; refineries: any[]; spr: any[] };
  playbook: Playbook | null;
  scenario: Scenario;
  selectedCorridor: string | null;
  drawer: null | 'scenario' | 'plans' | 'packet' | 'evidence';
  costOfDelay: Tagged<any> | null;
  loading: boolean;
  solving: boolean;
  lastRefresh: string | null;
  error: string | null;
  replayFrame: Tagged<any> | null;
}

const DEFAULT_SCENARIO: Scenario = {
  corridor_states: {}, restrict_severity: 0.5, duration_days: 14,
  price_shock_usd_bbl: 0, demand_change_pct: 0,
  vessel_availability_pct: 100, port_congestion_pct: 0,
  unavailable_suppliers: [], disabled_refineries: [],
};

export function useHeimdall() {
  const [s, setS] = useState<HeimdallState>({
    online: false, mode: 'LIVE', risks: [], resilience: null, intelligence: null,
    aisStatus: null, tankers: [], routes: {},
    network: { ports: [], refineries: [], spr: [] },
    playbook: null, scenario: DEFAULT_SCENARIO, selectedCorridor: null, drawer: null,
    costOfDelay: null, loading: true, solving: false, lastRefresh: null, error: null,
    replayFrame: null,
  });
  const patch = (p: Partial<HeimdallState>) => setS((prev) => ({ ...prev, ...p }));
  const scenarioRef = useRef(s.scenario);
  scenarioRef.current = s.scenario;

  // initial + periodic load of the monitoring lane (risk, resilience, tankers, routes)
  const loadMonitoring = useCallback(async () => {
    try {
      const [risk, resil, routes, network, intelligence, aisStatus] = await Promise.all([
        api.risk(), api.resilience(80), api.routes(), api.network(),
        api.intelligence(), api.aisStatus(),
      ]);
      const risks: CorridorRisk[] = Object.entries(risk.corridors).map(([id, tagged]) => ({ id, tagged }));
      patch({
        online: true, risks, resilience: resil, routes: routes.routes,
        network: network.value, intelligence, aisStatus,
        loading: false, lastRefresh: new Date().toISOString(), error: null,
      });
    } catch (e) {
      patch({ online: false, loading: false, error: 'Monitoring lane unavailable; retaining cached state.' });
    }
  }, []);

  // tanker positions come from a small dedicated fetch of the latest snapshot rows
  const loadTankers = useCallback(async () => {
    try {
      const r = await fetch('/api/tankers');
      if (r.ok) { const d = await r.json(); patch({ tankers: d.tankers || [] }); }
    } catch { /* offline: keep last */ }
  }, []);

  const recompute = useCallback(async (scenario: Scenario) => {
    patch({ scenario, solving: true, error: null });
    try {
      const pb = await api.createPlaybook(scenario);
      patch({ playbook: pb.value, solving: false, drawer: 'plans' });
    } catch {
      patch({ solving: false, error: 'The response engine could not certify this scenario.' });
    }
  }, []);

  const selectCorridor = useCallback((id: string | null) => {
    patch({ selectedCorridor: id, drawer: id ? 'evidence' : null });
  }, []);

  const openDrawer = useCallback((d: HeimdallState['drawer']) => patch({ drawer: d }), []);
  const setMode = useCallback((mode: 'LIVE' | 'REPLAY') => {
    patch({ mode });
    if (mode === 'LIVE') loadMonitoring();
  }, [loadMonitoring]);

  const setReplayTime = useCallback(async (at: string) => {
    try {
      const frame = await api.replayFrame(at);
      setS((prev) => {
        const replayRisk: CorridorRisk = { id: 'hormuz', tagged: { value: frame.value.risk, provenance: frame.provenance } };
        const risks = prev.risks.some((r) => r.id === 'hormuz')
          ? prev.risks.map((r) => r.id === 'hormuz' ? replayRisk : r)
          : [replayRisk, ...prev.risks];
        return { ...prev, risks, replayFrame: frame, online: true, error: null };
      });
    } catch {
      patch({ error: 'Replay frame unavailable; the simulation clock was not advanced.' });
    }
  }, []);

  useEffect(() => {
    loadMonitoring();
    loadTankers();
    const t = setInterval(() => { loadMonitoring(); }, 30000);
    return () => clearInterval(t);
  }, [loadMonitoring, loadTankers]);

  // generate an initial baseline playbook once online
  useEffect(() => {
    if (s.online && !s.playbook) {
      patch({ solving: true });
      api.createPlaybook(scenarioRef.current)
        .then((pb) => patch({ playbook: pb.value, solving: false }))
        .catch(() => patch({ solving: false, error: 'Baseline playbook precompute failed.' }));
    }
  }, [s.online]); // eslint-disable-line

  return { s, recompute, selectCorridor, openDrawer, setMode, setReplayTime, patch };
}
