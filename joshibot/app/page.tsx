import { Activity, CandlestickChart, Gauge, History as HistoryIcon, Radar, Shield } from "lucide-react";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { Lamp } from "@/components/desk";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { loadPolicies, loadSnapshot } from "@/lib/api";
import { deskBags, feeTank, gateLamps, parseSol, protectionTone } from "@/lib/desk";
import { loadIntelligence } from "@/lib/intelligence";
import type { IntelligenceSnapshot, Policy, Snapshot, ViewId } from "@/lib/types";
import { age, cn, number, shortAddress } from "@/lib/utils";
import { History } from "@/views/history";
import { Intelligence } from "@/views/intelligence";
import { Markets } from "@/views/markets";
import { Overview } from "@/views/overview";
import { Performance } from "@/views/performance";
import { Positions } from "@/views/positions";

const NAV: { id: ViewId; label: string; hint: string; icon: typeof Gauge }[] = [
  { id: "overview", label: "Watch", hint: "1", icon: Gauge },
  { id: "positions", label: "Bags", hint: "2", icon: Shield },
  { id: "markets", label: "Chart", hint: "3", icon: CandlestickChart },
  { id: "intelligence", label: "Wire", hint: "4", icon: Radar },
  { id: "history", label: "Tape", hint: "5", icon: HistoryIcon },
  { id: "performance", label: "Ledger", hint: "6", icon: Activity },
];

const VIEW_IDS = new Set<ViewId>(NAV.map((item) => item.id));

function parseHash(hash: string): { view: ViewId; selectedMint: string | null } {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw) return { view: "overview", selectedMint: null };
  const slash = raw.indexOf("/");
  const id = (slash === -1 ? raw : raw.slice(0, slash)) as ViewId;
  const rest = slash === -1 ? "" : raw.slice(slash + 1);
  const view = VIEW_IDS.has(id) ? id : "overview";
  const selectedMint = view === "markets" && rest ? rest : null;
  return { view, selectedMint };
}

function hashFor(view: ViewId, mint?: string | null) {
  return mint ? `#${view}/${mint}` : `#${view}`;
}

function subscribeHash(onStoreChange: () => void) {
  window.addEventListener("hashchange", onStoreChange);
  return () => window.removeEventListener("hashchange", onStoreChange);
}

function getHash() {
  return window.location.hash;
}

function getServerHash() {
  return "";
}

