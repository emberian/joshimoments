import { useState } from "react";
import { BookOpen, NotebookPen, RotateCw } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { candidateSymbol } from "../format";
import { isViewportAssertion } from "../operator/attention";
import { verbatimWords, MAX_JOURNAL_ENTRY_LENGTH } from "../operator/journal";
import type { DurableOperatorCommand } from "../operator/readback";
import type { DurableJournalReadback } from "../operator/useDurableSceneCommands";
import type { JournalEntry } from "../operator/useOperatorJournal";

/**
 * The exocortex journal: what was said over this exact scene, kept and read back.
 *
 * Every item is an operator act rendered verbatim — a journal entry, a hold, a note, a
 * provisional disposition — in time order: catalog commit order first, then this session's
 * not-yet-durable acts in the order they were made. Nothing is summarized, categorised, or
 * reflowed, and every absence on this surface is stated rather than left blank
 * (`docs/planning/EXOCORTEX.md`).
 */

const SESSION_STATUS_WORDS: Record<JournalEntry["status"], string> = {
  retaining_local: "Retained in this browser only; the store has not answered yet.",
  submitting: "Submitting to the local core.",
  queued: "Disconnected. The exact act is retained locally for retry.",
  committed: "Committed by the catalog.",
  rejected: "The core refused this act.",
};

function subjectWords(kind: string, key: string, candidates: Candidate[]): string {
  if (kind === "scene") return "This scene";
  if (kind === "candidate") {
    const candidate = candidates.find((item) => item.id === key);
    return candidate ? candidateSymbol(candidate.symbol, candidate.mint) : key;
  }
  return `${kind} ${key}`;
}

function ActWords({ kind, payload }: { kind: DurableOperatorCommand["commandKind"]; payload: DurableOperatorCommand["payload"] }) {
  const stated = verbatimWords(kind, payload);
  if (stated.length === 0) {
    return <p className="journal-no-words">No words were carried; the act itself was the statement.</p>;
  }
  return (
    <>
      {stated.map((item) => (
        <blockquote className="journal-words" key={`${item.label}:${item.words}`}>
          <p>{item.words}</p>
          <footer>{item.label}, verbatim</footer>
        </blockquote>
      ))}
    </>
  );
}

