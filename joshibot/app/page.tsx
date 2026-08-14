import {
  Activity,
  CandlestickChart,
  CircuitBoard,
  Gauge,
  History as HistoryIcon,
  Radar,
  Shield,
} from "lucide-react";
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { Lamp, StatusPill } from "@/components/instrument";
import { NowProvider } from "@/components/now";
import { TooltipProvider } from "@/components/ui/tooltip";
import { gateLamps, protectionTone, snapshotOf, useDesk } from "@/lib/desk";
import { cn, relativeAge, shortAddress } from "@/lib/format";
import type { ViewId } from "@/lib/types";
import { Circuit } from "@/views/circuit";
import { History } from "@/views/history";
import { Intelligence } from "@/views/intelligence";
import { Markets } from "@/views/markets";
import { Overview } from "@/views/overview";
import { Performance } from "@/views/performance";
import { Positions } from "@/views/positions";

const NAV: { id: ViewId; label: string; hint: string; icon: typeof Gauge }[] = [
  { id: "desk", label: "Desk", hint: "1", icon: Gauge },
  { id: "bags", label: "Positions", hint: "2", icon: Shield },
  { id: "chart", label: "Price", hint: "3", icon: CandlestickChart },
  { id: "circuit", label: "Circuit", hint: "4", icon: CircuitBoard },
  { id: "tape", label: "Tape", hint: "5", icon: HistoryIcon },
  { id: "ledger", label: "Ledger", hint: "6", icon: Activity },
  { id: "wire", label: "Wire", hint: "7", icon: Radar },
];

const VIEW_IDS = new Set<ViewId>(NAV.map((item) => item.id));

function parseHash(hash: string): { view: ViewId; selectedMint: string | null } {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw) return { view: "desk", selectedMint: null };
  const slash = raw.indexOf("/");
  const id = (slash === -1 ? raw : raw.slice(0, slash)) as ViewId;
  const rest = slash === -1 ? "" : raw.slice(slash + 1);
  const view = VIEW_IDS.has(id) ? id : "desk";
  return { view, selectedMint: view === "chart" && rest ? rest : null };
}

function hashFor(view: ViewId, mint?: string | null) {
  return mint ? `#${view}/${mint}` : `#${view}`;
}

function subscribeHash(onStoreChange: () => void) {
  window.addEventListener("hashchange", onStoreChange);
  return () => window.removeEventListener("hashchange", onStoreChange);
}

const getHash = () => window.location.hash;
const getServerHash = () => "";

export default function Home() {
  const hash = useSyncExternalStore(subscribeHash, getHash, getServerHash);
  const { view, selectedMint } = parseHash(hash);
  const desk = useDesk();
  const snapshot = snapshotOf(desk.snapshot);

  const go = useCallback((next: ViewId, mint?: string | null) => {
    window.location.hash = hashFor(next, mint);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      const index = Number(event.key) - 1;
      if (index >= 0 && index < NAV.length) {
        event.preventDefault();
        go(NAV[index].id);
      }
      if (event.key === "r" || event.key === "R") {
        event.preventDefault();
        desk.refresh();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, desk]);

  const system = snapshot?.system;
  const gates = gateLamps(system?.gate_failures ?? []);
  const closed = gates.filter((gate) => gate.closed).length;
  const unprotected = snapshot?.unmonitored.length ?? 0;

  return (
    <NowProvider value={desk.now}>
    <TooltipProvider delayDuration={120} skipDelayDuration={300}>
      <div className="flex min-h-svh flex-col">
        <header className="sticky top-0 z-40 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-background/95 px-4 py-2 backdrop-blur">
          <div className="flex items-center gap-2">
            <Lamp
              tone={protectionTone(system?.protection_state)}
              live={Boolean(system?.running)}
              title={system?.protection_state}
            />
            <span className="font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              shitcoims
              <span className="text-muted-foreground">/console</span>
            </span>
          </div>

          <nav className="flex flex-wrap items-center gap-0.5">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = view === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => go(item.id)}
                  className={cn(
                    "flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] uppercase tracking-wider",
                    active
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="size-3.5" />
                  {item.label}
                  <span className="text-[9px] opacity-50">{item.hint}</span>
                </button>
              );
            })}
          </nav>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {desk.snapshot.state === "error" && (
              <StatusPill
                label="api down"
                tone="bad"
                help="The sentinel is not answering. Nothing on screen is current."
              />
            )}
            {system && (
              <>
                <StatusPill
                  label={system.protection_state}
                  tone={protectionTone(system.protection_state)}
                />
                <StatusPill
                  label={closed === 0 ? "gates open" : `${closed}/3 closed`}
                  tone={closed === 0 ? "warn" : "ok"}
                  help={
                    closed === 0
                      ? "All three live gates are open: the sentinel can sign and submit sell-only exits on its own cycle. This console still cannot."
                      : `${closed} gate(s) closed — no sell can be constructed.`
                  }
                />
                {unprotected > 0 && (
                  <StatusPill label={`${unprotected} unprotected`} tone="bad" />
                )}
                <span className="font-mono text-[10px] text-muted-foreground">
                  cycle {relativeAge(system.last_cycle_at, desk.now)}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {shortAddress(system.wallet_address, 4, 4)}
                </span>
              </>
            )}
            <StatusPill
              label="view only"
              tone="idle"
              help="This browser holds no key, signs nothing, and submits nothing. Its only write is a policy rule into config.yaml, which the sentinel reads on its own cycle and is free to ignore."
            />
            <button
              type="button"
              onClick={desk.refresh}
              className="rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider hover:bg-muted"
            >
              refresh
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 p-3">
          {view === "desk" && (
            <Overview snapshot={desk.snapshot} now={desk.now} onChanged={desk.refresh} />
          )}
          {view === "bags" && (
            <Positions
              snapshot={desk.snapshot}
              policies={desk.policies}
              now={desk.now}
              onChanged={desk.refresh}
              onChart={(mint) => go("chart", mint)}
            />
          )}
          {view === "chart" && (
            <Markets
              snapshot={desk.snapshot}
              selectedMint={selectedMint}
              onSelect={(mint) => go("chart", mint)}
            />
          )}
          {view === "circuit" && (
            <Circuit
              netmap={desk.netmap}
              now={desk.now}
              onRefresh={desk.refreshNetmap}
              loading={desk.netmapLoading}
            />
          )}
          {view === "tape" && (
            <History events={desk.events} trades={desk.trades} now={desk.now} />
          )}
          {view === "ledger" && (
            <Performance performance={desk.performance} trades={desk.trades} now={desk.now} />
          )}
          {view === "wire" && <Intelligence intel={desk.intel} now={desk.now} />}
        </main>

        <footer className="border-t border-border px-4 py-1.5">
          <p className="font-mono text-[10px] text-muted-foreground">
            1–7 switch view · R refresh · hover any figure for its source, both clocks, sample size
            and caveats
          </p>
        </footer>
      </div>
    </TooltipProvider>
    </NowProvider>
  );
}
