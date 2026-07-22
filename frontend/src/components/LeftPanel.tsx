import React from 'react';
import { Label, Badge } from './primitives';
import { LayerToggles } from './WarMap';
import { ACCENT, SIM, RISK_HEX } from '../lib/colors';
import { fmt } from '../lib/format';

const LAYER_GROUPS: { title: string; rows: { key: keyof LayerToggles; label: string; glyph: string; color: string }[] }[] = [
  { title: 'RISK & SUPPLY', rows: [
    { key: 'halos', label: 'CORRIDOR RISK', glyph: '◎', color: RISK_HEX.high },
    { key: 'countries', label: 'SUPPLIER EXPOSURE', glyph: '▧', color: RISK_HEX.elev },
    { key: 'arcs', label: 'CRUDE FLOW ROUTES', glyph: '⌁', color: ACCENT },
    { key: 'tankers', label: 'TANKER POSITIONS', glyph: '◈', color: '#8EC5EA' },
  ] },
  { title: 'INDIA ENERGY TWIN', rows: [
    { key: 'refineries', label: 'REFINERIES', glyph: '◆', color: ACCENT },
    { key: 'ports', label: 'IMPORT TERMINALS', glyph: '■', color: '#54B5FF' },
    { key: 'spr', label: 'STRATEGIC RESERVES', glyph: '▲', color: SIM },
    { key: 'labels', label: 'MAP LABELS', glyph: 'Aa', color: '#E6EDEA' },
  ] },
];

