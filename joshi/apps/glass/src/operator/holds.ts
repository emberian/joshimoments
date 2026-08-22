import type { CaptureContext, OperatorCommand } from "./contract";
import type { JournalEntry, OperatorIntent } from "./useOperatorJournal";

/**
 * Holding a coin.
 *
 * pump.fun's feed forgets: a coin that scrolled past is an opportunity that existed and was lost
 * because nothing retained it. A hold is the smallest possible act that refuses that -- one
 * keystroke, no dialog, no taxonomy, bound to the exact scene bytes that were on screen.
 *
 * A hold is an ordinary `record_focus` evidence command. It invents no wire kind, carries no
 * economic authority, and travels the same route and the same local pending cache as every other
 * operator act, so it inherits the restart proof in `apps/core/src/live_gesture.rs` unchanged.
 *
 * The label is the whole discriminator, so it is frozen here and mirrored byte for byte by that
 * walk. Changing it silently would orphan every hold already in a catalog.
 */
export const HOLD_UI_LABEL = "Hold coin";

/**
 * A note appended to a coin that was already held.
 *
 * Deliberately a *second* act rather than a field on the first. The steering history of this
 * project is explicit that operator acts and raw utterances must precede a fixed taxonomy, and
 * asking for words at the moment of noticing is exactly what makes the noticing too slow. The
 * first act says "this one"; a later act says why, in her language, if she ever wants to.
 */
export const HOLD_NOTE_UI_LABEL = "Note on held coin";

/** The one label version these two acts have ever had. */
export const HOLD_UI_LABEL_VERSION = "1";

/** The longest free-text note the frozen `record_focus` context accepts. */
export const MAX_HOLD_NOTE_LENGTH = 4_000;

function holdContext(uiLabel: string, note: string | null): CaptureContext {
  return {
    uiLabel,
    uiLabelVersion: HOLD_UI_LABEL_VERSION,
    // Nothing here is asked for at hold time. A required field is a button she cannot push fast
    // enough, and a dropdown at the moment of noticing contaminates the very thing being recorded.
    confidencePpm: null,
    urgency: null,
    whyNow: null,
    note,
  };
}

/** The exact intent one keystroke commits: this coin, this scene, nothing else stated. */
export function holdIntent(candidateId: string): OperatorIntent {
  return {
    commandKind: "record_focus",
    subject: { kind: "candidate", key: candidateId },
    label: HOLD_UI_LABEL,
    payload: { context: holdContext(HOLD_UI_LABEL, null), dwellMilliseconds: null },
  };
}

/**
 * A later utterance about a held coin.
 *
 * @throws when the note is empty or longer than the frozen context field. An empty note is not
 * recorded as an empty note; it is refused, because a blank stored where words belong reads to a
 * later reader as "she had nothing to say".
 */
export function holdNoteIntent(candidateId: string, note: string): OperatorIntent {
  const exact = note.trim();
  if (exact.length === 0) throw new Error("a note with no words is not recorded as a note");
  if (exact.length > MAX_HOLD_NOTE_LENGTH) {
    throw new Error(`a note is limited to ${MAX_HOLD_NOTE_LENGTH} characters by the frozen operator context`);
  }
  return {
    commandKind: "record_focus",
    subject: { kind: "candidate", key: candidateId },
    label: HOLD_NOTE_UI_LABEL,
    payload: { context: holdContext(HOLD_NOTE_UI_LABEL, exact), dwellMilliseconds: null },
  };
}

function uiLabelOf(command: OperatorCommand): string | null {
  if (command.commandKind !== "record_focus") return null;
  return command.payload.context.uiLabel;
}

export function isHoldCommand(command: OperatorCommand): boolean {
  return uiLabelOf(command) === HOLD_UI_LABEL;
}

export function isHoldNoteCommand(command: OperatorCommand): boolean {
  return uiLabelOf(command) === HOLD_NOTE_UI_LABEL;
}

export function holdNoteText(command: OperatorCommand): string | null {
  return isHoldNoteCommand(command) && command.commandKind === "record_focus"
    ? command.payload.context.note
    : null;
}

/**
 * Every subject this browser session has held, in the order she held them.
 *
 * Insertion order, never rank and never recency: a row that moves under a keyboard or a screen
 * reader is a row that can be lost again, which is the defect this rail exists to end. A new hold
 * is appended below the existing ones and announced; nothing above it ever shifts.
 *
 * Scene is deliberately not a filter. A hold made over an earlier scene is still a coin she
 * noticed, and dropping it when the feed reloads underneath her is precisely the forgetting this
 * replaces.
 */
export function heldSubjectKeys(entries: JournalEntry[]): string[] {
  const held: string[] = [];
  for (const entry of entries) {
    if (!isHoldCommand(entry.command)) continue;
    const key = entry.command.subject.key;
    if (!held.includes(key)) held.push(key);
  }
  return held;
}

/** Every hold act for one subject, oldest first. */
export function holdEntriesFor(entries: JournalEntry[], subjectKey: string): JournalEntry[] {
  return entries.filter((entry) => isHoldCommand(entry.command) && entry.command.subject.key === subjectKey);
}

/** Every note appended to one held subject, oldest first. */
export function holdNoteEntriesFor(entries: JournalEntry[], subjectKey: string): JournalEntry[] {
  return entries.filter((entry) => isHoldNoteCommand(entry.command) && entry.command.subject.key === subjectKey);
}

/**
 * What a hold has actually reached so far, said at the resolution the journal supports.
 *
 * `retained_locally` is not "saved" and `queued` is not "failed". The only status that means the
 * catalog holds these bytes is `committed`, and it is the only one that names a commit sequence.
 */
export type HoldRetention =
  | { state: "retaining_local" }
  | { state: "submitting" }
  | { state: "queued"; reason: string | null }
  | { state: "committed"; commitSeq: string }
  | { state: "rejected"; reason: string | null };

export function holdRetention(entries: JournalEntry[]): HoldRetention {
  const committed = entries.find((entry) => entry.status === "committed" && entry.receipt !== null);
  if (committed?.receipt) return { state: "committed", commitSeq: committed.receipt.commitSeq };
  const latest = entries.at(-1);
  if (!latest) return { state: "retaining_local" };
  if (latest.status === "rejected") return { state: "rejected", reason: latest.error };
  if (latest.status === "queued") return { state: "queued", reason: latest.error };
  if (latest.status === "submitting") return { state: "submitting" };
  return { state: "retaining_local" };
}
