import type {
  CandlePayload,
  Health,
  Performance,
  Policy,
  ProtectUnmonitoredRequest,
  ProtectUnmonitoredResult,
  Snapshot,
  EventRow,
  TradeRow,
  UnmonitoredRow,
} from "./types";

/**
 * Every read carries the browser's own ingest clock and the endpoint it came
 * from, so a figure can name its producer and when THIS page learned it. The
 * server's `generated_at` is a separate, earlier clock; both are shown.
 */
export type Fetched<T> = {
  data: T;
  source: string;
  /** Browser ingest time — when this tab received the bytes. */
  receivedAt: string;
  latencyMs: number;
};

export type Loaded<T> =
  | { state: "ok"; fetched: Fetched<T> }
  | { state: "error"; source: string; error: string; receivedAt: string }
  | { state: "loading"; source: string };

async function getJson<T>(path: string): Promise<Fetched<T>> {
  const started = performance.now();
  const response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  const data = (await response.json()) as T;
  return {
    data,
    source: path,
    receivedAt: new Date().toISOString(),
    latencyMs: Math.round(performance.now() - started),
  };
}

export async function load<T>(fn: () => Promise<Fetched<T>>, source: string): Promise<Loaded<T>> {
  try {
    return { state: "ok", fetched: await fn() };
  } catch (error) {
    return {
      state: "error",
      source,
      error: error instanceof Error ? error.message : "request failed",
      receivedAt: new Date().toISOString(),
    };
  }
}

export const SNAPSHOT_PATH = "/api/snapshot";
export const POLICIES_PATH = "/api/policies";
export const EVENTS_PATH = "/api/events";
export const TRADES_PATH = "/api/trades";
export const PERFORMANCE_PATH = "/api/performance";
export const CANDLES_PATH = "/api/candles";
export const HEALTH_PATH = "/api/health";

export function loadSnapshot() {
  return getJson<Snapshot>(SNAPSHOT_PATH);
}

export function loadPolicies() {
  return getJson<{ items: Policy[]; can_execute: false }>(POLICIES_PATH);
}

export function loadHealth() {
  return getJson<Health>(HEALTH_PATH);
}

export function loadEvents(limit = 300) {
  return getJson<{ items: EventRow[] }>(`${EVENTS_PATH}?limit=${limit}`);
}

export function loadTrades(limit = 300) {
  return getJson<{ items: TradeRow[] }>(`${TRADES_PATH}?limit=${limit}`);
}

export function loadPerformance() {
  return getJson<Performance>(PERFORMANCE_PATH);
}

export function loadCandles(mint: string, interval = "15m", limit = 200) {
  return getJson<CandlePayload>(
    `${CANDLES_PATH}?mint=${encodeURIComponent(mint)}&interval=${interval}&limit=${limit}`,
  );
}

async function policyError(response: Response, fallback: string) {
  const detail = await response.json().catch(() => ({ detail: response.statusText }));
  throw new Error(typeof detail.detail === "string" ? detail.detail : fallback);
}

/**
 * Writes a rule into config.yaml. This is the ONLY class of mutation the browser
 * can cause, and it is a policy write, not an order: the sentinel reads the rule
 * on its own cycle and decides for itself. No key, no signature, no submission
 * ever crosses into this process.
 */
export type PolicyWrite = Partial<Omit<Policy, "mint">> & { name: string };

/**
 * A field left out is a field the sentinel fills in from its own PolicyDefaults; a field
 * sent as `null` is an exit switched off. Both are deliberate, and they are different.
 */
export async function savePolicy(mint: string, body: PolicyWrite) {
  const response = await fetch(`/api/policies/${mint}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) await policyError(response, "policy save failed");
  return (await response.json()) as { item: Policy; items: Policy[]; can_execute: false };
}

export async function protectUnmonitored(
  body: ProtectUnmonitoredRequest,
  fallbackRows: UnmonitoredRow[] = [],
): Promise<ProtectUnmonitoredResult> {
  // Only what the operator actually chose. A threshold the browser leaves out is filled in
  // by the sentinel's PolicyDefaults -- the browser used to carry its own copy of -30/100/20,
  // which is one of the six places this project wrote the same rule down differently.
  const payload: Record<string, unknown> = { mode: body.mode };
  for (const key of [
    "stop_loss_pct",
    "take_profit_pct",
    "runner_tightness",
    "rug_exit",
  ] as const) {
    if (key in body) payload[key] = body[key];
  }
  const response = await fetch("/api/policies/protect-unmonitored", {
    method: "post",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.status === 404 || response.status === 405) {
    return protectUnmonitoredFallback(payload, fallbackRows);
  }
  if (!response.ok) await policyError(response, "protect unmonitored failed");
  return (await response.json()) as ProtectUnmonitoredResult;
}

async function protectUnmonitoredFallback(
  body: Record<string, unknown>,
  rows: UnmonitoredRow[],
): Promise<ProtectUnmonitoredResult> {
  const created: string[] = [];
  const skipped: { mint: string; reason: string }[] = [];
  let items: Policy[] = [];
  for (const row of rows) {
    // No cost basis is sent. Stamping the current exit quote as basis made PnL
    // start at 0% regardless of what was paid, so every stop fired below the
    // coin's already-fallen price. The policy is created without a basis and is
    // rug-only until the engine reconstructs the real one from observed buys.
    const thresholds = { ...body };
    delete thresholds.mode;
    const saved = await savePolicy(row.mint, { name: row.name, ...thresholds });
    created.push(row.mint);
    items = saved.items;
  }
  return { created, skipped, items, can_execute: false };
}

export async function deletePolicy(mint: string) {
  const response = await fetch(`/api/policies/${mint}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("policy delete failed");
}
