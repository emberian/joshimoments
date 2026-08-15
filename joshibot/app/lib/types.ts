/**
 * Typed against the LIVE sentinel responses (schema_version 2), captured from
 * a running desk, not reconstructed from prose.
 *
 * The previous model was a stale subset: it omitted `readiness`, `freshness`,
 * `experiments`, `signals`, `schema_version`, `wallet.sol_lamports` and the
 * per-signal `provenance` array. `freshness` in particular is the server's own
 * two-clock block (`observed_at` / `received_at`) and the old UI never drew it.
 */

export type Severity = "info" | "warning" | "critical";

/** `shitcoims_sentinel/engine.py::_operational_sections` */
export type CapabilityState = "ready" | "blocked" | "degraded" | "disabled";

/** `shitcoims_sentinel/engine.py::_operational_sections` */
export type FreshnessStatus =
  | "fresh"
  | "never"
  | "disabled"
  | "unknown"
  | "degraded"
  | "stalled"
  | (string & {});

export type Capability = {
  id: string;
  label: string;
  state: CapabilityState;
  reason: string | null;
  /** null means this capability has never been checked — not "checked at epoch". */
  checked_at: string | null;
  required_for: ("observe" | "shadow" | "live")[];
};

export type Readiness = {
  overall: "ready" | "degraded" | "blocked";
  capabilities: Capability[];
};

/**
 * The two-clock row. `observed_at` is event time, `received_at` is ingest time.
 * They are currently equal for every producer, which means event time is being
 * PROXIED by ingest time — the UI must say so, not imply a measured latency.
 */
export type FreshnessRow = {
  id: string;
  label: string;
  status: FreshnessStatus;
  observed_at: string | null;
  received_at: string | null;
  ttl_seconds: number | null;
  last_error: string | null;
};

export type ExperimentRow = {
  id: string;
  label: string;
  mode: string;
  health: string;
  last_sample_at: string | null;
  last_error_type: string | null;
  signals_seen: number;
  can_execute: boolean;
  note: string | null;
};

/** Per-signal provenance, emitted by the server itself. */
export type SignalProvenance = {
  source_id: string;
  observed_at: string | null;
  received_at: string | null;
  adapter_version: string | null;
  endpoint_family: string | null;
  evidence: Record<string, unknown>;
};

export type SignalRow = {
  id: string;
  mint: string | null;
  token_name: string | null;
  kind: string;
  severity: Severity;
  status: string;
  summary: string;
  source_ids: string[];
  corroboration_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  expires_at: string | null;
  policy_effect: string;
  signature?: string;
  slot?: number;
  provenance: SignalProvenance[];
};

/**
 * `null` is a rule, not missing data: the exit never fires. Rendering it as a number is
 * how a bag that is meant to be held reads as a bag with a stop.
 */
