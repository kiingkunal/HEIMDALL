import React from 'react';
import DeckGL from '@deck.gl/react';
import { ScatterplotLayer, ArcLayer, GeoJsonLayer, TextLayer } from '@deck.gl/layers';
import { Map } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { CorridorRisk } from '../state';
import { rgb, riskHex, ACCENT, SIM, TANKER_UNDERWAY, RISK_HEX } from '../lib/colors';
import { riskBand } from '../api';
import type { TheatreId } from './TopBar';

const OFFLINE_STYLE: any = {
  version: 8, sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#05080D' } }],
};
const INDIA_REF: [number, number] = [69.84, 22.43];
const COUNTRIES_URL = '/data/ne_110m_admin_0_countries.geojson';

// focused on the Arabian Sea / Hormuz -> India theatre (not the whole globe)
const VIEW_BY_THEATRE: Record<TheatreId, any> = {
  arabian: { longitude: 61, latitude: 17, zoom: 3.55, pitch: 0, bearing: 0 },
  national: { longitude: 77.2, latitude: 20.2, zoom: 3.7, pitch: 0, bearing: 0 },
  hormuz: { longitude: 56.2, latitude: 25.5, zoom: 5.15, pitch: 0, bearing: 0 },
};

const THEATRE_LABELS = [
  { name: 'India', position: [78.4, 22.2] },
  { name: 'Pakistan', position: [69.5, 29.4] },
  { name: 'Iran', position: [53.7, 32.1] },
  { name: 'Iraq', position: [43.8, 33.0] },
  { name: 'Saudi Arabia', position: [45.0, 23.4] },
  { name: 'United Arab Emirates', position: [54.3, 24.1] },
  { name: 'Oman', position: [57.2, 20.4] },
  { name: 'Kuwait', position: [47.5, 29.4] },
  { name: 'Yemen', position: [47.3, 15.6] },
  { name: 'Egypt', position: [29.8, 26.7] },
  { name: 'Nigeria', position: [8.7, 9.4] },
] as { name: string; position: [number, number] }[];

const CORRIDOR_GEO: Record<string, [number, number]> = {
  hormuz: [56.25, 26.6], bab_el_mandeb: [43.35, 12.6], suez: [32.35, 30.6], malacca: [100.9, 3.2],
};
const CORRIDOR_NAME: Record<string, string> = {
  hormuz: 'HORMUZ', bab_el_mandeb: 'BAB-EL-MANDEB', suez: 'SUEZ', malacca: 'MALACCA',
};

// natural-earth country NAME -> our supplier id (for the exposure choropleth)
const NAME_TO_SUPPLIER: Record<string, string> = {
  Russia: 'russia', Iraq: 'iraq', 'Saudi Arabia': 'saudi_arabia',
  'United Arab Emirates': 'uae', 'United States of America': 'usa', Kuwait: 'kuwait',
  Nigeria: 'nigeria', Brazil: 'brazil', Angola: 'angola',
};

export interface LayerToggles {
  countries: boolean; halos: boolean; arcs: boolean; tankers: boolean; labels: boolean;
  ports: boolean; refineries: boolean; spr: boolean;
}

