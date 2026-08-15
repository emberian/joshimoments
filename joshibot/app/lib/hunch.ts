/**
 * Client for the paper desk's hunch API (`shitcoims_paperdesk/glass.py`, loopback 8790 —
 * NOT 8788, which the intelligence daemon already owns; see the vite proxy).
 *
 * A DIFFERENT PROCESS FROM THE SENTINEL, DELIBERATELY. The `/api` client in `./api`
 * talks to the process that holds the signing key. This one talks to a process that
 * holds no key, has no RPC client and no broadcast path, and says so on every health
 * response (`can_execute: false`). They are kept in separate modules against separate
 * path prefixes so that "which process am I writing to" is answerable by reading the
 * import, not by tracing a base URL.
 *
 * `Fetched` / `Loaded` / `load` are imported from `./api` rather than redefined: there
 * is one definition of "what a read carries" in this app, and both clients use it.
 *
 * Every optional figure the server serves is `| null` here, with the REASON in the
 * card's `absent` map. Those two travel together into `Measured<T>`: null becomes
 * `unobserved()` and the reason becomes the provenance note. Nothing in this file
 * substitutes a zero for an absence, and nothing in it derives a number.
 */

import { type Fetched, load } from "./api";

export type { Fetched, Loaded } from "./api";
export { load } from "./api";

export const HUNCH_HEALTH_PATH = "/hunch/health";
export const HUNCH_COINS_PATH = "/hunch/coins";
export const HUNCH_RESOLVE_PATH = "/hunch/resolve";
export const HUNCH_READOUT_PATH = "/hunch/readout";
export const HUNCH_TAPE_PATH = "/hunch/tape";
export const HUNCH_POSITIONS_PATH = "/hunch/positions";
export const HUNCH_PATH = "/hunch";
export const ZAP_PATH = "/hunch/zap";

// ---------------------------------------------------------------------- base58

const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/** Byte length of a non-negative bigint — the `(bit_length + 7) // 8` of the reference. */
function byteLength(value: bigint): number {
  if (value === 0n) return 0;
  return Math.ceil(value.toString(2).length / 8);
}

/**
 * A real Solana address: base58 that DECODES to exactly 32 bytes.
 *
 * Port of `shitcoims_paperdesk.readout.is_mint`, same algorithm, and it must stay a
 * decode rather than a shape test. A charset/length regex accepts strings that are not
 * 32-byte keys at all, and — the reason this matters here — base58's alphabet is
 * case-sensitive, so a lowercased address is a DIFFERENT account, not a sloppy one.
 * This operator is targeted by a live address-poisoning campaign whose whole method is
 * a string that looks right; "looks right" is the property a regex tests.
 */
export function isMint(text: string): boolean {
  if (text.length < 32 || text.length > 44) return false;
  let value = 0n;
  for (const character of text) {
    const index = BASE58_ALPHABET.indexOf(character);
    if (index < 0) return false;
    value = value * 58n + BigInt(index);
  }
  let leading = 0;
  while (leading < text.length && text[leading] === "1") leading += 1;
  return leading + byteLength(value) === 32;
}

// ---------------------------------------------------------------------- shapes

/**
 * One coin the collectors are currently showing us, as `CoinIndex.card` builds it.
 *
 * The nullable fields are nullable BECAUSE THEY WERE NOT MEASURED, and each one that is
 * null has an entry in `absent` naming the reason. `drawdown_from_ath` null means the
 * vendor served no all-time high — it does not mean the coin is at its high, which is a
 * confusion this desk has already paid for once.
 */
export type CoinCard = {
  mint: string;
  symbol: string | null;
  name: string | null;
  board: string | null;
  source: string;
  /** The collector's ingest stamp for the freshest board row. Not a chain time. */
  t_seen: string;
  t_seen_unix: number;
  seconds_since_seen: number;
  fresh: boolean;
  price_sol: number | null;
  usd_market_cap: number | null;
  ath_market_cap: number | null;
  drawdown_from_ath: number | null;
  age_s: number | null;
  trade_recency_s: number | null;
  sol_in_curve: number | null;
  complete: boolean;
  /** The n behind two_sided_frac, obs_per_min and wiggle_n. */
  sightings: number;
  obs_per_min: number | null;
  two_sided_frac: number | null;
  wiggle_n: number | null;
  wiggle_amp: number | null;
  own_exit_impact: number | null;
  round_trip_cost: number | null;
  /** The size every impact figure on this card was computed AT. */
  clip_lamports: number;
  gates: Record<string, boolean>;
  /** Evaluated and INERT. Logged so the operator can see which rule disagrees. */
  gates_would_veto: string[];
  ghost_town: boolean;
  held: boolean;
  hunched: CardHunches | null;
  /**
   * PRESENCE AND RECENCY, NOT A COUNT. The upstream feed dedupes by mint, so "called out
   * 15m ago by @x" is the whole fact and "3 callouts" would be an invented one.
   *
   * `null` with NO `absent.callout` is a measured silence: the store was read and nobody
   * named this mint in the last hour. `null` WITH `absent.callout` means the intelligence
   * store could not be read at all — nothing was watching, which carries no information
   * about whether anyone called it out. Those are `unobserved` and `unwatched`
   * respectively, and they must not render the same.
   */
  callout_last_s: number | null;
  callout_kind: string | null;
  callout_author: string | null;
  absent: Record<string, string>;
};

