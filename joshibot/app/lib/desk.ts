import { useCallback, useEffect, useRef, useState } from "react";

import {
  EVENTS_PATH,
  PERFORMANCE_PATH,
  POLICIES_PATH,
  SNAPSHOT_PATH,
  TRADES_PATH,
  load,
  loadEvents,
  loadPerformance,
  loadPolicies,
  loadSnapshot,
  loadTrades,
  type Loaded,
} from "./api";
import { loadIntelligence } from "./intelligence";
import { loadNetmap, type NetMapLoad } from "./netmap";
import { clockOf, type Clock, type Origin } from "./measure";
import type {
  EventRow,
  IntelligenceSnapshot,
  Performance,
  Policy,
  Snapshot,
  TradeRow,
} from "./types";

export const FEE_TANK_SOL = 0.02;

/** Fast plane: the protection loop's own state. */
const FAST_MS = 4_000;
/** Slow plane: history and aggregates that do not move every cycle. */
const SLOW_MS = 15_000;

export type Desk = {
  snapshot: Loaded<Snapshot>;
  policies: Loaded<{ items: Policy[]; can_execute: false }>;
  performance: Loaded<Performance>;
  events: Loaded<{ items: EventRow[] }>;
  trades: Loaded<{ items: TradeRow[] }>;
  intel: IntelligenceSnapshot | null;
  netmap: NetMapLoad;
  now: number;
  refresh: () => void;
  refreshNetmap: () => void;
  netmapLoading: boolean;
};

export function useDesk(): Desk {
  const [snapshot, setSnapshot] = useState<Loaded<Snapshot>>({
    state: "loading",
    source: SNAPSHOT_PATH,
  });
  const [policies, setPolicies] = useState<Loaded<{ items: Policy[]; can_execute: false }>>({
    state: "loading",
    source: POLICIES_PATH,
  });
  const [performance, setPerformance] = useState<Loaded<Performance>>({
    state: "loading",
    source: PERFORMANCE_PATH,
  });
  const [events, setEvents] = useState<Loaded<{ items: EventRow[] }>>({
    state: "loading",
    source: EVENTS_PATH,
  });
  const [trades, setTrades] = useState<Loaded<{ items: TradeRow[] }>>({
    state: "loading",
    source: TRADES_PATH,
  });
  const [intel, setIntel] = useState<IntelligenceSnapshot | null>(null);
  const [netmap, setNetmap] = useState<NetMapLoad>({ state: "loading" });
  const [netmapLoading, setNetmapLoading] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const mounted = useRef(true);

  const refreshFast = useCallback(async () => {
    const [snap, pol] = await Promise.all([
      load(loadSnapshot, SNAPSHOT_PATH),
      load(loadPolicies, POLICIES_PATH),
    ]);
    if (!mounted.current) return;
    setSnapshot(snap);
    setPolicies(pol);
  }, []);

  const refreshSlow = useCallback(async () => {
    const [perf, ev, tr, intelligence] = await Promise.all([
      load(loadPerformance, PERFORMANCE_PATH),
      load(() => loadEvents(300), EVENTS_PATH),
      load(() => loadTrades(300), TRADES_PATH),
      loadIntelligence(),
    ]);
    if (!mounted.current) return;
    setPerformance(perf);
    setEvents(ev);
    setTrades(tr);
    setIntel(intelligence);
  }, []);

  const refreshNetmap = useCallback(async () => {
    setNetmapLoading(true);
    const next = await loadNetmap();
    if (!mounted.current) return;
    setNetmap(next);
    setNetmapLoading(false);
  }, []);

  const refresh = useCallback(() => {
    void refreshFast();
    void refreshSlow();
  }, [refreshFast, refreshSlow]);

  useEffect(() => {
    mounted.current = true;
    // Deferred by a tick so the first paint is the loading state rather than a
    // synchronous cascade out of the effect body.
    const kickoff = window.setTimeout(() => {
      void refreshFast();
      void refreshSlow();
      void refreshNetmap();
    }, 0);
    const fast = window.setInterval(() => void refreshFast(), FAST_MS);
    const slow = window.setInterval(() => void refreshSlow(), SLOW_MS);
    const clock = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      mounted.current = false;
      window.clearTimeout(kickoff);
      window.clearInterval(fast);
      window.clearInterval(slow);
      window.clearInterval(clock);
    };
  }, [refreshFast, refreshSlow, refreshNetmap]);

  return {
    snapshot,
    policies,
    performance,
    events,
    trades,
    intel,
    netmap,
    now,
    refresh,
    refreshNetmap: () => void refreshNetmap(),
    netmapLoading,
  };
}

