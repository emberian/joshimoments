/**
 * The cluster as a circuit.
 *
 * Typed against `shitcoims_netmap/assemble.py` (schema "shitcoims_netmap/1").
 * This object already models absence three ways and already separates event
 * time from ingest time; the job here is to not throw any of that away.
 *
 * WIRING: `shitcoims_netmap.render` is a CLI. There is no HTTP route for it and
 * this UI does not create one (the sentinel process holds the signer; the web
 * tier does not get to add surface to it). The client below reads whichever of
 * these exists, in order, and otherwise reports itself NOT WIRED — never an
 * empty graph, which would read as "no cluster".
 */

export const NETMAP_SCHEMA = "shitcoims_netmap/1";

/** The tape's three-way absence encoding (`shitcoims_netmap/tapefeed.py`). */
export type Evidence = "observed" | "observed_zero" | "not_watching";

export type LpProvenance = "declared" | "declared_env" | "inferred_from_tape" | "unknown";

export type NetNode = {
  symbol: string;
  mint: string;
  /** A served 0 is coerced to null upstream: no price, not a zero price. */
  price_usd: number | null;
  price_source: string | null;
  degree: number;
  /** Edges above the min-liquidity floor. `degree - degree_live` is dead surface. */
  degree_live: number;
  edges: string[];
  inventory: {
    /** null = no LP wallet resolved. Unknown, NOT zero. */
    lp_units: number | null;
    lp_usd: number | null;
    in_pools: string[];
    /** Always null: needs an RPC read that is not wired. A typed hole, on purpose. */
    wallet_balance_units: null;
    /** Literal false — inventory is always a LOWER BOUND. */
    complete: false;
    basis: string;
  };
  flow_units_out_window: number;
  flow_usd_out_window: number | null;
  net_charge_units_window: number;
  net_charge_usd_window: number | null;
  any_watch_coverage: boolean;
};

export type LiquidityCrossCheck = {
  chosen_usd: number;
  chosen_source: string;
  dexscreener_liquidity_usd: number | null;
  geckoterminal_reserve_usd: number | null;
  meteora_vault_tvl_usd: number | null;
  tape_reserves_usd: number | null;
  /** EVENT time. */
  tape_reserves_t_event: string | null;
  /** Worst ratio against the chosen source. >0 means the sources disagree. */
  disagreement_ratio: number | null;
};

export type Capacitance =
  | { value: number; weights: [number, number] }
  | {
      low: number;
      high: number;
      span_bounds: [number, number];
      concentration_vs_cpmm: string;
    };

export type NetElement = {
  type: "capacitor" | "battery_cell_stack";
  tvl_usd: number;
  /** "unavailable" means nobody served a TVL. Render "—", never "$0". */
  tvl_source: string;
  liquidity_cross_check: LiquidityCrossCheck;
  /** null = infinite depth term, i.e. a dead pool. */
  depth_term_log_per_usd: { pessimistic: number | null; optimistic: number | null };
  identity: string;
  capacitance_usd_per_log_price: Capacitance;
};

export type NetFee = {
  /** What a cycle arbitrageur actually pays: LP + protocol + creator. */
  taker_bps: number;
  lp_share: number;
  lp_bps: number;
  source: string;
  /** true = assumed, not read from pool config. */
  uncertain: boolean;
  element: string;
  dissipation: string;
};

export type NetPrices = {
  base_in_quote: Partial<Record<"dexscreener" | "geckoterminal" | "chain_state", number>>;
  clock: string;
  /** INGEST time of the price fetch. */
  as_of: string;
  aggregator_disagreement_bps?: number;
  chain_vs_dexscreener_bps?: number;
  chain_price_basis: string | null;
  /** EVENT time; null for DLMM (an active-bin quote carries no block time). */
  chain_price_t_event: string | null;
};

export type NetMarket = {
  chain_price_basis: string;
  chain_price_t_event: string | null;
  volume_24h_usd: number | null;
  txns_24h: number | null;
  txns_1h: number | null;
  fdv_usd: number | null;
  dlmm?: {
    bin_step: number | null;
    base_fee_pct: number | null;
    dynamic_fee_pct: number | null;
    protocol_fee_pct: number | null;
    current_price: number;
    vault_amounts: Record<string, number>;
    api_tvl_field_is_zero: boolean;
  };
};

export type OurPosition = {
  position: string;
  pair: string | null;
  value_usd: number | null;
  unclaimed_fees_usd: number | null;
  claimed_fees_usd: number | null;
  lifetime_fees_usd: number | null;
  in_range: boolean | null;
  age_days: number | null;
  fee_rate_per_day: number | null;
  /** The LP report's thin-sample guard, renamed by the netmap projection. */
  fee_rate_is_thin_sample: boolean;
  token_amounts: Record<string, number>;
  token_usd: Record<string, number>;
};

