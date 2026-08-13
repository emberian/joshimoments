import type { ExitStyle, Policy, Snapshot } from "./types";

export const FEE_TANK_SOL = 0.02;

export type DeskBag = {
  mint: string;
  name: string;
  ui_amount: string;
  exit_sol: string | null;
  kind: "protected" | "observe";
  pnl_pct: string | null;
  unit_price_sol: string | null;
  trailing_peak_unit_price_sol: string | null;
  trailing_active: boolean;
  exit_style: ExitStyle | null;
  floor_multiple: string | null;
  scale_rungs_fired: string[];
  decision: string;
  decision_reason: string;
  rug_emergency: boolean;
  rug_reason: string | null;
  liquidity_usd: string | null;
  mint_revoked: boolean | null;
  errors: string[];
  stop_live: boolean;
};

export type GateLamp = {
  id: string;
  label: string;
  closed: boolean;
  detail: string;
};

export function parseSol(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function exitStyleOf(value: string | null | undefined): ExitStyle | null {
  if (value === "fixed_trail" || value === "runner") return value;
  return null;
}

export function deskBags(snapshot: Snapshot | null): DeskBag[] {
  if (!snapshot) return [];
  const protectedRows = snapshot.positions.map((row) => ({
    mint: row.mint,
    name: row.name,
    ui_amount: row.ui_amount,
    exit_sol: row.exit_sol ?? null,
    kind: "protected" as const,
    pnl_pct: row.pnl_pct ?? null,
    unit_price_sol: row.unit_price_sol ?? null,
    trailing_peak_unit_price_sol: row.trailing_peak_unit_price_sol ?? null,
    trailing_active: Boolean(row.trailing_active),
    exit_style: exitStyleOf(row.thresholds?.exit_style),
    floor_multiple: row.runner?.floor_multiple ?? null,
    scale_rungs_fired: row.runner?.scale_rungs_fired ?? [],
    decision: row.decision,
    decision_reason: row.decision_reason,
    rug_emergency: Boolean(row.rug?.emergency),
    rug_reason: null,
    liquidity_usd: row.pool?.liquidity_usd ?? null,
    mint_revoked: row.mint_safety ? row.mint_safety.mint_authority == null : null,
    errors: row.errors ?? [],
    stop_live: row.stop_live !== false,
  }));
  const observeRows = snapshot.unmonitored.map((row) => ({
    mint: row.mint,
    name: row.name,
    ui_amount: row.ui_amount,
    exit_sol: row.exit_sol ?? null,
    kind: "observe" as const,
    pnl_pct: null,
    unit_price_sol: null,
    trailing_peak_unit_price_sol: null,
    trailing_active: false,
    exit_style: null,
    floor_multiple: null,
    scale_rungs_fired: [],
    decision: "observe",
    decision_reason: "no policy",
    rug_emergency: Boolean(row.rug?.emergency),
    rug_reason: row.rug?.reason ?? null,
    liquidity_usd: row.pool?.liquidity_usd ?? null,
    mint_revoked: null,
    errors: row.errors ?? [],
    stop_live: true,
  }));
  return [...protectedRows, ...observeRows].sort((left, right) => {
    return (parseSol(right.exit_sol) ?? 0) - (parseSol(left.exit_sol) ?? 0);
  });
}

export function bookTotalSol(bags: DeskBag[]): number {
  return bags.reduce((sum, bag) => sum + (parseSol(bag.exit_sol) ?? 0), 0);
}

export function shareOfBook(bag: DeskBag, total: number): number | null {
  const exit = parseSol(bag.exit_sol);
  if (exit == null || total <= 0) return null;
  return (exit / total) * 100;
}

export function gateLamps(failures: string[]): GateLamp[] {
  const text = failures.join(" · ").toLowerCase();
  return [
    {
      id: "enabled",
      label: "execution.enabled",
      closed: text.includes("execution.enabled"),
      detail: "config execution.enabled is false",
    },
    {
      id: "live",
      label: "--live",
      closed: text.includes("--live"),
      detail: "process was not started with --live",
    },
    {
      id: "arm",
      label: "arm file",
      closed: text.includes("arm file") || text.includes("live arm"),
      detail: "arm file absent or pubkey mismatch",
    },
  ];
}

export function feeTank(sol: string | null | undefined): "ok" | "low" | "empty" {
  const value = parseSol(sol);
  if (value == null) return "empty";
  if (value <= 0) return "empty";
  if (value < FEE_TANK_SOL) return "low";
  return "ok";
}

export function protectionTone(state: string | undefined): "ok" | "warn" | "bad" {
  if (state === "LIVE_ARMED") return "ok";
  if (state === "DRY_RUN") return "warn";
  if (state === "DEGRADED" || state === "DOWN") return "bad";
  return "warn";
}

export function stopFiresAt(exitSol: string | null | undefined, stopLossPct: number): number | null {
  const exit = parseSol(exitSol);
  if (exit == null || !Number.isFinite(stopLossPct)) return null;
  return exit * (1 + stopLossPct / 100);
}

export function policyFor(policies: Policy[], mint: string): Policy | undefined {
  return policies.find((policy) => policy.mint === mint);
}

export function isFixedTrail(style: string | null | undefined): boolean {
  return style === "fixed_trail";
}

export function formatMultiple(value: string | number | null | undefined, digits = 2): string | null {
  const parsed = parseSol(value);
  if (parsed == null) return null;
  return `${parsed.toFixed(digits)}x`;
}

export function entryUnitPrice(policy: Policy | undefined, uiAmount: string | null | undefined): number | null {
  if (!policy) return null;
  if (policy.buy_price_sol != null && policy.buy_price_sol > 0) return policy.buy_price_sol;
  const amount = parseSol(uiAmount);
  if (policy.cost_basis_sol != null && policy.cost_basis_sol > 0 && amount != null && amount > 0) {
    return policy.cost_basis_sol / amount;
  }
  return null;
}

export function runnerMultiples(
  bag: Pick<DeskBag, "unit_price_sol" | "trailing_peak_unit_price_sol" | "pnl_pct" | "ui_amount" | "floor_multiple">,
  policy?: Policy,
): { peak: number | null; now: number | null; floor: number | null } {
  const floor = parseSol(bag.floor_multiple);
  const unit = parseSol(bag.unit_price_sol);
  const peakUnit = parseSol(bag.trailing_peak_unit_price_sol);
  const entry = entryUnitPrice(policy, bag.ui_amount);
  if (unit != null && entry != null && entry > 0) {
    const now = unit / entry;
    const peak = peakUnit != null && peakUnit > 0 ? peakUnit / entry : now;
    return { peak, now, floor };
  }
  const pnl = parseSol(bag.pnl_pct);
  if (pnl != null) {
    const now = 1 + pnl / 100;
    const peak = unit != null && unit > 0 && peakUnit != null ? (peakUnit / unit) * now : now;
    return { peak, now, floor };
  }
  return { peak: null, now: null, floor };
}

export function policyRuleLabel(policy: Policy | undefined, bag?: DeskBag): string {
  if (!policy) return "observe-only";
  const sl = policy.stop_loss_pct;
  const tp = policy.take_profit_pct;
  if (isFixedTrail(policy.exit_style ?? bag?.exit_style)) {
    return `SL ${sl}% · TP ${tp}% · trail ${policy.trailing_stop_pct}%`;
  }
  const floor = formatMultiple(bag?.floor_multiple);
  if (floor) return `SL ${sl}% · arm +${tp}% · floor ${floor}`;
  return `SL ${sl}% · arm +${tp}%`;
}

export function liveRunnerLine(bag: DeskBag, policy?: Policy): string | null {
  if (bag.kind !== "protected" || isFixedTrail(policy?.exit_style ?? bag.exit_style)) return null;
  const { peak, now, floor } = runnerMultiples(bag, policy);
  if (peak != null && floor != null && now != null) {
    return `peak ${formatMultiple(peak)} · floor ${formatMultiple(floor)} · now ${formatMultiple(now)}`;
  }
  return bag.decision_reason || null;
}

export function waitingGraduation(reason: string | null | undefined): boolean {
  return Boolean(reason && reason.toLowerCase().includes("graduation"));
}

export function scaleRungsLabel(rungs: string[] | null | undefined): string | null {
  if (!rungs?.length) return null;
  return `scaled ${rungs.join(" · ")}`;
}