export default function Home() {
  const hash = useSyncExternalStore(subscribeHash, getHash, getServerHash);
  const { view, selectedMint } = parseHash(hash);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [intel, setIntel] = useState<IntelligenceSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const [copied, setCopied] = useState(false);

  const go = useCallback((next: ViewId, mint?: string | null) => {
    window.location.hash = hashFor(next, mint);
  }, []);

  const refresh = useCallback(async () => {
    const [sentinel, policyPage, intelligence] = await Promise.allSettled([
      loadSnapshot(),
      loadPolicies(),
      loadIntelligence(),
    ]);
    if (sentinel.status === "fulfilled") {
      setSnapshot(sentinel.value);
      setError(null);
    } else {
      setError("local API unavailable");
    }
    if (policyPage.status === "fulfilled") setPolicies(policyPage.value.items);
    if (intelligence.status === "fulfilled") setIntel(intelligence.value);
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      setNow(Date.now());
      void refresh();
    }, 0);
    const poll = window.setInterval(() => void refresh(), 4_000);
    const clock = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      window.clearTimeout(kickoff);
      window.clearInterval(poll);
      window.clearInterval(clock);
    };
  }, [refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < NAV.length) {
        event.preventDefault();
        go(NAV[index].id);
      }
      if (event.key === "r" || event.key === "R") {
        event.preventDefault();
        void refresh();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, refresh]);

  const system = snapshot?.system;
  const bags = deskBags(snapshot);
  const unprotected = snapshot?.unmonitored.length ?? 0;
  const tank = feeTank(snapshot?.wallet.sol);
  const gatesClosed = gateLamps(system?.gate_failures ?? []).filter((gate) => gate.closed).length;
  const tone = protectionTone(system?.protection_state);

  return (
    <div className="flex min-h-svh">
      <aside className="flex w-60 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <div className="px-5 pb-4 pt-6">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.22em] text-primary/80">Local night watch</p>
          <h1 className="font-display mt-1 text-[1.65rem] font-medium leading-none">
            shitcoims
            <span className="text-muted-foreground"> / sentinel</span>
          </h1>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 px-3">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = view === item.id;
            return (
              <Button
                key={item.id}
                variant="ghost"
                className={cn(
                  "h-10 justify-start gap-3 rounded-lg px-3 font-medium",
                  active && "bg-sidebar-accent text-sidebar-accent-foreground",
                )}
                onClick={() => go(item.id)}
              >
                <Icon className={cn("size-4", active ? "text-primary" : "text-muted-foreground")} />
                <span>{item.label}</span>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground/70">{item.hint}</span>
              </Button>
            );
          })}
        </nav>
        <div className="space-y-3 border-t border-sidebar-border p-4 text-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span>Wallet</span>
            <button
              className="font-mono text-primary"
              onClick={() => {
                if (!system?.wallet_address) return;
                void navigator.clipboard.writeText(system.wallet_address);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1200);
              }}
            >
              {copied ? "copied" : shortAddress(system?.wallet_address ?? "")}
            </button>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Book</span>
            <span className="font-mono tnum">{number(snapshot?.wallet.portfolio_exit_sol, 3)} SOL</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Gas</span>
            <span className={cn("font-mono tnum", tank !== "ok" && "text-lamp-warn")}>
              {number(snapshot?.wallet.sol, 3)}
            </span>
          </div>
          {system?.mode === "live" ? (
            <Badge variant="warning">signer armed</Badge>
          ) : (
            <Badge variant="destructive">CANNOT EXECUTE</Badge>
          )}
          <p className="font-mono text-[10px] text-muted-foreground/70">1–6 to move · R to refresh</p>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-4 border-b px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Lamp tone={tone} live={Boolean(system?.running)} />
            <Badge variant={system?.protection_state === "LIVE_ARMED" ? "default" : tone === "bad" ? "destructive" : "warning"}>
              {system?.protection_state ?? "STARTING"}
            </Badge>
            <span className="truncate text-xs text-muted-foreground">
              {system?.last_cycle_at ? `cycle ${age(system.last_cycle_at, now)}` : "awaiting first sweep"}
              {unprotected > 0 ? ` · ${unprotected} unprotected` : ""}
              {` · ${gatesClosed} gates closed`}
              {parseSol(snapshot?.wallet.sol) != null ? ` · ${number(snapshot?.wallet.sol, 3)} SOL gas` : ""}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden font-mono text-[10px] text-muted-foreground sm:inline">
              {bags.length} bag{bags.length === 1 ? "" : "s"}
            </span>
            <Button size="sm" variant="outline" onClick={() => void refresh()}>
              Refresh
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          {error && (
            <p className="mb-4 text-sm text-destructive">{error}. Start the local Python sentinel on port 8787.</p>
          )}
          {view === "overview" && (
            <Overview snapshot={snapshot} policies={policies} intel={intel} now={now} onChanged={() => void refresh()} onChart={(mint) => go("markets", mint)} onBags={() => go("positions")} />
          )}
          {view === "positions" && (
            <Positions snapshot={snapshot} policies={policies} onChanged={() => void refresh()} onChart={(mint) => go("markets", mint)} />
          )}
          {view === "markets" && <Markets snapshot={snapshot} selectedMint={selectedMint} />}
          {view === "intelligence" && <Intelligence intel={intel} now={now} />}
          {view === "history" && <History now={now} />}
          {view === "performance" && <Performance />}
        </main>
      </div>
    </div>
  );
}
