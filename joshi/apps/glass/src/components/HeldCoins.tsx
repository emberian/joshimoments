import { useState } from "react";
import { Anchor, CircleOff, NotebookPen, PanelRight } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactUsd, duration, instantOrAbsent, signedTone } from "../format";
import type { VenueReadoutAnswer, VenueReadoutV1 } from "../venue/contract";
import { VenueAndClip } from "./VenueReadoutBlock";
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
    case "submitting": return "Submitting to the local core.";
    case "queued": return retention.reason ?? "Disconnected. The exact mark is retained locally for retry.";
    case "committed": return `Retained by the catalog at commit ${retention.commitSeq}.`;
    case "rejected": return retention.reason ?? "The core refused this mark.";
  }
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
 *
 * Two renderings of the same list. `panel` is the full card rail of the inspect lens: venue
 * readouts, notes, retention sentences. `strip` is what the hunt board carries: one compact
 * row of chips above the board, because on the hunt the board is the page and every paragraph
 * above it costs rows of coins — the sentences move to hover titles and the full cards stay
 * one lens switch away. Same journal-derived list, same order, nothing forgotten either way.
 */
export function HeldCoins({
  entries,
  candidates,
  retained,
  venueReadout,
  onSelect,
  onAppendNote,
  variant = "panel",
}: {
  entries: JournalEntry[];
  candidates: Candidate[];
  retained: Record<string, RetainedObservation>;
  venueReadout?: HeldVenueLookup;
  onSelect(candidateId: string): void;
  onAppendNote(subjectKey: string, note: string): void;
  variant?: "panel" | "strip";
}) {
  const held = heldSubjectKeys(entries);
  if (variant === "strip") {
    return (
      <section className="panel held-panel held-strip" aria-labelledby="held-title" id="held-coins" tabIndex={-1}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">Nothing here scrolls away</p>
            <h2 id="held-title">Held coins</h2>
          </div>
          <output
            className="count-badge"
            aria-live="polite"
            title={"This list covers the current browser session, plus any mark still waiting "
              + "to reach the store. Marks the catalog already accepted are read back verbatim "
              + "in the journal panel for their scene."}
          >
            {held.length} held
          </output>
        </div>
        {held.length === 0 ? (
          <p className="held-empty">
            Nothing is held yet. <kbd>;</kbd> holds the selected coin; it lands here and stays.
          </p>
        ) : (
          <ul className="held-chip-list" aria-label="Coins you are holding, in the order you held them">
            {held.map((subjectKey) => {
              const holds = holdEntriesFor(entries, subjectKey);
              const retention = holdRetention(holds);
              const live = candidates.find((candidate) => candidate.id === subjectKey) ?? null;
              const observation = retained[subjectKey] ?? null;
              const shown = live ?? observation?.candidate ?? null;
              const label = shown ? candidateSymbol(shown.symbol, shown.mint) : subjectKey;
              const headingId = `held-heading-${subjectKey}`;
              return (
                <li key={subjectKey}>
                  <article
                    className="held-chip"
                    aria-labelledby={headingId}
                    data-carried={live !== null}
                    data-retention={retention.state}
                    title={retentionText(retention)
                      + (live === null
                        ? " The feed stopped carrying this coin; what is shown is the last observation this cockpit saw."
                        : "")}
                  >
                    <h3 id={headingId}><Anchor aria-hidden="true" size={13} /> {label}</h3>
                    {/*
                      Whether the mark actually reached the catalog, at chip scale: the exact
                      commit sequence when it did (the end-to-end fact a hold exists to make
                      durable), one word while it has not, the sentence on hover. A refused
                      hold is additionally announced by the rail-wide alert.
                    */}
                    <span className="held-chip-retention">
                      {retention.state === "committed" ? `commit ${retention.commitSeq}`
                        : retention.state === "rejected" ? "refused"
                          : retention.state === "queued" ? "queued"
                            : retention.state === "submitting" ? "submitting"
                              : "local"}
                    </span>
                    <span className="held-chip-facts">
                      <span>{shown ? compactUsd(shown.metrics.marketCapUsd) : "—"}</span>
                      <span className={`value-${signedTone(shown?.metrics.change5mBps ?? null)}`}>
                        {shown ? basisPoints(shown.metrics.change5mBps) : "—"}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="held-chip-open"
                      onClick={() => onSelect(subjectKey)}
                      disabled={live === null}
                      aria-label={live === null
                        ? `${label} is not carried by this view; its retained card is on the inspect lens`
                        : `Open ${label}`}
                    >
                      {live === null ? "not in view" : "open"}
                    </button>
                  </article>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    );
  }
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
        for its scene, not restored here.
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
                      coin. Everything below is the last observation this cockpit saw, in
                      scene {observation.sceneId}.
                    </p>
                  )}
                  {live === null && observation === null && (
                    <p className="held-absence" role="note">
                      <CircleOff aria-hidden="true" size={15} /> This mark is retained, but no
                      observation of this coin is retained in this browser session.
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