export function WarMap({
  tankers, routes, risks, network, toggles, theatre, onSelectCorridor, selectedCorridor, onSelectTanker,
}: {
  tankers: any[]; routes: Record<string, any>; risks: CorridorRisk[];
  network: { ports: any[]; refineries: any[]; spr: any[] };
  theatre: TheatreId;
  toggles: LayerToggles; onSelectCorridor: (id: string) => void; selectedCorridor: string | null;
  onSelectTanker: (t: any) => void;
}) {
  const [countries, setCountries] = React.useState<any>(null);
  React.useEffect(() => {
    fetch(COUNTRIES_URL).then((r) => r.json()).then(setCountries).catch(() => setCountries(null));
  }, []);

  const riskByCorridor = React.useMemo(
    () => Object.fromEntries(risks.map((r) => [r.id, r.tagged.value.index])), [risks]);

  // supplier -> its route's max corridor risk index (Gulf suppliers inherit Hormuz risk)
  const supplierRisk = React.useMemo(() => {
    const m: Record<string, number> = {};
    Object.values(routes).forEach((r: any) => {
      const cs: string[] = r.corridors || [];
      m[r.supplier_id] = cs.length ? Math.max(...cs.map((c) => riskByCorridor[c] ?? 30)) : 15;
    });
    return m;
  }, [routes, riskByCorridor]);

  const layers = React.useMemo(() => {
    const L: any[] = [];

    // --- choropleth: supplier countries tinted by exposure, India highlighted, rest faint ---
    if (toggles.countries && countries) {
      L.push(new GeoJsonLayer({
        id: 'countries', data: countries, stroked: true, filled: true,
        getLineColor: (f: any) => {
          const name = f.properties.NAME || f.properties.ADMIN;
          if (name === 'India') return rgb(ACCENT, 150);
          return NAME_TO_SUPPLIER[name] ? rgb('#2C405A', 220) : rgb('#141F2E', 200);
        },
        getFillColor: (f: any) => {
          const name = f.properties.NAME || f.properties.ADMIN;
          if (name === 'India') return rgb(ACCENT, 46);
          const sid = NAME_TO_SUPPLIER[name];
          if (sid) return rgb(riskHex(supplierRisk[sid] ?? 30), 42);
          return rgb('#0C1420', 235);
        },
        lineWidthMinPixels: 0.5, pickable: false, updateTriggers: { getFillColor: [supplierRisk] },
      }));
      if (toggles.labels) {
        L.push(new TextLayer({
          id: 'theatre-country-labels', data: THEATRE_LABELS,
          getPosition: (item: any) => item.position, getText: (item: any) => item.name,
          getSize: 12, sizeUnits: 'pixels', getColor: [215, 226, 237, 210],
          fontFamily: 'IBM Plex Sans, sans-serif', fontWeight: 600,
          fontSettings: { sdf: true },
          getTextAnchor: 'middle', getAlignmentBaseline: 'center',
          outlineWidth: 2, outlineColor: [5, 8, 13, 235], pickable: false,
        }));
      }
    }

    // --- corridor risk halos: layered glow (outer soft + mid + core ring) ---
    if (toggles.halos) {
      const halo = risks.filter((r) => CORRIDOR_GEO[r.id]);
      [[3.0, 22], [2.0, 40], [1.15, 90]].forEach(([mult, alpha], i) => {
        L.push(new ScatterplotLayer({
          id: `halo-${i}`, data: halo,
          getPosition: (r: CorridorRisk) => CORRIDOR_GEO[r.id],
          getRadius: (r: CorridorRisk) => (60000 + r.tagged.value.index * 1900) * (mult as number),
          getFillColor: (r: CorridorRisk) => rgb(riskHex(r.tagged.value.index), alpha as number),
          radiusUnits: 'meters', stroked: false, pickable: i === 2,
          onClick: (info: any) => info.object && onSelectCorridor(info.object.id),
          updateTriggers: { getFillColor: [riskByCorridor], getRadius: [riskByCorridor] },
        }));
      });
      // core ring
      L.push(new ScatterplotLayer({
        id: 'halo-ring', data: halo,
        getPosition: (r: CorridorRisk) => CORRIDOR_GEO[r.id],
        getRadius: (r: CorridorRisk) => 60000 + r.tagged.value.index * 1900,
        getLineColor: (r: CorridorRisk) => rgb(riskHex(r.tagged.value.index), 230),
        getFillColor: [0, 0, 0, 0], stroked: true, filled: false, lineWidthMinPixels: 1.5,
        radiusUnits: 'meters', pickable: true,
        onClick: (info: any) => info.object && onSelectCorridor(info.object.id),
        updateTriggers: { getLineColor: [riskByCorridor], getRadius: [riskByCorridor] },
      }));
    }

    // --- supplier -> India flow arcs ---
    if (toggles.arcs) {
      const arcData = Object.values(routes).filter((r: any) => r.load_port);
      L.push(new ArcLayer({
        id: 'flow-arcs', data: arcData,
        getSourcePosition: (r: any) => r.load_port, getTargetPosition: () => INDIA_REF,
        getSourceColor: rgb(ACCENT, 90), getTargetColor: rgb(ACCENT, 200),
        getWidth: 1.2, greatCircle: true,
      }));
    }

    // --- India energy network nodes (sourced static twin configuration) ---
    if (toggles.ports) {
      const ports = network.ports.filter((p: any) => !p.is_load_port);
      L.push(new ScatterplotLayer({
        id: 'india-ports', data: ports, getPosition: (p: any) => [p.lon, p.lat],
        radiusUnits: 'pixels', getRadius: 4, getFillColor: [84, 181, 255, 235],
        stroked: true, getLineColor: [210, 235, 255, 220], lineWidthMinPixels: 1, pickable: true,
      }));
    }
    if (toggles.refineries) {
      L.push(new ScatterplotLayer({
        id: 'india-refineries', data: network.refineries,
        getPosition: (r: any) => [r.lon, r.lat], radiusUnits: 'pixels', getRadius: 4.5,
        getFillColor: rgb(ACCENT, 245), stroked: true, getLineColor: [215, 250, 255, 230],
        lineWidthMinPixels: 1, pickable: true,
      }));
    }
    if (toggles.spr) {
      L.push(new ScatterplotLayer({
        id: 'india-spr', data: network.spr, getPosition: (s: any) => [s.lon, s.lat],
        radiusUnits: 'pixels', getRadius: 5, getFillColor: [180, 140, 255, 245],
        stroked: true, getLineColor: [235, 220, 255, 230], lineWidthMinPixels: 1, pickable: true,
      }));
    }

    // --- tankers (brighter, SIM flagged) ---
    if (toggles.tankers) {
      L.push(new ScatterplotLayer({
        id: 'tankers', data: tankers,
        getPosition: (t: any) => [t.lon, t.lat],
        getRadius: (t: any) => (t.source === 'sim' ? 3.2 : 3.6),
        radiusUnits: 'pixels', radiusMinPixels: 2.6, radiusMaxPixels: 7,
        getFillColor: (t: any) =>
          t.source === 'sim' ? rgb(SIM, 220)
            : (t.ship_type || '').toLowerCase().includes('crude') ? rgb('#8EC5EA', 240)
              : rgb(TANKER_UNDERWAY, 220),
        stroked: true, getLineColor: rgb('#05080D', 180), lineWidthMinPixels: 0.5, pickable: true,
        onClick: (info: any) => info.object && onSelectTanker(info.object),
      }));
    }

    // --- on-map corridor labels (name + index) ---
    if (toggles.labels) {
      L.push(new TextLayer({
        id: 'corridor-labels', data: risks.filter((r) => CORRIDOR_GEO[r.id]),
        getPosition: (r: CorridorRisk) => CORRIDOR_GEO[r.id],
        getText: (r: CorridorRisk) => `${CORRIDOR_NAME[r.id]}  ${r.tagged.value.index.toFixed(0)}`,
        getSize: 12, getColor: (r: CorridorRisk) => rgb(riskHex(r.tagged.value.index), 255),
        getPixelOffset: [0, -26], fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600,
        fontSettings: { sdf: true },
        getTextAnchor: 'middle', background: true, getBackgroundColor: [5, 8, 13, 245],
        backgroundPadding: [6, 4], outlineWidth: 1, outlineColor: [5, 8, 13, 255], characterSet: 'auto',
        updateTriggers: { getText: [riskByCorridor], getColor: [riskByCorridor] },
      }));

    }

    const selected = risks.filter((r) => r.id === selectedCorridor && CORRIDOR_GEO[r.id]);
    if (selected.length) {
      L.push(new ScatterplotLayer({
        id: 'selected-corridor', data: selected,
        getPosition: (r: CorridorRisk) => CORRIDOR_GEO[r.id],
        getRadius: (r: CorridorRisk) => 76000 + r.tagged.value.index * 2100,
        getLineColor: [232, 239, 247, 245], getFillColor: [0, 0, 0, 0],
        stroked: true, filled: false, lineWidthMinPixels: 2, radiusUnits: 'meters',
      }));
    }

    return L;
  }, [tankers, routes, risks, network, toggles, countries, supplierRisk, riskByCorridor, selectedCorridor, onSelectCorridor]);

  const hasSim = tankers.some((t) => t.source === 'sim');

  return (
    <div className="relative flex-1 h-full">
      <DeckGL key={theatre} initialViewState={VIEW_BY_THEATRE[theatre]} controller layers={layers}
        getTooltip={({ object }: any) =>
          object && (object.name || object.id) && {
            html: `<div style="font-family:'IBM Plex Mono';font-size:11px">${object.name || object.id}${object.ship_type ? ' · ' + object.ship_type : ''}${object.source === 'sim' ? ' · SIM' : ''}</div>`,
            style: { background: '#0E1622', color: '#E8EFF7', border: '1px solid #2C405A', borderRadius: '2px', padding: '4px 6px' },
          }}>
        <Map reuseMaps attributionControl={false} mapStyle={OFFLINE_STYLE} />
      </DeckGL>

      {hasSim && (
        <div className="absolute top-3 right-3">
          <span className="inline-flex items-center gap-1 font-mono text-2xs font-semibold uppercase tracking-badge px-1.5 py-0.5 rounded-sm border"
            style={{ color: SIM, borderColor: SIM, background: 'var(--hm-sim-dim)' }}>
            ● SIM AUGMENTED
          </span>
        </div>
      )}

      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-3 px-3 h-8 bg-bg-1 border border-line-2 rounded pointer-events-none shadow-xl">
        <span className="hm-num text-2xs text-text-2"><span className="text-accent">◆</span> REFINERY</span>
        <span className="hm-num text-2xs text-text-2"><span className="text-sim">▲</span> SPR</span>
        <span className="hm-num text-2xs text-text-2"><span style={{ color: '#54B5FF' }}>■</span> PORT</span>
        <span className="hm-num text-2xs text-text-3">ROUTES · STRATEGIC PLANNING ESTIMATES</span>
      </div>
    </div>
  );
}
