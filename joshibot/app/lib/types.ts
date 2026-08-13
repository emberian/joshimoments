export type Severity = "info" | "warning" | "critical";

export type ExitStyle = "runner" | "fixed_trail";

export type PositionThresholds = {
  stop_loss_pct: string;
  take_profit_pct: string;
  trailing_stop_pct: string;
  exit_style?: ExitStyle | string;
  floor_confirm_quotes?: number;
  hold_trail_until_graduated?: boolean;
};

export type PositionRunner = {
  floor_multiple?: string | null;
  below_floor_streak?: number;
  scale_rungs_fired?: string[];
  original_amount?: number | string | null;
  sell_amount?: number | string | null;
};

export type PositionRow = {
  mint: string;
  name: string;
  ui_amount: string;
  exit_sol?: string | null;
  pnl_pct?: string | null;
  unit_price_sol?: string | null;
  decision: string;
  decision_reason: string;
  trailing_active?: boolean;
  trailing_peak_unit_price_sol?: string | null;
  errors: string[];
  rug?: { emergency: boolean; liquidity_drop_pct?: string | null };
  pool?: { dex_id: string; liquidity_usd: string; reserve_value: string; reserve_unit: string } | null;
  mint_safety?: { mint_authority: string | null; freeze_authority: string | null } | null;
  thresholds?: PositionThresholds;
  runner?: PositionRunner;
  stop_live?: boolean;
  sl_live_after?: string | null;
};

export type UnmonitoredRow = {
  mint: string;
  name: string;
  ui_amount: string;
  protection: string;
  exit_sol?: string | null;
  pool?: { liquidity_usd: string } | null;
  rug?: { emergency: boolean; reason?: string | null };
  errors?: string[];
  pump_metadata?: { symbol: string | null; complete: boolean | null } | null;
};

export type Snapshot = {
  generated_at: string;
  system: {
    wallet_address: string;
    mode: "live" | "dry-run";
    protection_state: string;
    running: boolean;
    rpc_ready: boolean;
    jupiter_ready: boolean;
    telegram_ready: boolean;
    gate_failures: string[];
    last_cycle_at: string | null;
    last_cycle_error: string | null;
    unprotected_count?: number;
  };
  wallet: { sol: string | null; portfolio_exit_sol: string | null };
  positions: PositionRow[];
  unmonitored: UnmonitoredRow[];
  events: { timestamp: string; severity: Severity; category: string; message: string }[];
};

export type Policy = {
  mint: string;
  name: string;
  cost_basis_sol?: number | null;
  buy_price_sol?: number | null;
  stop_loss_pct: number;
  take_profit_pct: number;
  trailing_stop_pct: number;
  rug_exit: boolean;
  dispose_after_break_even: boolean;
  exit_style?: ExitStyle;
  floor_confirm_quotes?: number;
  hold_trail_until_graduated?: boolean;
};

export type ProtectUnmonitoredRequest = {
  // `from_quote` is deliberately absent: seeding a basis from the current exit
  // quote made PnL start at 0% regardless of what was paid. The server rejects
  // it; keeping it out of the type makes reintroducing it a compile error.
  mode: "rug_only";
  stop_loss_pct?: number;
  take_profit_pct?: number;
  trailing_stop_pct?: number;
  rug_exit?: boolean;
  exit_style?: ExitStyle;
};

export type ProtectUnmonitoredResult = {
  created: string[];
  skipped: { mint: string; reason: string }[];
  items: Policy[];
  can_execute: false;
};

export type CandleBar = { t: number; o: number; h: number; l: number; c: number; v: number };

export type Performance = {
  native_sol: string | null;
  portfolio_exit_sol: string | null;
  realized_sol: string;
  trade_count: number;
  protected_positions: number;
  observe_only: number;
  event_counts: Record<string, number>;
  last_exit_at: string | null;
  mode: string | null;
  protection_state: string | null;
};

export type EvidenceClass = "fact" | "claim" | "speculation";

export type IntelEvidence = {
  id: string;
  classification: EvidenceClass;
  title: string;
  summary: string;
  observed_at: string | null;
  source_ids: string[];
  kind: string;
  url: string | null;
  author: string | null;
  cashtags: string[];
  mint_candidates: string[];
  watched_handle: string | null;
  mint: string | null;
};

export type SieveCard = {
  mint: string;
  name: string | null;
  verdict: string;
  reasons: string[];
  scores: Record<string, number | null>;
  execution_effect: "none";
};

export type IntelligenceSnapshot = {
  service: {
    status: string;
    collectors_active: number;
    last_cycle_at: string | null;
    x_items_today: number;
    cycle_in_progress: boolean;
    last_cycle_partial: boolean;
    last_error: string | null;
  };
  inbox: IntelEvidence[];
  x_tape: IntelEvidence[];
  sources: { id: string; label: string; status: string }[];
  watchlists: { id: string; name: string; member_count: number }[];
  candidates: SieveCard[];
};

export type ViewId = "overview" | "positions" | "markets" | "intelligence" | "history" | "performance";
