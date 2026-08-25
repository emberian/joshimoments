import { useEffect, useState } from "react";

import { elapsedWords } from "../format";
import type { VenueReadoutAnswer, VenueReadoutV1 } from "../venue/contract";

/**
 * The decision-relevant facts about a venue, when something has actually measured them.
 *
 * A live bonding curve and a graduated pool differ by roughly fifty times in the clip they can
 * carry, and a graduated pool at a small market cap can be as expensive as a curve, because the
 * fee-tier row its market cap selects is the lever rather than the venue label. Glass computes
 * none of it and must never appear to: this is the parsed wire the local core serves from
 * `joshi_liquidity::readout::PreTradeReadout`, so this block is a renderer and not a second
 * implementation. It is shared by the held rail and the coin page so the venue truth cannot
 * fork between them.
 */
export type HeldVenueReadout = VenueReadoutV1;

/** How long ago these bytes arrived, recomputed while the readout sits on screen unread. */
function useElapsedSince(receivedAtUnixMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // Five seconds, deliberately. One pool was measured drifting nine to ten basis points in
    // thirty seconds, so the age has to visibly move; and this element carries no live region, so
    // a screen reader is never interrupted by a clock she did not ask about.
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);
  return now - receivedAtUnixMs;
}

/**
 * When these numbers were true, which is the part that beats the arithmetic.
 *
 * Chain-to-receipt was measured at eleven to thirteen seconds, mostly the `finalized` commitment
 * depth, and one pool drifted nine to ten basis points in thirty seconds -- so a sixty
 * basis-point fee floor is two to four minutes of drift. A number on screen without its age is a
 * lie by omission, so this is rendered above the numbers rather than under them.
 */
function StateAge({ readout }: { readout: HeldVenueReadout }) {
  const age = readout.stateAge;
  const elapsed = useElapsedSince(Number(age.receivedAtUnixMs));
  return (
    <div className="held-venue-age">
      <p>
        <strong>Read {elapsedWords(elapsed)} ago</strong> at slot {age.contextSlot}, commitment{" "}
        {age.requestedCommitment}. These numbers describe that moment and are not refreshed.
      </p>
      <p>
        {"absence" in age.chainToReceipt
          ? age.chainToReceipt.absence
          : `Chain to receipt was ${age.chainToReceipt.earliestMs} to ${age.chainToReceipt.latestMs} ms; an interval, because chain time has whole-second resolution.`}
      </p>
      <p>
        {"absence" in age.drift
          ? age.drift.absence
          : `Measured drift: the marginal price moved ${age.drift.direction} ${age.drift.bps} bps over ${age.drift.elapsedSlots} slots and ${age.drift.elapsedLocalMs} ms`
            + (age.drift.bpsPerMinute === null
              ? ", over a window with no duration."
              : `, about ${age.drift.bpsPerMinute} bps per minute over that one window. It bounds nothing in general.`)}
      </p>
    </div>
  );
}

/** What crossing the next threshold does to the rate, said as a consequence rather than a label. */
const NEXT_TIER_WORDS = {
  cheaper: "cheaper if this grows into it.",
  dearer: "dearer if this grows into it.",
  unchanged: "the same rate there.",
  not_comparable: "not comparable, because a creator component was not observed.",
} as const;

/**
 * Which fee-tier row this market cap selects, and how far the next one is.
 *
 * Three real mints, read on consecutive evenings: a bonding curve at 247 basis points, a graduated
 * pool at 60, and a second graduated pool at 249 -- the last one as expensive as the curve,
 * because its 42.8 SOL market cap selects the fee program's first tier row at 125 basis points a
 * leg. "Graduated" predicts nothing. The row does, and the tables are steep enough that being near
 * a threshold is worth knowing before the trade rather than after it.
 */
