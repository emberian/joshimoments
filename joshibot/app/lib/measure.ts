/**
 * The epistemic core of the console.
 *
 * Every figure this UI draws is a `Measured<T>`, not a number. The point is that
 * "we watched and it was zero", "we watched and never got a sample", and "we are
 * not watching" are three DIFFERENT constructors, so a renderer physically
 * cannot collapse them into `0`. A wallet-indexed tape once made absence look
 * like measurement; the type system is where that stops being possible.
 *
 * Every figure also carries an `Origin`: which endpoint served it, which field,
 * whether it was served or derived here, and BOTH clocks.
 */

/**
 * Event time vs ingest time.
 *
 * `event` is when the thing happened out in the world (block time, quote time,
 * pool observation). `ingest` is when this process learned about it. On backfill
 * these orders disagree (measured rank correlation -0.77), so subtracting one
 * from the other across sources fabricates latency. They are kept separate and
 * both are rendered; nothing in this file computes a difference between them.
 */
export type Clock = {
  event: string | null;
  ingest: string | null;
};

export type CaveatKind =
  | "thin-sample"
  | "proxy-clock"
  | "derived"
  | "stale"
  | "disagreement"
  | "unbounded"
  | "retracted";

export type Caveat = {
  kind: CaveatKind;
  note: string;
};

/** How a figure came to be on screen. */
export type Origin = {
  /** Producer: an endpoint path, a CLI module, or a file. */
  source: string;
  /** Field path within the producer's payload, when it is a served scalar. */
  path?: string;
  /**
   * `served`   — the producer emitted this number; we printed it.
   * `derived`  — this browser computed it from served numbers.
   * `config`   — a local constant, not a measurement.
   */
  kind: "served" | "derived" | "config";
  clock: Clock;
  /** Producer's own staleness budget, when it publishes one. */
  ttlSeconds?: number | null;
  /** Sample size and window behind an aggregate. Absent means not an aggregate. */
  sample?: Sample | null;
  caveats?: Caveat[];
  /** Free-text provenance detail shown in the popover. */
  note?: string;
};

export type Sample = {
  n: number;
  /** Human window, e.g. "3h 12m" or "27 closed trades". */
  window?: string | null;
};

export type Measured<T> =
  | { state: "observed"; value: T; origin: Origin }
  /** Watched, but the producer has never yielded a sample. NOT zero. */
  | { state: "unobserved"; origin: Origin }
  /** Not being watched at all — no collector, disabled, or not wired. NOT zero. */
  | { state: "unwatched"; origin: Origin }
  /** The producer errored. Distinct from having no data. */
  | { state: "error"; error: string; origin: Origin };

export function observed<T>(value: T, origin: Origin): Measured<T> {
  return { state: "observed", value, origin };
}

export function unobserved<T>(origin: Origin): Measured<T> {
  return { state: "unobserved", origin };
}

export function unwatched<T>(origin: Origin): Measured<T> {
  return { state: "unwatched", origin };
}

export function measureError<T>(error: string, origin: Origin): Measured<T> {
  return { state: "error", error, origin };
}

/**
 * Lift a nullable served scalar.
 *
 * `null` from a producer that IS watching means "no sample yet", which is
 * `unobserved` — never 0. A served `0` stays `observed` and renders as a real
 * zero, which is a different thing on screen.
 */
export function fromNullable<T>(
  value: T | null | undefined,
  origin: Origin,
): Measured<T> {
  if (value === null || value === undefined || value === "") return unobserved(origin);
  return observed(value, origin);
}

/** Lift a served decimal-string (the sentinel sends SOL amounts as strings). */
export function fromDecimalString(
  value: string | number | null | undefined,
  origin: Origin,
): Measured<number> {
  if (value === null || value === undefined || value === "") return unobserved(origin);
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) {
    return measureError(`unparseable numeric: ${String(value).slice(0, 32)}`, origin);
  }
  return observed(parsed, origin);
}