export type NetOwnership = {
  is_ours: boolean;
  wallet: string;
  provenance: LpProvenance;
  basis: string;
  positions: OurPosition[];
  value_usd: number | null;
  unclaimed_fees_usd: number | null;
  lifetime_fees_usd: number | null;
  /** null when there are 0 positions OR >1 — not merely "unknown". */
  fee_rate_per_day: number | null;
  in_range: boolean | null;
};

export type NetFlow =
  | { evidence: "not_watching"; note: string }
  | {
      evidence: Evidence;
      watched_seconds: number;
      watch_windows_open: number;
      gap_seconds: number;
      swaps_watched: number;
      /** null iff evidence === "not_watching". */
      swaps_per_hour: number | null;
      /** Swaps seen OUTSIDE coverage: evidence of flow, never of absence. */
      swaps_unwatched: number;
      unwatched_note: string;
      /** EVENT time. */
      last_swap_t_event: string | null;
      gross_usd_at_current_price: number | null;
      /** Says out loud that this multiplies event-time units by an ingest-time price. */
      gross_usd_note: string;
    };

export type NetAttempts = {
  attempts: number;
  attempts_watched: number;
  landed: number;
  /** Fraction 0..1. */
  failed_attempt_rate: number | null;
  denominator: string;
  top_errors: { error: string; count: number }[];
};

export type NetCharge = {
  gross_out_units: Record<string, number>;
  net_delta_units: Record<string, number>;
  net_delta_note: string;
  liquidity_delta_units: Record<string, number>;
  liquidity_delta_note: string;
  last_reserves_units: Record<string, number>;
  /** EVENT time. */
  last_reserves_t_event: string | null;
  last_reserves_slot: number | null;
  implied_displacement_bps: number | null;
  implied_displacement_note: string;
};

export type NetEdge = {
  pool: string;
  label: string;
  dex: "pumpswap" | "meteora_dlmm" | (string & {});
  base: { symbol: string; mint: string };
  quote: { symbol: string; mint: string };
  mint_provenance: string;
  in_cluster_universe: boolean;
  element: NetElement;
  fee: NetFee;
  prices: NetPrices;
  market: NetMarket;
  /** null = wallet never resolved (UNKNOWN), which is not `is_ours: false`. */
  ours: NetOwnership | null;
  flow: NetFlow;
  /** Absent for LP-only edges with no tape slice. */
  attempts?: NetAttempts;
  charge?: NetCharge;
  tape_counts?: {
    swaps: number;
    liquidity: number;
    references: number;
    attempts: number;
    unattributed_swaps: number;
    multi_leg_swaps: number;
  };
  tape_window?: { from_t_event: string; to_t_event: string; hours: number; clock: string };
  /** >0 means rows arrived stamped before they happened: clock corruption. */
  clock_alarms?: { rows_with_ingest_before_event: number };
  lp_candidates_from_tape?: { wallet: string; liquidity_rows: number }[];
};

export type CycleVerdict =
  | "no_price"
  | "unresolvable — sources disagree by more than the band"
  | "inside the fee dead-zone — KVL holds, no current"
  | "outside the fee band but uneconomic at any size"
  | "economic ONLY under an assumed DLMM concentration — unmeasured"
  | "outside the full band at both depth bounds"
  | (string & {});

export type NetCycle = {
  name: string;
  legs: {
    pool: string;
    label: string;
    orientation: 1 | -1;
    dex: string;
    element: string;
    tvl_usd: number;
    fee_bps: number;
    fee_uncertain: boolean;
    ours: boolean | null;
  }[];
  /** Keys appear only for sources that priced EVERY leg. */
  curl_bps: Partial<Record<"dexscreener" | "geckoterminal" | "chain_state", number>>;
  curl_primary_source: "dexscreener" | "geckoterminal" | "chain_state" | null;
  source_spread_bps: number | null;
  /** EVENT times. */
  chain_leg_event_times: string[];
  chain_channel_note: string;
  /** The diode dead-zone half-width. A curl inside this band moves nothing. */
  fee_band_bps: number;
  full_band_bps: { no_concentration: number; tight_dlmm_span: number };
  /** `{}` only when verdict === "no_price" — and then there is no curl either. */
  net_value_usd:
    | Record<string, never>
    | {
        no_concentration: { notional_usd: number; net_usd: number };
        tight_dlmm_span: { notional_usd: number; net_usd: number };
        gas_usd: number;
        note: string;
      };
  verdict: CycleVerdict;
  diagnostic_only: true;
  diagnostic_note: string;
  thinnest_leg_usd: number;
};