function DurableAct({ command, candidates }: { command: DurableOperatorCommand; candidates: Candidate[] }) {
  return (
    <article className="journal-act" data-origin="catalog">
      <header>
        <span className="journal-label">{command.payload.context.uiLabel}</span>
        <span className="journal-kind">{command.commandKind}</span>
      </header>
      <ActWords kind={command.commandKind} payload={command.payload} />
      <dl className="journal-facts">
        <div><dt>About</dt><dd>{subjectWords(command.subject.kind, command.subject.key, candidates)}</dd></div>
        <div><dt>Said at</dt><dd>{command.issuedAt}</dd></div>
        <div><dt>Retained</dt><dd>Commit {command.commitSeq} · received {command.receivedAt}</dd></div>
        <div><dt>By</dt><dd>{command.clientSessionId}</dd></div>
        <div>
          <dt>Scene binding</dt>
          <dd>
            {command.scene.viewDigest === null
              ? "The catalog no longer joins this act to retained scene bytes; that gap is the fact shown here."
              : `Bound to the exact served bytes, ${command.scene.viewDigest.slice(0, 18)}…`}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function SessionAct({ entry, candidates }: { entry: JournalEntry; candidates: Candidate[] }) {
  return (
    <article className="journal-act" data-origin="session" data-status={entry.status}>
      <header>
        <span className="journal-label">{entry.label}</span>
        <span className="journal-kind">{entry.command.commandKind}</span>
      </header>
      <ActWords kind={entry.command.commandKind} payload={entry.command.payload} />
      <dl className="journal-facts">
        <div><dt>About</dt><dd>{subjectWords(entry.command.subject.kind, entry.command.subject.key, candidates)}</dd></div>
        <div><dt>Said at</dt><dd>{entry.command.issuedAt}</dd></div>
        <div>
          <dt>Retention</dt>
          <dd>
            {entry.status === "committed" && entry.receipt
              ? `Committed by the catalog at commit ${entry.receipt.commitSeq}.`
              : entry.error ?? SESSION_STATUS_WORDS[entry.status]}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function CatalogAnswer({ readback, onReread }: { readback: DurableJournalReadback; onReread(): void }) {
  return (
    <div className="journal-catalog-state">
      {readback.state === "no_scene" && (
        <p role="note">No scene is loaded.</p>
      )}
      {readback.state === "reading" && <p role="status">Reading the catalog…</p>}
      {readback.state === "no_catalog" && <p role="note">{readback.absence}</p>}
      {readback.state === "failed" && (
        <p role="alert">
          The catalog could not be read: {readback.reason} Acts from this browser session are still
          listed below.
        </p>
      )}
      {readback.state === "read" && (
        <p role="note">
          Catalog read at {readback.readAt} ·{" "}
          {readback.answer.sceneRetention === "durable"
            ? `${readback.answer.commands.length} durable act${readback.answer.commands.length === 1 ? "" : "s"} bound to this scene.`
            : "This scene is being served but no act has made it durable yet; the catalog holds nothing for it."}
        </p>
      )}
      {(readback.state === "read" || readback.state === "failed") && (
        <button type="button" className="secondary-button" onClick={onReread}>
          <RotateCw aria-hidden="true" /> Read the catalog again
        </button>
      )}
    </div>
  );
}

function JournalEntryForm({ onAppendEntry }: { onAppendEntry(words: string): void }) {
  const [words, setWords] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="journal-entry-form"
      data-shortcuts-disabled="true"
      onSubmit={(event) => {
        event.preventDefault();
        try {
          onAppendEntry(words);
          setWords("");
          setError(null);
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "This entry was not recorded.");
        }
      }}
    >
      <label htmlFor="journal-entry-words">
        Write a journal entry about this scene, in your own words
      </label>
      <textarea
        id="journal-entry-words"
        rows={3}
        maxLength={MAX_JOURNAL_ENTRY_LENGTH}
        value={words}
        onChange={(event) => setWords(event.target.value)}
        placeholder="What is being discussed, believed, or doubted right now. Nothing is categorised."
      />
      {error && <p className="capture-error" role="alert">{error}</p>}
      <button type="submit" className="secondary-button">
        <NotebookPen aria-hidden="true" /> Append journal entry
      </button>
    </form>
  );
}

/**
 * Reachable in ordinary tab order and through the command palette; deliberately no new
 * single-letter shortcut — six of the eight existing ones already collide with NVDA/JAWS
 * quick-nav keys, and this surface must not add a seventh.
 */
export function JournalRail({
  sceneId,
  candidates,
  readback,
  sessionEntries,
  onReread,
  onAppendEntry,
}: {
  sceneId: string;
  candidates: Candidate[];
  readback: DurableJournalReadback;
  sessionEntries: JournalEntry[];
  onReread(): void;
  onAppendEntry(words: string): void;
}) {
  // Automatic viewport assertions are instrument telemetry, not something she said; narrating
  // one per hold would cost a reader real traversal time. They stay durable in the catalog and
  // listed in the scene inspector, and the scope text below states this exclusion out loud.
  const durable = (readback.state === "read" ? readback.answer.commands : [])
    .filter((command) => !isViewportAssertion(command));
  const durableIds = new Set(durable.map((command) => command.commandId));
  // Time order: catalog commit order first, then this session's acts that the catalog answer
  // does not already carry, in the order they were made. One act never renders twice; the
  // catalog's record wins because it carries the commit clock.
  const sessionOnly = sessionEntries.filter(
    (entry) => entry.command.scene.sceneId === sceneId
      && !durableIds.has(entry.command.commandId)
      && !isViewportAssertion(entry.command),
  );
  const total = durable.length + sessionOnly.length;
  return (
    <section className="panel journal-panel" aria-labelledby="journal-title" id="journal" tabIndex={-1}>
      <div className="panel-header">
        <div>
          <p className="eyebrow">What was said, kept</p>
          <h2 id="journal-title"><BookOpen aria-hidden="true" size={16} /> Journal</h2>
        </div>
        {/* The scope sentences ride the badge's hover; the face keeps the count. */}
        <output
          className="count-badge"
          aria-live="polite"
          title={`Every operator act bound to scene ${sceneId}, verbatim and in time order: `
            + "journal entries, holds, notes, dispositions. The core reads back one scene at "
            + "a time, so acts bound to other scenes are not listed here. Automatic viewport "
            + "assertions are retained in the catalog and listed in the scene inspector."}
        >
          {total} act{total === 1 ? "" : "s"}
        </output>
      </div>

      <CatalogAnswer readback={readback} onReread={onReread} />

      {total === 0 ? (
        <p className="journal-empty">
          Nothing has been said over this scene yet — no entry, no hold, no note.
        </p>
      ) : (
        <ol className="journal-list" aria-label="Acts bound to this scene, oldest first">
          {durable.map((command) => (
            <li key={command.commandId}>
              <DurableAct command={command} candidates={candidates} />
            </li>
          ))}
          {sessionOnly.map((entry) => (
            <li key={entry.command.commandId}>
              <SessionAct entry={entry} candidates={candidates} />
            </li>
          ))}
        </ol>
      )}

      <JournalEntryForm onAppendEntry={onAppendEntry} />
    </section>
  );
}

export default JournalRail;
