import { z } from "zod";

/**
 * What one held coin's live venue state costs, exactly as the local core serves it.
 *
 * This is the render shape of `joshi_liquidity::readout::PreTradeReadout` plus the fee-tier
 * standing beside it. Glass computes none of it and must never appear to: every number crosses as
 * a decimal string the core already rendered, and every value the core could not state arrives as
 * an explicit sentence rather than as a blank or a zero. A blank is the shape a reader fills in
 * themselves, and on this screen what they would fill in is money.
 *
 * Three unions here exist because three answers are genuinely two-sided:
 *
 * * **The break-even clip is an interval, not a ceiling.** With any fixed cost at all the hurdle
 *   is U-shaped -- below roughly 0.0003 SOL the network fee eats the trade, above some size the
 *   curve does -- so it is two numbers or a stated refusal, never one number. "No clip breaks
 *   even" is an answer and it arrives as one.
 * * **A fee-tier row may be the top row.** "There is no further threshold to cross" is a fact
 *   worth reading, not an empty field.
 * * **A chain clock may be absent.** A provider that stated no block time did not state an age of
 *   zero.
 */

const wireU64 = z.string().regex(/^(?:0|[1-9]\d*)$/, "must be a non-negative integer string");
const exactDecimal = z
  .string()
  .regex(/^(?:0|[1-9]\d*)\.\d+$/, "must be an exact non-negative decimal string");
/**
 * A rate the core either computed or refused to compute.
 *
 * The refusal branch is in the contract rather than mapped to null on arrival, so a rate that
 * could not be produced can never render as an absent one -- they mean different things.
 */
const bpsOrRefusal = z
  .string()
  .regex(/^(?:0|[1-9]\d*|refused: .+)$/, "must be a basis-point count or a stated refusal");
const absence = z.object({ absence: z.string().min(1) });

export const breakEvenClipSchema = z.union([
  z.object({
    smallestSol: exactDecimal,
    largestSol: exactDecimal,
    smallestHurdleBps: bpsOrRefusal,
    largestHurdleBps: bpsOrRefusal,
  }),
  z.object({ refusal: z.string().min(1) }),
]);

export const nextTierSchema = z.union([
  z.object({
    rowOrdinal: wireU64,
    thresholdSol: exactDecimal,
    gapSol: exactDecimal,
    /** Null only where the market cap is zero, where a fraction of it is not a number. */
    gapBpsOfMarketCap: bpsOrRefusal.nullable(),
    legBps: z.string().min(1),
    direction: z.enum(["cheaper", "dearer", "unchanged", "not_comparable"]),
  }),
  absence,
]);

export const feeTierSchema = z.union([
  z.object({
    marketCapSol: exactDecimal,
    rowOrdinal: wireU64,
    rowCount: wireU64,
    thresholdSol: exactDecimal,
    legBps: z.string().min(1),
    /**
     * True when the first row applies as the deployed fallback rather than because its own
     * threshold was reached. Same rates, different situation, and the difference is worth seeing.
     */
    belowFirstThreshold: z.boolean(),
    next: nextTierSchema,
  }),
  absence,
]);

export const stateAgeSchema = z.object({
  contextSlot: wireU64,
  requestedCommitment: z.string().min(1),
  chainToReceipt: z.union([
    z.object({ earliestMs: z.string().regex(/^-?\d+$/), latestMs: z.string().regex(/^-?\d+$/) }),
    absence,
  ]),
  /** Wall clock at which these bytes reached the machine that read them, in Unix milliseconds. */
  receivedAtUnixMs: z.string().regex(/^-?\d+$/, "must be an integer millisecond clock"),
  clockId: z.string().min(1),
  drift: z.union([
    z.object({
      direction: z.enum(["up", "down", "unchanged"]),
      bps: bpsOrRefusal,
      elapsedSlots: wireU64,
      elapsedLocalMs: z.string().regex(/^-?\d+$/),
      bpsPerMinute: wireU64.nullable(),
    }),
    absence,
  ]),
});

export const venueReadoutV1Schema = z.object({
  contract: z.literal("joshi.glass.venue_readout"),
  schemaVersion: z.literal(1),
  authority: z.literal("read_record_replay_only"),
  mint: z.string().min(16),
  venueKind: z.string().min(1),
  venueKindLabel: z.enum(["pump_bonding_curve", "pumpswap_pool"]),
  venueAccount: z.string().min(32),
  venueBinding: z.string().min(1),
  feeFloorBps: bpsOrRefusal,
  feeFloorProbeSol: exactDecimal,
  declaredLiftBps: wireU64,
  breakEvenClip: breakEvenClipSchema,
  feeTier: feeTierSchema,
  /**
   * Set only when the retained fee tier tables disagreed at this market cap and the more expensive
   * one was used. Null means they agreed -- never that the question went unasked.
   */
  pessimisticTierBranch: z.string().min(1).nullable(),
  stateAge: stateAgeSchema,
  declaredCosts: z.string().min(1),
  /** What the core could not reconstruct. An empty list is itself a claim, and it is rendered. */
  unsupported: z.array(z.string().min(1)),
});

export type VenueReadoutV1 = z.infer<typeof venueReadoutV1Schema>;
export type BreakEvenClip = z.infer<typeof breakEvenClipSchema>;
export type FeeTier = z.infer<typeof feeTierSchema>;
export type NextTier = z.infer<typeof nextTierSchema>;
export type StateAge = z.infer<typeof stateAgeSchema>;

/**
 * Either a measured readout or the core's own account of why there is none.
 *
 * The two absences the core distinguishes are kept apart all the way to the screen. "This core has
 * measured nothing at all" and "this core has measured other coins and not this one" are different
 * things to know at three in the morning, and collapsing them would print the second over the
 * first.
 */
export type VenueReadoutAnswer =
  | { state: "measured"; readout: VenueReadoutV1 }
  | { state: "absent"; absence: string };

export function parseVenueReadoutV1(value: unknown): VenueReadoutV1 {
  return venueReadoutV1Schema.parse(value);
}