export type TapeSource =
  | { status: "not read" }
  | {
      root: string;
      files_read: number;
      rows: number;
      partial_final_lines: number;
      malformed_lines: number;
      unreadable_files: string[];
      /** INGEST clock. */
      as_of: string;
    };

export type LpMeterSource =
  | { status: "not read" }
  | {
      wallet: string | null;
      provenance: LpProvenance;
      candidates_from_tape: string[];
      total_value_usd: number | null;
      total_unclaimed_usd: number | null;
      total_lifetime_fees_usd: number | null;
      portfolio_fee_rate_per_day: number | null;
      pools_with_positions: string[];
      errors: string[];
    };

export type NetMap = {
  schema: string;
  /** INGEST clock. */
  generated_at: string;
  clocks: { join_and_display: string; ingest_only: string; why: string };
  /** EVENT-time window; all null when the tape was not read. */
  window: { from_t_event: string | null; to_t_event: string | null; hours: number | null };
  config: {
    gas_usd: number;
    dlmm_span_bounds: [number, number];
    min_cycle_liquidity_usd: number;
  };
  physics: { capacitance: string; fee: string; dlmm: string; resistance: string };
  sources: {
    cluster_tape: TapeSource;
    prices: {
      fetched_at: string;
      dexscreener_pools: number;
      geckoterminal_pools: number;
      dlmm_pool_states: number;
      errors: string[];
    };
    lp_meter: LpMeterSource;
  };
  nodes: NetNode[];
  edges: NetEdge[];
  cycles: NetCycle[];
  warnings: string[];
};

export type NetMapLoad =
  | { state: "ok"; map: NetMap; source: string; receivedAt: string }
  | { state: "error"; error: string; source: string }
  /** No producer is wired. This is "not watching", not "an empty cluster". */
  | { state: "not-wired"; tried: string[] }
  | { state: "loading" };

/** Producer command that mints the snapshot this view reads. */
export const NETMAP_COMMAND = "uv run python -m shitcoims_netmap.render --json > public/netmap.json";

const NETMAP_CANDIDATES = ["/api/netmap", "/netmap.json"] as const;

export async function loadNetmap(): Promise<NetMapLoad> {
  const tried: string[] = [];
  for (const path of NETMAP_CANDIDATES) {
    tried.push(path);
    let response: Response;
    try {
      response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
    } catch {
      continue;
    }
    if (response.status === 404) continue;
    if (!response.ok) {
      return { state: "error", error: `${path} returned ${response.status}`, source: path };
    }
    try {
      const map = (await response.json()) as NetMap;
      if (typeof map?.schema !== "string" || !Array.isArray(map?.edges)) {
        return { state: "error", error: `${path} did not return a netmap document`, source: path };
      }
      return { state: "ok", map, source: path, receivedAt: new Date().toISOString() };
    } catch {
      return { state: "error", error: `${path} returned unparseable JSON`, source: path };
    }
  }
  return { state: "not-wired", tried };
}

/** Sum of edges whose flow is genuinely unknown rather than measured as zero. */
export function unwatchedEdges(map: NetMap): NetEdge[] {
  return map.edges.filter((edge) => edge.flow.evidence === "not_watching");
}

export function observedZeroEdges(map: NetMap): NetEdge[] {
  return map.edges.filter((edge) => edge.flow.evidence === "observed_zero");
}

/** TVL that nobody served. Distinct from a pool measured at zero. */
export function tvlUnavailable(edge: NetEdge): boolean {
  return edge.element.tvl_source === "unavailable";
}

export function clockCorruptedEdges(map: NetMap): NetEdge[] {
  return map.edges.filter((edge) => (edge.clock_alarms?.rows_with_ingest_before_event ?? 0) > 0);
}

/** A cycle is only actionable if it clears the dead-zone AND nets positive. */
export function cycleClearsBand(cycle: NetCycle): boolean {
  const primary = cycle.curl_primary_source;
  if (!primary) return false;
  const curl = cycle.curl_bps[primary];
  if (curl === undefined) return false;
  return Math.abs(curl) > cycle.fee_band_bps;
}

export function cycleNetUsd(cycle: NetCycle): { optimistic: number; pessimistic: number } | null {
  const net = cycle.net_value_usd;
  if (!("no_concentration" in net)) return null;
  return {
    pessimistic: net.no_concentration.net_usd,
    optimistic: net.tight_dlmm_span.net_usd,
  };
}