function ToggleRow({ row, active, onClick }: {
  row: { label: string; glyph: string; color: string }; active: boolean; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      className="group w-full flex items-center gap-2.5 px-2 h-7 hover:bg-bg-3 transition-colors">
      <span className={`w-3.5 h-3.5 rounded-sm border flex items-center justify-center shrink-0
        ${active ? 'border-accent bg-accent text-bg-0' : 'border-line-2 bg-bg-inset'}`}>
        {active && <span className="text-[9px] font-bold leading-none">✓</span>}
      </span>
      <span className="w-4 hm-num text-2xs text-center" style={{ color: row.color }}>{row.glyph}</span>
      <span className={`hm-num text-2xs flex-1 text-left ${active ? 'text-text-1' : 'text-text-3'}`}>{row.label}</span>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? '' : 'opacity-25'}`} style={{ background: row.color }} />
    </button>
  );
}

export function LeftPanel({
  toggles, onToggle, tankerCount, synthetic, aisStatus, selectedTanker, onCloseTanker, networkCounts,
}: {
  toggles: LayerToggles; onToggle: (k: keyof LayerToggles) => void;
  tankerCount: number; synthetic: boolean;
  aisStatus: any | null;
  selectedTanker: any | null; onCloseTanker: () => void;
  networkCounts: { ports: number; refineries: number; spr: number };
}) {
  const [open, setOpen] = React.useState(true);
  const receiving = !!aisStatus?.stream?.value?.receiving;
  const sourceLabel = receiving ? 'AISSTREAM · RECEIVING'
    : aisStatus?.live_snapshot ? `${String(aisStatus.snapshot_source || 'ais').toUpperCase()} · CACHED SNAPSHOT`
      : 'SIM AUGMENTATION';

  return (
    <>
      <div className="absolute top-3 left-3 z-10">
        {open ? (
          <div className="w-[260px] bg-bg-1 border border-line-2 rounded shadow-2xl">
            <button onClick={() => setOpen(false)}
              className="w-full flex items-center justify-between px-3 h-9 border-b border-line-1 bg-bg-2 hover:bg-bg-3">
              <span className="flex items-center gap-2"><span className="text-accent">▤</span><Label>MAP LAYERS</Label></span>
              <span className="hm-num text-2xs text-text-3">MINIMISE —</span>
            </button>
            <div className="py-1.5">
              {LAYER_GROUPS.map((group, gi) => (
                <div key={group.title} className={gi ? 'border-t border-line-1 mt-1 pt-1' : ''}>
                  <div className="px-3 h-6 flex items-center hm-label !text-2xs">{group.title}</div>
                  {group.rows.map((row) => (
                    <ToggleRow key={row.key} row={row} active={toggles[row.key]}
                      onClick={() => onToggle(row.key)} />
                  ))}
                </div>
              ))}
            </div>
            <div className="border-t border-line-1 px-3 py-3 bg-bg-inset">
              <div className="flex justify-between hm-num text-2xs text-text-3">
                <span>{tankerCount} VESSELS</span>
                <span>{networkCounts.refineries} REFINERIES</span>
                <span>{networkCounts.spr} SPR</span>
              </div>
              <div className={`hm-num text-[9px] mt-1 ${receiving ? 'text-risk-low' : synthetic ? 'text-sim' : 'text-text-3'}`}>{sourceLabel}</div>
              <div className="flex justify-between hm-num text-[9px] text-text-2 mt-3 mb-1">
                <span>LOW</span><span>HIGH</span>
              </div>
              <div className="h-1.5 rounded-sm"
                style={{ background: `linear-gradient(90deg, ${RISK_HEX.low}, ${RISK_HEX.elev}, ${RISK_HEX.high})` }} />
              <div className="hm-num text-[9px] text-text-2 mt-1.5 text-center">CORRIDOR RISK INDEX · NOT A PROBABILITY</div>
            </div>
          </div>
        ) : (
          <button onClick={() => setOpen(true)}
            className="flex items-center gap-2 px-2.5 h-8 bg-bg-1 border border-line-2 rounded hover:border-accent">
            <span className="text-accent text-2xs">▤</span><Label>LAYERS</Label>
            <span className="hm-num text-2xs text-text-2">{tankerCount}</span>
            {synthetic && <span className="hm-num text-2xs" style={{ color: SIM }}>SIM</span>}
          </button>
        )}
      </div>

      {selectedTanker && (
        <div className="absolute top-3 left-[284px] z-10 w-72 bg-bg-1 border border-line-2 rounded shadow-2xl">
          <div className="flex items-center justify-between px-3 h-9 border-b border-line-1 bg-bg-2">
            <Label>VESSEL INTELLIGENCE</Label>
            <button onClick={onCloseTanker} className="text-text-3 text-2xs hover:text-text-1">✕</button>
          </div>
          <div className="p-3 space-y-2">
            <div>
              <div className="hm-num text-sm text-text-1 font-semibold truncate">
                {selectedTanker.name || `MMSI ${selectedTanker.mmsi}`}
              </div>
              <div className="mt-1">
                {selectedTanker.source === 'sim'
                  ? <Badge tone="sim">SIM · SYNTHETIC</Badge>
                  : receiving && selectedTanker.source === 'aisstream'
                    ? <Badge tone="live" dot>LIVE AISSTREAM</Badge>
                    : <Badge tone="stale">AIS SNAPSHOT · {String(selectedTanker.source || 'CACHE').toUpperCase()}</Badge>}
              </div>
            </div>
            <div className="grid grid-cols-[64px_1fr] gap-x-2 gap-y-1 hm-num text-2xs border-t border-line-1 pt-2">
              <span className="text-text-3">TYPE</span><span className="text-text-1 truncate">{selectedTanker.ship_type || '—'}</span>
              <span className="text-text-3">MMSI</span><span className="text-text-1">{selectedTanker.mmsi}</span>
              <span className="text-text-3">SPEED</span><span className="text-text-1">{selectedTanker.sog != null ? `${fmt(selectedTanker.sog, 1)} kt` : '—'}</span>
              <span className="text-text-3">HEADING</span><span className="text-text-1">{selectedTanker.heading != null ? `${fmt(selectedTanker.heading, 0)}°` : '—'}</span>
              <span className="text-text-3">POSITION</span><span className="text-text-1">{fmt(selectedTanker.lat, 2)}, {fmt(selectedTanker.lon, 2)}</span>
              {selectedTanker.corridor && <><span className="text-text-3">ZONE</span>
                <span className="text-text-1 capitalize">{selectedTanker.corridor.replace(/_/g, ' ')}</span></>}
            </div>
            {selectedTanker.source === 'sim' && (
              <div className="text-[10px] leading-4 text-sim border-t border-line-1 pt-2">
                Synthetic augmentation along a real searoute path. Never mixed silently with live AIS.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
