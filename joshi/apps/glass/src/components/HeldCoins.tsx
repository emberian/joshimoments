import { useEffect, useState } from "react";
import { Anchor, CircleOff, NotebookPen, PanelRight } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactUsd, duration, elapsedWords, instantOrAbsent } from "../format";
import type { VenueReadoutAnswer, VenueReadoutV1 } from "../venue/contract";
import {
  heldSubjectKeys,
  holdEntriesFor,
  holdNoteEntriesFor,
  holdNoteText,
  holdRetention,
  MAX_HOLD_NOTE_LENGTH,
  type HoldRetention,
} from "../operator/holds";
import type { JournalEntry } from "../operator/useOperatorJournal";

/**
 * The exact candidate row that was on screen when she held it.
 *
 * Kept because the feed is allowed to stop carrying a coin at any moment, and when that happens
 * the last thing actually observed is the only honest thing to show. It is a copy of served
 * bytes, never a recomputation.
 */
export type RetainedObservation = {
  candidate: Candidate;
  sceneId: string;
  heldAt: string;
};

/**
 * The decision-relevant facts about a venue, when something has actually measured them.
 *
 * A live bonding curve and a graduated pool differ by roughly fifty times in the clip they can
 * carry, and a graduated pool at a small market cap can be as expensive as a curve, because the
 * fee-tier row its market cap selects is the lever rather than the venue label. Glass computes
 * none of it and must never appear to: this is the parsed wire the local core serves from
 * `joshi_liquidity::readout::PreTradeReadout`, so wiring it up is a renderer and not a second
 * implementation.
 */
export type HeldVenueReadout = VenueReadoutV1;

/**
 * Either a measured readout for a held coin or the reason there is none.
 *
 * `null` is a third answer and a different one: this cockpit has no venue source at all, so
 * nothing was even asked. It is not evidence that nothing has been measured anywhere.
 */
export type HeldVenueLookup = (subjectKey: string) => VenueReadoutAnswer | null;

function retentionText(retention: HoldRetention): string {
  switch (retention.state) {
    case "retaining_local": return "Retained in this browser only; the store has not answered yet.";
    case "submitting": return "Submitting to the local core; no durable commit is claimed yet.";
    case "queued": return retention.reason ?? "Disconnected. The exact mark is retained locally for retry.";
    case "committed": return `Retained by the catalog at commit ${retention.commitSeq}.`;
    case "rejected": return retention.reason ?? "The core refused this mark. It is not retained.";
  }
}

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