export type CardHunches = {
  n: number;
  last_kind: string | null;
  last_at: string | null;
  last_seconds?: number;
};

/**
 * What `CoinIndex.card` returns for a mint it has never seen on a board: the mint, and
 * `absent.card` saying why there is nothing else. Reachable from `POST /hunch` and from
 * `/hunch/readout/{mint}` — the coin list filters these out server-side.
 */
export type UnsightedCard = {
  mint: string;
  absent: Record<string, string>;
};

export type MaybeCard = CoinCard | UnsightedCard;

export function isSighted(card: MaybeCard): card is CoinCard {
  return (card as CoinCard).t_seen_unix !== undefined;
}

export type CoinSort = "recent" | "callout" | "wiggle" | "drawdown" | "mcap" | "age";

export type CoinList = {
  generated_at: string;
  sort: string;
  n_indexed: number;
  items: CoinCard[];
};

/** `shitcoims_paperdesk.readout.Readout.to_json` — every field, with its own `absent`. */
export type Readout = {
  mint: string;
  symbol: string | null;
  t_unix: number;
  elapsed_s: number;
  absent: Record<string, string>;
  price_sol: number | null;
  usd_market_cap: number | null;
  drawdown_from_ath: number | null;
  age_s: number | null;
  trade_recency_s: number | null;
  complete: boolean | null;
  board: string | null;
  sol_in_curve: number | null;
  own_exit_impact: number | null;
  round_trip_cost: number | null;
  clip_lamports: number;
  observations: number | null;
  obs_per_min: number | null;
  two_sided_frac: number | null;
  wiggle_n: number | null;
  wiggle_amp: number | null;
  /** A LOWER BOUND: the boards poll only learns of a trade by sampling after it. */
  trade_marks_per_hour: number | null;
  callout_last_s: number | null;
  callout_kind: string | null;
  callout_author: string | null;
  crime_symbol: string | null;
  crime_peak_mcap: number | null;
  crime_drawdown: number | null;
  ghost_town: boolean | null;
  gate_legs: Record<string, boolean>;
};

export type ReadoutPayload = {
  generated_at: string;
  card: MaybeCard;
  readout: Readout;
};

export type DeskHealth = {
  alive: boolean;
  /** Present only when there is no heartbeat at all. */
  reason?: string;
  seconds_since_heartbeat?: number;
  at?: string | null;
  run_id?: string | null;
  books?: Record<string, Record<string, number | boolean>> | null;
  sources?: Record<string, { events?: number; silent_seconds?: number; stale?: boolean }> | null;
  hunches?: unknown;
};

export type HunchHealth = {
  generated_at: string;
  desk: DeskHealth;
  index: { coins: number; rows_read: number; refreshed_at: string | null };
  hunches: { total: number; last_at: string | null; path: string };
  /** Stated on every response, and it is a fact about the process, not a setting. */
  can_execute: false;
};

export type ResolveCandidate = {
  mint: string;
  symbol: string | null;
  name: string | null;
  source: string;
  detail: string;
  seconds_since_seen: number | null;
};

/** `mint: null` is a REFUSAL — ambiguous or unknown. The candidates are the disambiguation. */
export type Resolution = {
  generated_at: string;
  query: string;
  mint: string | null;
  matched_on: "mint" | "prefix" | "symbol" | "none" | (string & {});
  reason: string;
  is_address: boolean;
  candidates: ResolveCandidate[];
  suppressed: { mint: string; source: string }[];
};

/** Only `wiggle` opens a position. The rest are watch-only claims, scored at a horizon. */
export type HunchKind = "wiggle" | "down" | "up" | "watch";

/**
 * OMIT, NEVER ZERO. The server 400s on `size_sol <= 0`, `horizon_s <= 0`, and any
 * `confidence` outside the open interval (0, 1) — an explicit `0` included, where it used
 * to be silently coerced to the default. A field left out is a field the desk fills in
 * from its own defaults; a field sent as 0 is a rejected request. This surface sends none
 * of the three, because a one-click hunch has no sliders and the desk's defaults are the
 * single place those numbers are written down.
 */