function FeeTier({ tier }: { tier: HeldVenueReadout["feeTier"] }) {
  if ("absence" in tier) {
    return (
      <div>
        <dt>Fee tier</dt>
        <dd className="held-venue-absent">Not stated<p className="held-venue-note">{tier.absence}</p></dd>
      </div>
    );
  }
  return (
    <div>
      <dt>Fee tier</dt>
      <dd>
        Row {tier.rowOrdinal} of {tier.rowCount} · {tier.legBps} bps a leg
        <p className="held-venue-note">
          Market cap {tier.marketCapSol} SOL selects the row at {tier.thresholdSol} SOL.
          {tier.belowFirstThreshold
            ? " That first row is applying as the program's fallback, not because its own threshold was reached."
            : ""}
        </p>
        <p className="held-venue-note">
          {"absence" in tier.next
            ? tier.next.absence
            : `Next row ${tier.next.rowOrdinal} at ${tier.next.thresholdSol} SOL: ${tier.next.gapSol} SOL of market cap away`
              + (tier.next.gapBpsOfMarketCap === null ? "" : ` (${tier.next.gapBpsOfMarketCap} bps of the current cap)`)
              + `, ${tier.next.legBps} bps a leg there — `
              + NEXT_TIER_WORDS[tier.next.direction]}
        </p>
      </dd>
    </div>
  );
}

/**
 * Either a measured readout, the core's own stated absence, or (`null`) the fact that this
 * cockpit has no venue source attached at all — three different things to know, kept apart all
 * the way to the screen. None of them ever renders as a zero.
 *
 * `headingLevel` exists because the block renders in two outlines: inside a held card (h3
 * coin, so h4 here) and inside the coin page's microstructure panel (h2 panel, so h3 here).
 * A skipped level is an axe violation and a real cost to a reader walking headings.
 */
export function VenueAndClip({ answer, headingLevel = 4 }: {
  answer: VenueReadoutAnswer | null;
  headingLevel?: 3 | 4;
}) {
  const Heading = headingLevel === 3 ? "h3" : "h4";
  if (answer === null) {
    return (
      <div className="held-venue" data-measured="false">
        <Heading>Venue and clip</Heading>
        <dl>
          <div><dt>Venue kind</dt><dd>Not yet measured</dd></div>
          <div><dt>Fee floor</dt><dd>Not yet measured</dd></div>
          <div><dt>Clips that break even inside a stated lift</dt><dd>Not yet measured</dd></div>
          <div><dt>Fee tier</dt><dd>Not yet measured</dd></div>
        </dl>
        <p>
          No liquidity measurement is attached to this cockpit yet. These lines stay empty until a
          measured readout arrives; nothing here is estimated, defaulted, or carried over from
          another coin.
        </p>
      </div>
    );
  }
  if (answer.state === "absent") {
    return (
      <div className="held-venue" data-measured="false">
        <Heading>Venue and clip</Heading>
        <p className="held-venue-absent" role="note">{answer.absence}</p>
      </div>
    );
  }
  const readout = answer.readout;
  return (
    <div className="held-venue" data-measured="true">
      <Heading>Venue and clip</Heading>
      <StateAge readout={readout} />
      <dl>
        <div>
          <dt>Venue kind</dt>
          <dd>
            {readout.venueKind}
            <p className="held-venue-note">Bound by {readout.venueBinding} · account {readout.venueAccount}</p>
          </dd>
        </div>
        <div>
          <dt>Fee floor</dt>
          <dd>
            {readout.feeFloorBps} bps
            <p className="held-venue-note">Venue only, probed at {readout.feeFloorProbeSol} SOL</p>
          </dd>
        </div>
        <div>
          <dt>Clips that break even inside a {readout.declaredLiftBps} bps lift</dt>
          <dd className={"refusal" in readout.breakEvenClip ? "held-venue-refusal" : undefined}>
            {"refusal" in readout.breakEvenClip
              ? `None. ${readout.breakEvenClip.refusal}`
              : `${readout.breakEvenClip.smallestSol} SOL to ${readout.breakEvenClip.largestSol} SOL`}
            <p className="held-venue-note">An interval, not a ceiling: below it the fixed costs eat the trade, above it the curve does.</p>
          </dd>
        </div>
        <FeeTier tier={readout.feeTier} />
      </dl>
      {readout.pessimisticTierBranch !== null && (
        <p className="held-venue-refusal" role="note">{readout.pessimisticTierBranch}</p>
      )}
      <p>Declared costs: {readout.declaredCosts}</p>
      {readout.unsupported.length === 0 ? (
        <p>
          This readout names nothing it could not reconstruct, which is itself worth doubting rather
          than trusting.
        </p>
      ) : (
        <>
          <p id={`held-gaps-${readout.mint}`}>Not reconstructed, {readout.unsupported.length} in all:</p>
          <ul className="held-venue-gaps" aria-labelledby={`held-gaps-${readout.mint}`}>
            {readout.unsupported.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}
