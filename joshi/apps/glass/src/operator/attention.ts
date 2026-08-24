import type { OperatorIntent } from "./useOperatorJournal";

/**
 * The automatic attention assertions: the honest denominator for the selection instrument.
 *
 * The selection measurement scores a chosen coin against the coins the operator PASSED OVER in
 * the same scene, and its pre-registered denominator is the `viewport` choice set when a scene
 * recorded one (falling back to `rendered`). This module is where that set is defined, so the
 * definition is stated here precisely — and versioned, because it has changed once:
 *
 *   (v2) A candidate is in this scene's viewport when the operator could actually see its row
 *   before the assertion was issued — its pixels intersected the feed's visible scroll
 *   rectangle (not merely virtualizer-mounted), or her reading reached the row (Tab, J/K and
 *   arrow navigation, screen-reader navigation in focus mode), or the pointer entered the
 *   row, or the candidate was explicitly selected by an operator gesture (click, palette,
 *   episode rail, held rail), or an evidence act named it as its subject. The DOM mechanism
 *   carrying "reading reached the row" changed once without changing the claim: the feed rows
 *   were focusable buttons and the event was per-row DOM focus; the feed is now a
 *   single-tab-stop listbox and the event is the row becoming `aria-activedescendant` while
 *   the listbox holds focus — the moment a reader announces the row and a keystroke acts on
 *   it. Same claim, same denominator, so the label version stays 2.
 *
 * Version history, because scored events carry `uiLabelVersion` and eras must stay
 * distinguishable: v1 counted focus-reach and gestures ONLY, on the belief that the operator
 * was screen-reader, keyboard-only — so pixels on screen were rejected as "not reading". That
 * belief was wrong and Ember corrected it directly: she is primarily visual and uses a
 * pointer. For a visual operator, presentation inside the visible scroll rectangle is the
 * honest floor of "saw", and excluding it systematically under-counted her reading — which
 * shrank the passed-over set and biased the very instrument this set exists to serve.
 *
 * What v2 claims: this cockpit presented the row inside the visible rectangle, or observed
 * the operator's navigation or pointer reach it. What it refuses to claim: comprehension,
 * dwell, or screen-reader browse-mode reading that never moves system focus or the feed's
 * active descendant (still invisible to the DOM, still simply absent). When she is working by reader rather than by eye,
 * scroll-visibility over-counts *reading* — but the pre-registered rule forbids only crediting
 * a pass on a coin she could not have SEEN, and visible pixels satisfy that for the operator
 * this cockpit actually has. The label version records which definition produced each event.
 *
 * Definitions still deliberately rejected:
 * - "the virtualizer mounted the row": overscan mounts rows that were never presented at all —
 *   a fabricated denominator, worse than the honest `rendered` fallback.
 * - "dwell above a threshold": any threshold would be a free parameter chosen by the people
 *   being measured. Entry and visibility are events; dwell is an interpretation.
 *
 * The assertions are recorded automatically at act time — the only moments a scene can ever
 * produce a selection event — as ordinary `record_choice_set` evidence commands whose subject
 * is the scene itself, never a candidate: an automatic assertion must not register as the
 * operator marking a coin. They add no keystroke, move no focus, and render nothing; a scene
 * without them keeps only its `rendered` set, and the instrument reports that fallback rather
 * than having it backfilled. Headless, replay, and agent clients produce no DOM events and
 * therefore never synthesize either set — absence stays absent.
 */
export const VIEWPORT_ASSERTION_UI_LABEL = "Viewport reading reached (automatic)";

/** Version 2: visible-rectangle and pointer entry joined focus-reach. See module doc. */
export const VIEWPORT_ASSERTION_UI_LABEL_VERSION = "2";

/**
 * The pointer set is its own kind, never blurred into `viewport`, because Ember uses her
 * pointer DELIBERATELY as an attention marker — her words: "scroll rectangle is good and so is
 * my pointer, i can be mindful to intentionally use the pointer to capture some aspect of my
 * attention". The instrument and the operator co-adapt: it watches where she points, and she
 * points on purpose. What this set claims is exactly "the pointer entered this row's
 * rectangle" — nothing about intent or reading. Deliberateness is supplied by her stated
 * practice, not inferred by the instrument, and incidental crossings are therefore included
 * rather than filtered by some threshold she would have chosen herself. Pointer entry also
 * feeds the viewport set (a pointed row is a seen row), so `pointed` is a subset of
 * `viewport` by construction.
 */
export const POINTED_ASSERTION_UI_LABEL = "Pointer entered (automatic)";

/** The one label version this automatic assertion has ever had. */
export const POINTED_ASSERTION_UI_LABEL_VERSION = "1";

/** The frozen `record_choice_set` contract admits at most this many subjects. */
export const MAX_VIEWPORT_ASSERTION_SUBJECTS = 1_000;

