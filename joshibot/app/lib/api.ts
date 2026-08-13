import type {
  CandleBar,
  Performance,
  Policy,
  ProtectUnmonitoredRequest,
  ProtectUnmonitoredResult,
  Snapshot,
  UnmonitoredRow,
} from "./types";

const YAML_ONLY_THRESHOLDS = {
  stop_loss_pct: -30,
  take_profit_pct: 100,
  trailing_stop_pct: 20,
  rug_exit: true,
  exit_style: "runner" as const,
};

function quotedExitSol(value: string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return parsed;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export function loadSnapshot() {
  return getJson<Snapshot>("/api/snapshot");
}

export function loadPolicies() {
  return getJson<{ items: Policy[] }>("/api/policies");
}

async function policyError(response: Response, fallback: string) {
  const detail = await response.json().catch(() => ({ detail: response.statusText }));
  throw new Error(typeof detail.detail === "string" ? detail.detail : fallback);
}

export async function savePolicy(mint: string, body: Omit<Policy, "mint">) {
  const response = await fetch(`/api/policies/${mint}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) await policyError(response, "policy save failed");
  return (await response.json()) as { item: Policy; items: Policy[] };
}

export async function protectUnmonitored(
  body: ProtectUnmonitoredRequest,
  fallbackRows: UnmonitoredRow[] = [],
): Promise<ProtectUnmonitoredResult> {
  const payload = {
    mode: body.mode,
    stop_loss_pct: body.stop_loss_pct ?? YAML_ONLY_THRESHOLDS.stop_loss_pct,
    take_profit_pct: body.take_profit_pct ?? YAML_ONLY_THRESHOLDS.take_profit_pct,
    trailing_stop_pct: body.trailing_stop_pct ?? YAML_ONLY_THRESHOLDS.trailing_stop_pct,
    rug_exit: body.rug_exit ?? YAML_ONLY_THRESHOLDS.rug_exit,
    exit_style: body.exit_style ?? YAML_ONLY_THRESHOLDS.exit_style,
  };
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
  body: {
    stop_loss_pct: number;
    take_profit_pct: number;
    trailing_stop_pct: number;
    rug_exit: boolean;
    exit_style: "runner" | "fixed_trail";
  },
  rows: UnmonitoredRow[],
): Promise<ProtectUnmonitoredResult> {
  const created: string[] = [];
  const skipped: { mint: string; reason: string }[] = [];
  let items: Policy[] = [];
  for (const row of rows) {
    const cost_basis_sol = quotedExitSol(row.exit_sol);
    if (cost_basis_sol == null) {
      skipped.push({ mint: row.mint, reason: "missing or non-positive exit_sol" });
      continue;
    }
    const saved = await savePolicy(row.mint, {
      name: row.name,
      cost_basis_sol,
      stop_loss_pct: body.stop_loss_pct,
      take_profit_pct: body.take_profit_pct,
      trailing_stop_pct: body.trailing_stop_pct,
      rug_exit: body.rug_exit,
      dispose_after_break_even: false,
      exit_style: body.exit_style,
    });
    created.push(row.mint);
    items = saved.items;
  }
  return { created, skipped, items, can_execute: false };
}

export async function deletePolicy(mint: string) {
  const response = await fetch(`/api/policies/${mint}`, { method: "DELETE", credentials: "same-origin" });
  if (!response.ok) throw new Error("policy delete failed");
}

export function loadEvents() {
  return getJson<{ items: { timestamp: string; severity: string; category: string; message: string }[] }>("/api/events?limit=200");
}

export function loadTrades() {
  return getJson<{ items: { timestamp: string; mint: string; name: string; reason: string; output_lamports: string; signature: string }[] }>("/api/trades?limit=200");
}

export function loadPerformance() {
  return getJson<Performance>("/api/performance");
}

export function loadCandles(mint: string, interval = "15m") {
  return getJson<{
    mint: string;
    interval: string;
    bars: CandleBar[];
    source: string;
    dex?: string;
    stats?: Record<string, number | null>;
  }>(`/api/candles?mint=${encodeURIComponent(mint)}&interval=${interval}&limit=120`);
}