export function valueOr<T>(measured: Measured<T>, fallback: T): T {
  return measured.state === "observed" ? measured.value : fallback;
}

export function isObserved<T>(
  measured: Measured<T>,
): measured is { state: "observed"; value: T; origin: Origin } {
  return measured.state === "observed";
}

/** Map a measurement's value while preserving its state and provenance. */
export function mapMeasured<T, U>(
  measured: Measured<T>,
  fn: (value: T) => U,
  amend?: Partial<Origin>,
): Measured<U> {
  const origin = amend ? { ...measured.origin, ...amend } : measured.origin;
  if (measured.state === "observed") return observed(fn(measured.value), origin);
  if (measured.state === "error") return measureError(measured.error, origin);
  if (measured.state === "unwatched") return unwatched(origin);
  return unobserved(origin);
}

/**
 * Build a clock pair, flagging the case where the producer has only one clock
 * and is publishing it as both.
 *
 * The sentinel currently sets `observed_at === received_at` for every freshness
 * row, i.e. it uses ingest time as a PROXY for event time. That is not a bug to
 * paper over — it means "this timestamp is when we heard, not when it happened",
 * and the UI says exactly that rather than implying a measured event time.
 */
export function clockOf(eventAt: string | null, ingestAt: string | null): Clock {
  return { event: eventAt, ingest: ingestAt };
}

export function clockIsProxied(clock: Clock): boolean {
  return clock.event !== null && clock.event === clock.ingest;
}

export function proxyClockCaveat(clock: Clock): Caveat[] {
  if (!clockIsProxied(clock)) return [];
  return [
    {
      kind: "proxy-clock",
      note:
        "Producer publishes one timestamp as both event and ingest time. This is when the sentinel heard, not a measured block time. Do not read a latency from it.",
    },
  ];
}

/** Sample-size floor below which a rate must not be extrapolated. */
export const THIN_SAMPLE_N = 30;

export function thinSampleCaveat(sample: Sample | null | undefined): Caveat[] {
  if (!sample) return [];
  if (sample.n >= THIN_SAMPLE_N) return [];
  return [
    {
      kind: "thin-sample",
      note: `n=${sample.n}${sample.window ? ` over ${sample.window}` : ""} is below the n=${THIN_SAMPLE_N} floor. Not extrapolated; read as a raw count, not a rate.`,
    },
  ];
}

export function caveatsOf(origin: Origin): Caveat[] {
  return [
    ...(origin.caveats ?? []),
    ...proxyClockCaveat(origin.clock),
    ...thinSampleCaveat(origin.sample),
  ];
}

export function worstCaveat(caveats: Caveat[]): Caveat | null {
  const rank: Record<CaveatKind, number> = {
    retracted: 0,
    disagreement: 1,
    "thin-sample": 2,
    unbounded: 3,
    stale: 4,
    "proxy-clock": 5,
    derived: 6,
  };
  return [...caveats].sort((a, b) => rank[a.kind] - rank[b.kind])[0] ?? null;
}

/** Staleness verdict against the producer's own published TTL. */
export type Staleness = "fresh" | "aging" | "stale" | "unknown";

export function stalenessOf(
  clock: Clock,
  ttlSeconds: number | null | undefined,
  now: number,
): Staleness {
  const stamp = clock.ingest ?? clock.event;
  if (!stamp || !ttlSeconds) return "unknown";
  const at = new Date(stamp).getTime();
  if (!Number.isFinite(at)) return "unknown";
  const elapsed = (now - at) / 1000;
  if (elapsed <= ttlSeconds) return "fresh";
  if (elapsed <= ttlSeconds * 3) return "aging";
  return "stale";
}

/**
 * Map the sentinel's own freshness `status` onto our three-way absence model.
 *
 * The server already distinguishes these; the previous UI dropped the whole
 * block on the floor.
 */
export function absenceFromStatus(status: string): "observed" | "unobserved" | "unwatched" {
  if (status === "never") return "unobserved";
  if (status === "disabled" || status === "unknown") return "unwatched";
  return "observed";
}
