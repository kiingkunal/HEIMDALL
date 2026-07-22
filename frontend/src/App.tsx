import React from 'react';
import { useHeimdall } from './state';
import { WarMap, LayerToggles } from './components/WarMap';
import { RightRail } from './components/RightRail';
import { BottomDock } from './components/BottomDock';
import { TopBar } from './components/TopBar';
import type { TheatreId } from './components/TopBar';
import { SituationBar } from './components/SituationBar';
import { LeftPanel } from './components/LeftPanel';
import { Drawer } from './components/Drawer';
import { BottomRail } from './components/BottomRail';

export function App() {
  const { s, recompute, selectCorridor, openDrawer, setMode, setReplayTime, patch } = useHeimdall();
  const [toggles, setToggles] = React.useState<LayerToggles>({
    countries: true, halos: true, arcs: true, tankers: true, labels: true,
    ports: true, refineries: true, spr: true,
  });
  const [selectedTanker, setSelectedTanker] = React.useState<any>(null);
  const [theatre, setTheatre] = React.useState<TheatreId>('arabian');
  const toggle = (k: keyof LayerToggles) => setToggles((t) => ({ ...t, [k]: !t[k] }));
  const synthetic = s.tankers.some((t) => t.source === 'sim');

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key.toLowerCase() === 's') openDrawer('scenario');
      if (e.key.toLowerCase() === 'p') openDrawer('plans');
      if (e.key.toLowerCase() === 'r') setMode(s.mode === 'LIVE' ? 'REPLAY' : 'LIVE');
      if (e.key === 'Escape') patch({ drawer: null, selectedCorridor: null });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [s.mode, openDrawer, setMode, patch]);

  return (
    <div className="h-full w-full flex flex-col bg-bg-0">
      <TopBar mode={s.mode} onMode={setMode} online={s.online}
        resilience={s.resilience} risks={s.risks} tankerCount={s.tankers.length}
        theatre={theatre} onTheatre={setTheatre}
        onScenario={() => openDrawer('scenario')} onPlans={() => openDrawer('plans')} />
      <SituationBar mode={s.mode} risks={s.risks} playbook={s.playbook} solving={s.solving}
        intelligence={s.intelligence} aisStatus={s.aisStatus}
        replayTime={s.replayFrame?.value?.sim_now}
        onDetect={() => s.risks[0] && selectCorridor([...s.risks].sort((a, b) => b.tagged.value.index - a.tagged.value.index)[0].id)}
        onScenario={() => openDrawer('scenario')} onAllocate={() => openDrawer('plans')}
        onPlans={() => openDrawer('plans')} onAuthorise={() => openDrawer('packet')} />

      <div className="flex-1 flex relative min-h-0">
        <WarMap tankers={s.tankers} routes={s.routes} risks={s.risks} network={s.network} toggles={toggles}
          theatre={theatre}
          selectedCorridor={s.selectedCorridor}
          onSelectCorridor={(id) => selectCorridor(id)}
          onSelectTanker={setSelectedTanker} />
        <LeftPanel toggles={toggles} onToggle={toggle}
          tankerCount={s.tankers.length} synthetic={synthetic}
          aisStatus={s.aisStatus}
          selectedTanker={selectedTanker} onCloseTanker={() => setSelectedTanker(null)}
          networkCounts={{
            ports: s.network.ports.filter((p: any) => !p.is_load_port).length,
            refineries: s.network.refineries.length, spr: s.network.spr.length,
          }} />
        <RightRail
          risks={s.risks} resilience={s.resilience} playbook={s.playbook}
          intelligence={s.intelligence}
          selectedCorridor={s.selectedCorridor} scenario={s.scenario}
          onSelectCorridor={(id) => selectCorridor(id)}
          onOpenPlaybook={() => openDrawer('plans')}
          onOpenScenario={() => openDrawer('scenario')} />
        <Drawer
          open={s.drawer !== null} mode={s.drawer} playbook={s.playbook}
          scenario={s.scenario} selectedCorridor={s.selectedCorridor}
          onScenario={(sc) => recompute(sc)}
          solving={s.solving}
          onPlans={() => openDrawer('plans')}
          onClose={() => { patch({ drawer: null, selectedCorridor: null }); }} />

        {s.loading && (
          <div className="absolute inset-0 z-30 bg-bg-0/85 backdrop-blur-sm grid place-items-center">
            <div className="text-center">
              <div className="hm-num text-accent text-sm tracking-[.2em] animate-pulse">INITIALISING WAR ROOM</div>
              <div className="hm-num text-2xs text-text-3 mt-2">CONNECTING SIGNALS · TWIN · SOLVER</div>
            </div>
          </div>
        )}
      </div>

      <BottomDock risks={s.risks} routes={s.routes} playbook={s.playbook} scenario={s.scenario}
        mode={s.mode} replayFrame={s.replayFrame}
        onOpenPlaybook={() => openDrawer('plans')} />
      {s.mode === 'REPLAY' && <BottomRail onReplayTime={setReplayTime} />}

      {s.error && (
        <div aria-live="polite" className="fixed bottom-14 left-1/2 -translate-x-1/2 z-50 px-3 py-2 bg-alert-dim border border-alert rounded-sm hm-num text-2xs text-alert shadow-2xl">
          {s.error}
        </div>
      )}
    </div>
  );
}