export function snapshotOf(loaded: Loaded<Snapshot>): Snapshot | null {
  return loaded.state === "ok" ? loaded.fetched.data : null;
}

/**
 * The clock pair for anything served inside a snapshot: the engine's own
 * `generated_at` is the closest thing to event time it publishes, and the
 * browser's receipt is ingest time.
 */
export function snapshotClock(loaded: Loaded<Snapshot>): Clock {
  if (loaded.state !== "ok") return clockOf(null, null);
  return clockOf(loaded.fetched.data.generated_at, loaded.fetched.receivedAt);
}

export function loadedClock<T>(loaded: Loaded<T>, eventAt?: string | null): Clock {
  if (loaded.state !== "ok") return clockOf(null, null);
  return clockOf(eventAt ?? null, loaded.fetched.receivedAt);
}

export function originOf<T>(
  loaded: Loaded<T>,
  path: string,
  clock: Clock,
  extra: Partial<Origin> = {},
): Origin {
  return {
    source: loaded.state === "loading" ? loaded.source : loaded.state === "error" ? loaded.source : loaded.fetched.source,
    path,
    kind: "served",
    clock,
    ...extra,
  };
}

export type GateLamp = {
  id: string;
  label: string;
  closed: boolean;
  detail: string;
};

/**
 * The three live gates. All must be open before a sell can exist, and this UI
 * can open none of them — it has no route that touches any.
 */
export function gateLamps(failures: string[]): GateLamp[] {
  const text = failures.join(" · ").toLowerCase();
  return [
    {
      id: "enabled",
      label: "execution.enabled",
      closed: text.includes("execution.enabled"),
      detail: "config.yaml execution.enabled is false. Set in the file the sentinel reads at boot.",
    },
    {
      id: "live",
      label: "--live",
      closed: text.includes("--live"),
      detail: "The sentinel process was not started with --live. Process argv, not config.",
    },
    {
      id: "arm",
      label: "arm file",
      closed: text.includes("arm file") || text.includes("live arm"),
      detail: "The 0600 arm file is absent or its pubkey does not match the loaded signer.",
    },
  ];
}

export function feeTank(sol: number | null): "ok" | "low" | "empty" | "unknown" {
  if (sol == null) return "unknown";
  if (sol <= 0) return "empty";
  if (sol < FEE_TANK_SOL) return "low";
  return "ok";
}

export function protectionTone(state: string | undefined): "ok" | "warn" | "bad" {
  if (state === "LIVE_ARMED") return "ok";
  if (state === "DRY_RUN") return "warn";
  if (state === "DEGRADED" || state === "DOWN") return "bad";
  return "warn";
}

export function policyFor(policies: Policy[], mint: string): Policy | undefined {
  return policies.find((policy) => policy.mint === mint);
}

export function policiesOf(loaded: Loaded<{ items: Policy[]; can_execute: false }>): Policy[] {
  return loaded.state === "ok" ? loaded.fetched.data.items : [];
}

/**
 * Entry unit price from a policy, or null.
 *
 * Returns null rather than guessing. A basis stamped from the current exit quote
 * makes PnL start at 0% regardless of what was paid, which fired every stop
 * below an already-fallen price; the absence of a basis is displayed, never
 * filled in.
 */
export function entryUnitPrice(
  policy: Policy | undefined,
  uiAmount: string | null | undefined,
): number | null {
  if (!policy) return null;
  if (policy.buy_price_sol != null && policy.buy_price_sol > 0) return policy.buy_price_sol;
  const amount = uiAmount == null ? null : Number(uiAmount);
  if (
    policy.cost_basis_sol != null &&
    policy.cost_basis_sol > 0 &&
    amount != null &&
    Number.isFinite(amount) &&
    amount > 0
  ) {
    return policy.cost_basis_sol / amount;
  }
  return null;
}

/**
 * A switched-off exit reads as a rule ("no SL"), never as a blank or a zero. The operator
 * has to be able to see at a glance that a bag is meant to be held.
 */
export function policyRuleLabel(policy: Policy | undefined): string {
  if (!policy) return "observe-only";
  const stop = policy.stop_loss_pct == null ? "no SL" : `SL ${policy.stop_loss_pct}%`;
  const take = policy.take_profit_pct == null ? "no TP" : `arm +${policy.take_profit_pct}%`;
  const runner =
    policy.runner_tightness == null ? "no runner" : `runner ${policy.runner_tightness}`;
  return `${stop} · ${take} · ${runner}`;
}
