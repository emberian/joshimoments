import type { OperatorIntent } from "./useOperatorJournal";

/**
 * The automatic viewport assertion: the honest denominator for the selection instrument.
 *
 * The selection measurement scores a chosen coin against the coins the operator PASSED OVER in
 * the same scene, and its pre-registered denominator is the `viewport` choice set when a scene
 * recorded one (falling back to `rendered`). This module is where that set is defined, so the
 * definition is stated here precisely:
 *
 *   A candidate is in this scene's viewport when the operator's reading actually reached its
 *   row before the assertion was issued — reached meaning the row received real focus (Tab,
 *   J/K roving navigation, screen-reader navigation that moves system focus), or the candidate
 *   was explicitly selected into the workbench by an operator gesture (click, palette, episode
 *   rail, held rail), or an evidence act named it as its subject.
 *
 * What it claims: this cockpit observed the operator's navigation reach that row. In this feed
 * every row is a single focusable button and the app's own navigation model keeps "what she is
 * on" and "what a keystroke acts on" identical, so reaching a row is the event in which a
 * screen reader announces it.
 *
 * What it refuses to claim: comprehension, dwell, or coverage of screen-reader browse-mode
 * reading that never moves system focus — that reading is invisible to the DOM and is therefore
 * NOT recorded. The omission can only shrink the recorded set: it may fail to credit a pass the
 * operator really made, but it can never credit her with passing over a coin she did not see,
 * which is the failure mode the pre-registration forbids.
 *
 * Definitions deliberately rejected:
 * - "the virtualizer mounted the row": overscan mounts rows that were never presented at all —
 *   a fabricated denominator, worse than the honest `rendered` fallback.
 * - "the row's pixels intersected the scroll viewport": pixels on screen are not reading for a
 *   screen-reader operator, and rows keep scrolling past while she is working elsewhere.
 * - "dwell above a threshold": elapsed time is not reading either, and any threshold would be a
 *   free parameter chosen by the people being measured.
 *
 * The assertion is recorded automatically at act time — the only moments a scene can ever
 * produce a selection event — as an ordinary `record_choice_set` evidence command whose subject
 * is the scene itself, never a candidate: an automatic assertion must not register as the
 * operator marking a coin. It adds no keystroke, moves no focus, and renders nothing; a scene
 * without one keeps only its `rendered` set, and the instrument reports that fallback rather
 * than having it backfilled.
 */
export const VIEWPORT_ASSERTION_UI_LABEL = "Viewport reading reached (automatic)";

/** The one label version this automatic assertion has ever had. */
export const VIEWPORT_ASSERTION_UI_LABEL_VERSION = "1";

/** The frozen `record_choice_set` contract admits at most this many subjects. */
export const MAX_VIEWPORT_ASSERTION_SUBJECTS = 1_000;

/**
 * The exact automatic assertion one operator act triggers.
 *
 * @throws when the reached set is empty or exceeds the frozen contract's bound. An oversized
 * set is refused rather than truncated: a truncated viewport would silently drop passed
 * candidates, and the honest alternative to an unrecordable set is the `rendered` fallback.
 */
export function viewportAssertionIntent(
  sceneId: string,
  reachedCandidateIds: readonly string[],
  actedCandidateId: string | null,
): OperatorIntent {
  const subjects = [...new Set(reachedCandidateIds)].sort();
  if (subjects.length === 0) {
    throw new Error("an empty viewport is not asserted; the scene keeps its rendered set");
  }
  if (subjects.length > MAX_VIEWPORT_ASSERTION_SUBJECTS) {
    throw new Error(
      `a viewport of ${subjects.length} rows exceeds the frozen choice-set contract; the scene keeps its rendered set`,
    );
  }
  const selected = actedCandidateId !== null && subjects.includes(actedCandidateId)
    ? { kind: "candidate" as const, key: actedCandidateId }
    : null;
  return {
    commandKind: "record_choice_set",
    subject: { kind: "scene", key: sceneId },
    label: VIEWPORT_ASSERTION_UI_LABEL,
    payload: {
      context: {
        uiLabel: VIEWPORT_ASSERTION_UI_LABEL,
        uiLabelVersion: VIEWPORT_ASSERTION_UI_LABEL_VERSION,
        // Nothing is asked of the operator; an automatic record answers no questions.
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      choiceSet: {
        setKind: "viewport",
        subjects: subjects.map((key) => ({ kind: "candidate" as const, key })),
        selectedSubject: selected,
      },
    },
  };
}

/**
 * Whether a command is an automatic viewport assertion, from either the session journal or the
 * durable readback. Instrument telemetry, not operator words: the journal narrative filters
 * these out (and says so), while the scene inspector still lists them.
 */
export function isViewportAssertion(command: {
  commandKind: string;
  payload: unknown;
}): boolean {
  if (command.commandKind !== "record_choice_set") return false;
  const context = (command.payload as { context?: { uiLabel?: string } }).context;
  return context?.uiLabel === VIEWPORT_ASSERTION_UI_LABEL;
}