function attentionAssertionIntent(
  setKind: "viewport" | "pointed",
  uiLabel: string,
  uiLabelVersion: string,
  sceneId: string,
  memberCandidateIds: readonly string[],
  actedCandidateId: string | null,
): OperatorIntent {
  const subjects = [...new Set(memberCandidateIds)].sort();
  if (subjects.length === 0) {
    throw new Error(`an empty ${setKind} set is not asserted; the scene keeps its rendered set`);
  }
  if (subjects.length > MAX_VIEWPORT_ASSERTION_SUBJECTS) {
    throw new Error(
      `a ${setKind} set of ${subjects.length} rows exceeds the frozen choice-set contract; the scene keeps its rendered set`,
    );
  }
  const selected = actedCandidateId !== null && subjects.includes(actedCandidateId)
    ? { kind: "candidate" as const, key: actedCandidateId }
    : null;
  return {
    commandKind: "record_choice_set",
    subject: { kind: "scene", key: sceneId },
    label: uiLabel,
    payload: {
      context: {
        uiLabel,
        uiLabelVersion,
        // Nothing is asked of the operator; an automatic record answers no questions.
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      choiceSet: {
        setKind,
        subjects: subjects.map((key) => ({ kind: "candidate" as const, key })),
        selectedSubject: selected,
      },
    },
  };
}

/**
 * The exact automatic viewport assertion one operator act triggers.
 *
 * @throws when the seen set is empty or exceeds the frozen contract's bound. An oversized
 * set is refused rather than truncated: a truncated viewport would silently drop passed
 * candidates, and the honest alternative to an unrecordable set is the `rendered` fallback.
 */
export function viewportAssertionIntent(
  sceneId: string,
  seenCandidateIds: readonly string[],
  actedCandidateId: string | null,
): OperatorIntent {
  return attentionAssertionIntent(
    "viewport",
    VIEWPORT_ASSERTION_UI_LABEL,
    VIEWPORT_ASSERTION_UI_LABEL_VERSION,
    sceneId,
    seenCandidateIds,
    actedCandidateId,
  );
}

/**
 * Entering the inspect lens on a coin is its own automatic attention record, because it is the
 * moment Ember focuses IN — her words: "it's when i 'inspect' (the ' hotkey) that it should
 * pull that down". The act asks the sensing side for richer observation of that coin (core's
 * hot-attention channel forwards the mint to the keeper), so it is a `request_hot_scope`
 * command; the label below marks it automatic, distinguishing it from the deliberate capture
 * gesture with its own words.
 *
 * THE SUBJECT IS THE SCENE, NEVER THE CANDIDATE, exactly like the viewport assertion above and
 * for the same reason: the selection instrument counts every candidate-named act as the
 * operator marking a coin (`selection/events.py` scores `subject_kind == "candidate"`), and an
 * automatic record on every lens switch would silently score every inspected coin as a pick.
 * The mint rides inside the payload (`scope.subject` of kind `mint`), which is where core reads
 * it from.
 */
export const INSPECT_ASSERTION_UI_LABEL = "Inspect lens entered (automatic)";

/** The one label version this automatic assertion has ever had. */
export const INSPECT_ASSERTION_UI_LABEL_VERSION = "1";

/**
 * The exact automatic act one hunt-to-inspect lens switch emits for the selected coin. The
 * caller debounces repeats of the same coin in the same scene, the changed-set idiom the
 * viewport assertion uses.
 */
export function inspectAssertionIntent(sceneId: string, mint: string): OperatorIntent {
  return {
    commandKind: "request_hot_scope",
    subject: { kind: "scene", key: sceneId },
    label: INSPECT_ASSERTION_UI_LABEL,
    payload: {
      context: {
        uiLabel: INSPECT_ASSERTION_UI_LABEL,
        uiLabelVersion: INSPECT_ASSERTION_UI_LABEL_VERSION,
        // Nothing is asked of the operator; an automatic record answers no questions.
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      scope: {
        family: "candidate-attention",
        subject: { kind: "mint", key: mint },
      },
    },
  };
}

/**
 * The exact automatic pointer assertion one operator act triggers, when the pointer entered
 * any row this scene. Same refusals as the viewport assertion, for the same reasons.
 */
export function pointedAssertionIntent(
  sceneId: string,
  pointedCandidateIds: readonly string[],
  actedCandidateId: string | null,
): OperatorIntent {
  return attentionAssertionIntent(
    "pointed",
    POINTED_ASSERTION_UI_LABEL,
    POINTED_ASSERTION_UI_LABEL_VERSION,
    sceneId,
    pointedCandidateIds,
    actedCandidateId,
  );
}

/**
 * Whether a command is an automatic attention assertion (viewport, pointed, or the inspect-lens
 * record), from either the session journal or the durable readback. Instrument telemetry, not
 * operator words: the journal narrative filters these out (and says so), while the scene
 * inspector still lists them.
 */
export function isViewportAssertion(command: {
  commandKind: string;
  payload: unknown;
}): boolean {
  const context = (command.payload as { context?: { uiLabel?: string } }).context;
  if (command.commandKind === "request_hot_scope") {
    return context?.uiLabel === INSPECT_ASSERTION_UI_LABEL;
  }
  if (command.commandKind !== "record_choice_set") return false;
  return (
    context?.uiLabel === VIEWPORT_ASSERTION_UI_LABEL
    || context?.uiLabel === POINTED_ASSERTION_UI_LABEL
  );
}