export type HunchRequest = {
  mint: string;
  kind: HunchKind;
  /** The utterance, VERBATIM. Empty is honest: the operator pointed rather than spoke. */
  note?: string;
  confidence?: number;
  size_sol?: number;
  horizon_s?: number;
  surface?: string;
  /** Client-DECLARED context. The server keeps it in its own labelled key. */
  context?: Record<string, unknown>;
  query?: string;
};

/** `shitcoims_paperdesk.hunch.Hunch.to_json` — Expectation-shaped, two clocks. */
export type HunchRow = {
  schema: string;
  hunch_id: string;
  run_id: string;
  t_event: string;
  t_event_unix: number;
  /** `operator:gesture` — on this row the event clock is a person. */
  t_event_source: string;
  t_ingest: string;
  t_ingest_unix: number;
  scope: { kind: string; mint: string; symbol: string | null };
  claim: { kind: string };
  kind: string;
  horizon_s: number | null;
  confidence: number;
  utterance: string;
  size_lamports: number;
  resolution: Record<string, unknown>;
  evidence: Record<string, unknown>;
};

export type HunchOutcomeState =
  | "pending"
  | "accepted_awaiting_first_observation"
  | "decided"
  | "closed"
  | "recorded"
  | "resolved"
  | "censored"
  | "falsifier_tripped"
  | "expired_before_the_desk_saw_it"
  | "never_observed_no_position_opened"
  | "already_holding_this_mint"
  | (string & {});

export type HunchOutcome = {
  state: HunchOutcomeState;
  net_return?: number | null;
  net_return_pessimistic?: number | null;
  exit_reason?: string | null;
  holding_seconds?: number | null;
  censored?: boolean | null;
  brier?: number | null;
  outcome?: string | null;
  change?: number | null;
  gates_would_veto?: string[];
  ghost_town?: boolean;
  censor_reason?: string | null;
};

export type TapeRow = HunchRow & { seconds_ago: number; outcome: HunchOutcome };

/**
 * LIVE hunches only. The tape on disk is append-only, so a misclick is corrected by
 * appending a RETRACTION row rather than by editing — and this endpoint returns the view
 * with retractions already applied. A `hunch_id` present in one response can therefore be
 * gone from the next without anything having been deleted. Nothing here may cache a row
 * and assume it stays; there is no retraction endpoint yet and this client builds no UI
 * for one.
 */
export type HunchTape = { generated_at: string; items: TapeRow[] };

/**
 * The receipt. `warnings` is the point of it: the capture ALWAYS succeeded, and the
 * warnings are what the desk wants in the operator's face about the thing they just
 * pointed at. They are advisory and they come from the server — never reconstructed here.
 */
export type HunchReceipt = {
  ok: boolean;
  hunch_id: string;
  recorded_at: string;
  hunch: HunchRow;
  card: MaybeCard;
  warnings: string[];
  next: string;
};

// ---------------------------------------------------------------------- positions

/**
 * One open OPERATOR position, read out of the desk's own persisted state.
 *
 * Its exit is the ZAP. The clock is only a 20-40 minute backstop (`backstop_in_s`,
 * closing as `backstop_expired`) — it is the thing that happens when the operator does
 * NOT act, not the intended exit.
 */
export type Position = {
  position_id: string | null;
  decision_id: string | null;
  mint: string;
  symbol: string | null;
  label: string | null;
  spend_lamports: number | null;
  entry_price: number | null;
  last_price: number | null;
  /** Only on the older state-file shape; the per-cycle sidecar does not carry it. */
  mark_price?: number | null;
  peak_price: number | null;
  /** `null` when unmarkable. NEVER render as 0 — a flat position and an unmarkable one
   *  are the difference between "nothing happened" and "we cannot see it". */
  unrealised_return: number | null;
  drawdown_from_peak: number | null;
  held_s: number;
  /** How long since the desk last observed this coin. A zap fills on the NEXT observation,
   *  so a number that keeps growing is an exit that is not coming. */
  seconds_since_observed: number;
  observations: number | null;
  backstop_in_s: number;
  take_profit: number | null;
  stop_loss: number | null;
  /** Non-null means it is ALREADY exiting; a second zap is a server-side no-op. */
  armed: string | null;
  /**
   * THE DESK'S OWN VERDICT on whether it can currently see this coin — not a threshold the
   * browser invented. `false` means a zap has nothing to fill against: the gesture is still
   * recorded (it is the operator's intention, timestamped) but the exit cannot land until
   * an observation arrives, and the button must not look effective when it is not.
   */
  markable?: boolean;
  /** Full card, or null when no board is carrying this mint. */
  card: CoinCard | null;
};