function VenueAndClip({ answer }: { answer: VenueReadoutAnswer | null }) {
  if (answer === null) {
    return (
      <div className="held-venue" data-measured="false">
        <h4>Venue and clip</h4>
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
        <h4>Venue and clip</h4>
        <p className="held-venue-absent" role="note">{answer.absence}</p>
      </div>
    );
  }
  const readout = answer.readout;
  return (
    <div className="held-venue" data-measured="true">
      <h4>Venue and clip</h4>
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

function HeldNoteForm({
  subjectKey,
  label,
  onAppendNote,
}: {
  subjectKey: string;
  label: string;
  onAppendNote(subjectKey: string, note: string): void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fieldId = `held-note-${subjectKey}`;
  return (
    <details className="held-note-form">
      <summary>Add a note</summary>
      <form
        data-shortcuts-disabled="true"
        onSubmit={(event) => {
          event.preventDefault();
          try {
            onAppendNote(subjectKey, note);
            setNote("");
            setError(null);
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "This note was not recorded.");
          }
        }}
      >
        <label htmlFor={fieldId}>Anything you want to say about {label}, in your own words</label>
        <textarea
          id={fieldId}
          rows={3}
          maxLength={MAX_HOLD_NOTE_LENGTH}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional. Nothing is required, and nothing is categorised."
        />
        {error && <p className="capture-error" role="alert">{error}</p>}
        <button type="submit" className="secondary-button">
          <NotebookPen aria-hidden="true" /> Append note
        </button>
      </form>
    </details>
  );
}

/**
 * The held rail: the coins she noticed, kept exactly where she left them.
 *
 * Nothing in here is derived from the feed's ordering, so nothing in here can be re-sorted,
 * scrolled away, or dropped when a later scene arrives. A held coin the current view no longer
 * carries keeps its last observation and says out loud that the feed stopped carrying it.
 */
export function HeldCoins({
  entries,
  candidates,
  retained,
  venueReadout,
  onSelect,
  onAppendNote,
}: {
  entries: JournalEntry[];
  candidates: Candidate[];
  retained: Record<string, RetainedObservation>;
  venueReadout?: HeldVenueLookup;
  onSelect(candidateId: string): void;
  onAppendNote(subjectKey: string, note: string): void;
}) {
  const held = heldSubjectKeys(entries);
  return (
    // `tabIndex={-1}` so the skip link really lands here: without it the target is unfocusable
    // and several screen readers keep reading from wherever they already were.
    <section className="panel held-panel" aria-labelledby="held-title" id="held-coins" tabIndex={-1}>
      <div className="panel-header">
        <div>
          <p className="eyebrow">Nothing here scrolls away</p>
          <h2 id="held-title">Held coins</h2>
        </div>
        <output className="count-badge" aria-live="polite">{held.length} held</output>
      </div>

      {/*
        The reach of this list, said out loud. An empty rail is the exact shape a reader fills in
        with "nothing was held", and after a reload that reading would be false: the catalog still
        holds every accepted mark. The journal panel reads those back per scene through the core's
        operator readback route; this rail itself still lists only this session's marks, and says
        so rather than borrowing the journal's answer and re-sorting it.
      */}
      <p className="held-scope">
        This list covers the current browser session, plus any mark still waiting to reach the
        store. A hold the catalog has already accepted is read back verbatim in the journal panel
        for its scene, not restored here — so an empty list is never evidence that nothing was
        held.
      </p>

      {held.length === 0 ? (
        <p className="held-empty">
          Nothing is held yet. Press <kbd>;</kbd> to hold whichever coin is selected in the feed;
          it lands here immediately and stays, even after the feed moves on.
        </p>
      ) : (
        <ul className="held-list" aria-label="Coins you are holding, in the order you held them">
          {held.map((subjectKey, index) => {
            const holds = holdEntriesFor(entries, subjectKey);
            const notes = holdNoteEntriesFor(entries, subjectKey);
            const retention = holdRetention(holds);
            const live = candidates.find((candidate) => candidate.id === subjectKey) ?? null;
            const observation = retained[subjectKey] ?? null;
            const shown = live ?? observation?.candidate ?? null;
            const label = shown ? candidateSymbol(shown.symbol, shown.mint) : subjectKey;
            const headingId = `held-heading-${subjectKey}`;
            return (
              <li key={subjectKey}>
                <article
                  className="held-card"
                  aria-labelledby={headingId}
                  aria-posinset={index + 1}
                  aria-setsize={held.length}
                  data-carried={live !== null}
                  data-retention={retention.state}
                >
                  <header>
                    <h3 id={headingId}>
                      <Anchor aria-hidden="true" size={15} /> {label}
                    </h3>
                    {shown && <span className="held-name">{candidateName(shown.name)}</span>}
                    <span className="held-retention">{retentionText(retention)}</span>
                  </header>

                  {live === null && observation !== null && (
                    <p className="held-absence" role="note">
                      <CircleOff aria-hidden="true" size={15} /> The feed stopped carrying this
                      coin. Everything below is the last observation this cockpit actually saw, in
                      scene {observation.sceneId}. It is not a claim about what the coin is doing
                      now, and it is not a claim that the coin is gone.
                    </p>
                  )}
                  {live === null && observation === null && (
                    <p className="held-absence" role="note">
                      <CircleOff aria-hidden="true" size={15} /> This mark is retained, but no
                      observation of this coin is retained in this browser session, so there is
                      nothing to show about it here. The mark itself is not affected.
                    </p>
                  )}

                  {shown && (
                    <dl className="held-facts">
                      <div><dt>Held at</dt><dd>{instantOrAbsent(observation?.heldAt ?? null)}</dd></div>
                      <div><dt>Last observed</dt><dd>{instantOrAbsent(shown.lastObservedAt)}</dd></div>
                      <div><dt>Market cap</dt><dd>{compactUsd(shown.metrics.marketCapUsd)}</dd></div>
                      <div><dt>Change, 5m</dt><dd>{basisPoints(shown.metrics.change5mBps)}</dd></div>
                      <div><dt>Age</dt><dd>{duration(shown.metrics.ageSeconds)}</dd></div>
                    </dl>
                  )}

                  <VenueAndClip answer={venueReadout?.(subjectKey) ?? null} />

                  {notes.length > 0 && (
                    <ul className="held-notes" aria-label={`Notes you appended to ${label}`}>
                      {notes.map((entry) => (
                        <li key={entry.command.commandId}>
                          <span>{holdNoteText(entry.command)}</span>
                          <small>{entry.status === "committed" && entry.receipt
                            ? `Retained at commit ${entry.receipt.commitSeq}`
                            : `Not yet retained by the catalog · ${entry.status}`}</small>
                        </li>
                      ))}
                    </ul>
                  )}

                  <div className="held-actions">
                    <button type="button" className="secondary-button" onClick={() => onSelect(subjectKey)} disabled={live === null}>
                      <PanelRight aria-hidden="true" /> {live === null ? "Not in this view" : "Open in workbench"}
                    </button>
                  </div>
                  <HeldNoteForm subjectKey={subjectKey} label={label} onAppendNote={onAppendNote} />
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default HeldCoins;
