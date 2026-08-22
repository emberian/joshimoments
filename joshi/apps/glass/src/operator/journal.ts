import type { CaptureContext, OperatorCommandKind, OperatorPayload } from "./contract";
import type { OperatorIntent } from "./useOperatorJournal";

/**
 * The exocortex journal entry.
 *
 * "On this day we discussed this about these charts" is an ordinary `record_focus` evidence
 * command whose words travel verbatim in the frozen capture context, bound to the exact scene
 * bytes the discussion was over. It invents no wire kind and no parallel store: the journal is a
 * reading of the operator command ledger, and this label is what distinguishes an entry from a
 * hold or any other focus record (`docs/planning/EXOCORTEX.md`).
 *
 * The label is the whole discriminator, so it is frozen here and mirrored byte for byte by
 * `JOURNAL_UI_LABEL` in `apps/core/src/live_journal.rs`. Changing it silently would orphan every
 * entry already in a catalog.
 */
export const JOURNAL_UI_LABEL = "Journal entry";

/** The one label version journal entries have ever had. */
export const JOURNAL_UI_LABEL_VERSION = "1";

/** The longest entry the frozen `record_focus` context accepts. */
export const MAX_JOURNAL_ENTRY_LENGTH = 4_000;

/**
 * An utterance about the whole served scene, in her language, committed as evidence.
 *
 * The subject is the scene itself (`{kind: "scene", key: sceneId}`): a discussion is usually
 * about the composition on screen, not one coin. A coin-directed utterance already has its own
 * act — the hold note — and both render in the same journal timeline.
 *
 * @throws when the words are empty or longer than the frozen context field. An empty entry is
 * refused, not stored, because a blank where words belong reads later as "nothing was said".
 */
export function journalEntryIntent(sceneId: string, words: string): OperatorIntent {
  const exact = words.trim();
  if (exact.length === 0) throw new Error("a journal entry with no words is not recorded as an entry");
  if (exact.length > MAX_JOURNAL_ENTRY_LENGTH) {
    throw new Error(`a journal entry is limited to ${MAX_JOURNAL_ENTRY_LENGTH} characters by the frozen operator context`);
  }
  return {
    commandKind: "record_focus",
    subject: { kind: "scene", key: sceneId },
    label: JOURNAL_UI_LABEL,
    payload: {
      context: {
        uiLabel: JOURNAL_UI_LABEL,
        uiLabelVersion: JOURNAL_UI_LABEL_VERSION,
        // Nothing beyond the words is asked for. Structure, if it ever exists, is derived later
        // from the words; it is never demanded at the moment of saying them.
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: exact,
      },
      dwellMilliseconds: null,
    },
  };
}

/** One verbatim stated field of an act: the reader's label and the operator's exact words. */
export type VerbatimWords = { label: string; words: string };

/**
 * Every field of a frozen payload that carries the operator's own words, verbatim.
 *
 * This enumerates stated free-text and stated single-choice fields only. It never summarizes,
 * never concatenates, and returns an empty list for an act that carried no words — the surface
 * renders that as the explicit "the act itself was the statement", not as a blank.
 */
export function verbatimWords(kind: OperatorCommandKind, payload: OperatorPayload): VerbatimWords[] {
  const words: VerbatimWords[] = [];
  const context: CaptureContext = payload.context;
  if (context.whyNow !== null) words.push({ label: "Why now", words: context.whyNow });
  if (context.note !== null) words.push({ label: "Note", words: context.note });
  if (kind === "nominate_candidate" && "nomination" in payload) {
    words.push({ label: "Nomination", words: payload.nomination });
  }
  if (kind === "record_disposition" && "disposition" in payload) {
    words.push({ label: "Disposition (provisional)", words: payload.disposition });
  }
  if (kind === "record_crackle_family" && "crackleFamily" in payload) {
    words.push({ label: "Crackle family (provisional)", words: payload.crackleFamily });
  }
  if (kind === "record_gesture" && "gestureLabel" in payload) {
    words.push({ label: "Gesture", words: payload.gestureLabel });
  }
  if (kind === "compensate_command" && "reason" in payload) {
    words.push({ label: "Correction reason", words: payload.reason });
  }
  return words;
}