export type PositionThresholds = {
  stop_loss_pct: string | null;
  take_profit_pct: string | null;
  runner_tightness: string | null;
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

export type PositionPool = {
  dex_id?: string;
  liquidity_usd?: string;
  reserve_value?: string;
  reserve_unit?: string;
  observed_at?: string | null;
};

export type PositionRow = {
  mint: string;
  name: string;
  amount?: string;
  ui_amount: string;
  exit_sol?: string | null;
  pnl_pct?: string | null;
  unit_price_sol?: string | null;
  decision: string;
  decision_reason: string;
  dispose_after_break_even?: boolean;
  confirmed_slot?: number | null;
  /** Ingest time of the exit quote behind `exit_sol`. */
  quote_received_at?: string | null;
  trailing_active?: boolean;
  trailing_peak_unit_price_sol?: string | null;
  errors: string[];
  rug?: { emergency: boolean; liquidity_drop_pct?: string | null; reason?: string | null };
  pool?: PositionPool | null;
  mint_safety?: { mint_authority: string | null; freeze_authority: string | null } | null;
  pump_metadata?: PumpMetadata | null;
  thresholds?: PositionThresholds;
  runner?: PositionRunner;
  stop_live?: boolean;
  sl_live_after?: string | null;
};

export type PumpMetadata = {
  symbol?: string | null;
  name?: string | null;
  complete?: boolean | null;
  creator?: string | null;
  last_trade_at?: string | null;
  received_at?: string | null;
};

export type UnmonitoredRow = {
  mint: string;
  name: string;
  amount?: string;
  ui_amount: string;
  protection: string;
  exit_sol?: string | null;
  quote_received_at?: string | null;
  pool?: PositionPool | null;
  rug?: { emergency: boolean; reason?: string | null };
  errors?: string[];
  pump_metadata?: PumpMetadata | null;
};

export type EventRow = {
  timestamp: string;
  severity: Severity;
  category: string;
  message: string;
  context?: Record<string, unknown>;
};

export type Snapshot = {
  schema_version?: number;
  generated_at: string;
  system: {
    wallet_name?: string;
    wallet_address: string;
    mode: "live" | "dry-run";
    protection_state: string;
    running: boolean;
    rpc_ready: boolean;
    jupiter_ready: boolean;
    telegram_ready: boolean;
    telegram_configured?: boolean;
    telegram_last_error_type?: string | null;
    gate_failures: string[];
    poll_interval_seconds?: number;
    last_cycle_at: string | null;
    last_cycle_error: string | null;
    unprotected_count?: number;
  };
  wallet: { sol_lamports?: number; sol: string | null; portfolio_exit_sol: string | null };
  positions: PositionRow[];
  unmonitored: UnmonitoredRow[];
  readiness?: Readiness;
  freshness?: FreshnessRow[];
  experiments?: ExperimentRow[];
  signals?: SignalRow[];
  events: EventRow[];
};

export type Policy = {
  mint: string;
  name: string;
  cost_basis_sol?: number | null;
  buy_price_sol?: number | null;
  /** null means this exit NEVER fires. Absence of a rule, not a very deep threshold. */
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  /** Tightness knob on the lock-rung table; null means no trailing behaviour at all. */
  runner_tightness: number | null;
  rug_exit: boolean;
  dispose_after_break_even: boolean;
  floor_confirm_quotes?: number;
  hold_trail_until_graduated?: boolean;
};

export type ProtectUnmonitoredRequest = {
  // `from_quote` is deliberately absent: seeding a basis from the current exit
  // quote made PnL start at 0% regardless of what was paid. The server rejects
  // it; keeping it out of the type makes reintroducing it a compile error.
  mode: "rug_only";
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  runner_tightness?: number | null;
  rug_exit?: boolean;
};

export type ProtectUnmonitoredResult = {
  created: string[];
  skipped: { mint: string; reason: string }[];
  items: Policy[];
  can_execute: false;
};

export type CandleBar = { t: number; o: number; h: number; l: number; c: number; v: number };

export type CandlePayload = {
  mint: string;
  interval: string;
  bars: CandleBar[];
  source: string;
  dex?: string;
  stats?: Record<string, number | null>;
};

export type TradeRow = {
  timestamp: string;
  mint: string;
  name: string;
  reason: string;
  input_amount?: string;
  output_lamports: string;
  signature: string;
};

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

export type Health = {
  healthy: boolean;
  wallet: string;
  protection_state: string;
  last_cycle_at: string | null;
  unprotected_count: number;
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

/**
 * Counters are nullable on purpose. The previous loader defaulted every missing
 * counter to `0`, which rendered a service that was not answering as a service
 * reporting zero activity. `null` here means "not observed".
 */
export type IntelligenceSnapshot = {
  reachable: boolean;
  service: {
    status: string;
    collectors_active: number | null;
    last_cycle_at: string | null;
    x_items_today: number | null;
    cycle_in_progress: boolean;
    last_cycle_partial: boolean;
    last_error: string | null;
  };
  inbox: IntelEvidence[];
  x_tape: IntelEvidence[];
  sources: { id: string; label: string; status: string }[];
  watchlists: { id: string; name: string; member_count: number | null }[];
  candidates: SieveCard[];
};

export type ViewId =
  | "desk"
  | "bags"
  | "chart"
  | "circuit"
  | "tape"
  | "ledger"
  | "wire";