/** A hunch the desk has taken but not yet filled — waiting on its first observation. */
export type AwaitingHunch = { mint: string; utterance?: string } & Record<string, unknown>;

export type PositionList = {
  generated_at: string;
  /** The desk writes this sidecar every cycle (~3s), so it is near-live rather than
   *  the once-a-minute state file. Rendered regardless: staleness here costs money. */
  state_saved_at?: string | null;
  state_age_s?: number | null;
  items: Position[];
  /** Hunches taken but not yet filled. */
  awaiting?: AwaitingHunch[];
  /** Open down/up/watch claims — scored at a horizon, no position behind them. */
  expectations?: Record<string, unknown>[];
  /**
   * `absent.positions` means the desk has stopped writing, i.e. THE RAIL IS SHOWING A
   * GHOST: a dead desk's last book rendered as if it were current. That is the worst
   * failure available on this surface and it renders loudly.
   */
  absent?: Record<string, string>;
};

export type ZapRequest = {
  mint: string;
  position_id?: string | null;
  /** Verbatim, and optional. Empty is the normal case: they hit the key. */
  reason?: string;
  surface?: string;
  context?: Record<string, unknown>;
  position?: Record<string, unknown>;
};

export type ZapReceipt = {
  ok: boolean;
  zap_id: string;
  recorded_at: string;
  mint: string;
  /** Count of price-path points captured with the gesture, not a dict of features. */
  state_features: number;
  next: string;
};

// ---------------------------------------------------------------------- reads

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

export function loadHunchHealth() {
  return getJson<HunchHealth>(HUNCH_HEALTH_PATH);
}

export function coinsPath({
  limit = 60,
  sort = "recent",
  board = null,
  freshOnly = true,
}: {
  limit?: number;
  sort?: CoinSort;
  board?: string | null;
  freshOnly?: boolean;
} = {}) {
  const query = new URLSearchParams({
    limit: String(limit),
    sort,
    fresh_only: String(freshOnly),
  });
  if (board) query.set("board", board);
  return `${HUNCH_COINS_PATH}?${query.toString()}`;
}

export function loadCoins(options?: Parameters<typeof coinsPath>[0]) {
  return getJson<CoinList>(coinsPath(options));
}

export function resolvePath(query: string) {
  return `${HUNCH_RESOLVE_PATH}?q=${encodeURIComponent(query)}`;
}

export function loadResolution(query: string) {
  return getJson<Resolution>(resolvePath(query));
}

export function readoutPath(mint: string) {
  return `${HUNCH_READOUT_PATH}/${encodeURIComponent(mint)}`;
}

export function loadReadout(mint: string) {
  return getJson<ReadoutPayload>(readoutPath(mint));
}

export function loadHunchTape(limit = 50) {
  return getJson<HunchTape>(`${HUNCH_TAPE_PATH}?limit=${limit}`);
}

export function loadPositions() {
  return getJson<PositionList>(HUNCH_POSITIONS_PATH);
}

// ---------------------------------------------------------------------- the write

/**
 * The one write this client can cause: an append to `state/hunches.jsonl`.
 *
 * It reaches the paper desk, which holds no key and cannot sign, submit, or quote. The
 * response's `warnings` must be rendered on the card that produced the click — the
 * capture is already durable (fsynced server-side before the response is composed), so
 * a warning is information about what was captured, never a reason it failed.
 */
export async function postHunch(body: HunchRequest): Promise<HunchReceipt> {
  const response = await fetch(HUNCH_PATH, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof detail.detail === "string" ? detail.detail : "the desk refused the hunch",
    );
  }
  return (await response.json()) as HunchReceipt;
}

/**
 * GET ME OUT. No confirmation, no ceremony, and never a dialog on this path.
 *
 * Arming is ceremony; stopping is instant — the asymmetry is the design, and a confirm
 * step here would measure the dialog instead of the operator. The row is fsynced before
 * this resolves, so by the time a caller sees the receipt the gesture is already durable
 * and there is nothing to undo. Callers must not render a fake undo affordance.
 *
 * WHY THE STATE TRAVELS WITH IT: the zap row carries the full instrument reading and the
 * recent price path at the instant of the exit, which makes every gesture a labelled
 * `(state, exit)` pair. That is the training set for a REACTIVE exit policy. Every exit
 * rule in this repo is currently a function of a clock, and it is a function of a clock
 * because a clock is the only thing anybody ever wrote down.
 */
export async function postZap(body: ZapRequest): Promise<ZapReceipt> {
  const response = await fetch(ZAP_PATH, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof detail.detail === "string" ? detail.detail : "the desk refused the zap");
  }
  return (await response.json()) as ZapReceipt;
}

/** Same convenience wrapper the sentinel client uses, re-exported for symmetry. */
export const loadHunch = load;
