import { useState } from "react";
import { Anchor, CircleOff, NotebookPen, PanelRight } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactUsd, duration, instantOrAbsent } from "../format";
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
 * carry, which is the difference between a coin being worth her attention and not. Glass computes
 * none of it and must never appear to: this is the render shape of
 * `joshi_liquidity::readout::PreTradeReadout`, field for field, so wiring it up is a serializer
 * and not a second implementation.
 */
export type HeldVenueReadout = {
  venueKind: string;
  venueAccount: string;
  /** What binds that account to this mint, stated rather than assumed. A curve names no mint. */
  venueBinding: string;
  /** Venue-only round trip at the probe size. The floor, in basis points. */
  feeFloorBps: string;
  /** The probe is a declared input, not a venue fact, so it is shown next to what it produced. */
  feeFloorProbeSol: string;
  declaredLiftBps: string;
  /**
   * Both ends of the break-even clip interval at that lift, or exactly why there is none.
   *
   * With any fixed cost at all the answer is an interval and never a ceiling -- too small and the
   * network fee eats the trade, too large and the curve does -- so it is never rendered as one
   * number. "No clip breaks even" is an answer too, and it is rendered as an answer.
   */
  breakEvenClip: { smallestSol: string; largestSol: string } | { refusal: string };
  /** The binding uncertainty on all of this is state age, so it is never left off the screen. */
  stateAge: string;
  /** What the readout could not reconstruct. An empty list is a claim, so it is rendered too. */
  unsupported: string[];
};

export type HeldVenueLookup = (subjectKey: string) => HeldVenueReadout | null;

function retentionText(retention: HoldRetention): string {
  switch (retention.state) {
    case "retaining_local": return "Retained in this browser only; the store has not answered yet.";
    case "submitting": return "Submitting to the local core; no durable commit is claimed yet.";
    case "queued": return retention.reason ?? "Disconnected. The exact mark is retained locally for retry.";
    case "committed": return `Retained by the catalog at commit ${retention.commitSeq}.`;
    case "rejected": return retention.reason ?? "The core refused this mark. It is not retained.";
  }
}

function VenueAndClip({ readout }: { readout: HeldVenueReadout | null }) {
  if (!readout) {
    return (
      <div className="held-venue" data-measured="false">
        <h4>Venue and clip</h4>
        <dl>
          <div><dt>Venue kind</dt><dd>Not yet measured</dd></div>
          <div><dt>Fee floor</dt><dd>Not yet measured</dd></div>
          <div><dt>Clips that break even inside a stated lift</dt><dd>Not yet measured</dd></div>
        </dl>
        <p>
          No liquidity measurement is attached to this cockpit yet. These lines stay empty until a
          measured readout arrives; nothing here is estimated, defaulted, or carried over from
          another coin.
        </p>
      </div>
    );
  }
  return (
    <div className="held-venue" data-measured="true">
      <h4>Venue and clip</h4>
      <dl>
        <div>
          <dt>Venue kind</dt>
          <dd>{readout.venueKind}</dd>
          <p>Bound by {readout.venueBinding} · account {readout.venueAccount}</p>
        </div>
        <div>
          <dt>Fee floor</dt>
          <dd>{readout.feeFloorBps} bps</dd>
          <p>Venue only, probed at {readout.feeFloorProbeSol} SOL</p>
        </div>
        <div>
          <dt>Clips that break even inside a {readout.declaredLiftBps} bps lift</dt>
          {"refusal" in readout.breakEvenClip
            ? <dd className="held-venue-refusal">None. {readout.breakEvenClip.refusal}</dd>
            : <dd>{readout.breakEvenClip.smallestSol} SOL to {readout.breakEvenClip.largestSol} SOL</dd>}
          <p>An interval, not a ceiling: below it the fixed costs eat the trade, above it the curve does.</p>
        </div>
      </dl>
      <p>State read at {readout.stateAge}.{" "}
        {readout.unsupported.length === 0
          ? "This readout names nothing it could not reconstruct, which is itself worth doubting rather than trusting."
          : `Not reconstructed: ${readout.unsupported.join("; ")}.`}
      </p>
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
        holds every accepted mark, this cockpit just has no route to ask for them back.
      */}
      <p className="held-scope">
        This list covers the current browser session, plus any mark still waiting to reach the
        store. A hold the catalog has already accepted is not read back here, because the core
        serves no route for that yet, so an empty list is never evidence that nothing was held.
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

                  <VenueAndClip readout={venueReadout?.(subjectKey) ?? null} />

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
