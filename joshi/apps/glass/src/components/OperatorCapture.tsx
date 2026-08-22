import * as Dialog from "@radix-ui/react-dialog";
import { BookOpenCheck, Crosshair, Flame, Focus, History, ListChecks, MessageSquareText, RotateCcw, Sparkles, Tag, Undo2, WifiOff, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { Candidate, Episode, ReplayMode } from "../contract/v1";
import { candidateSymbol } from "../format";
import type { ChartAnchor, CaptureContext } from "../operator/contract";
import type { JournalEntry, OperatorIntent } from "../operator/useOperatorJournal";

export type ChoiceSetKind = "surfaced" | "filtered" | "viewport" | "interacted" | "compared";
export type ChoiceSets = Record<ChoiceSetKind, string[]>;

export type CapturePreset =
  | { type: "focus" }
  | { type: "nominate" }
  | { type: "hot_scope" }
  | { type: "disposition" }
  | { type: "crackle" }
  | { type: "gesture"; gestureLabel: string; episodeId: string | null }
  | { type: "annotation"; anchor: ChartAnchor }
  | { type: "choice_set" }
  | { type: "post_action"; episodeId: string | null; relatedCommandId: string | null }
  | { type: "interview"; episodeId: string | null; sourceCommandIds: string[]; defaultOutcomeVisibility?: "hidden" | "aware" };

function artifactId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "") ?? `${Date.now()}`;
  return `${prefix}-${random}`;
}

function titleFor(preset: CapturePreset): string {
  switch (preset.type) {
    case "focus": return "Record deliberate focus";
    case "nominate": return "Nominate this candidate";
    case "hot_scope": return "Request richer observation";
    case "disposition": return "Record a provisional disposition";
    case "crackle": return "Name a provisional crackle family";
    case "gesture": return `Record ${preset.gestureLabel}`;
    case "annotation": return "Annotate the chart";
    case "choice_set": return "Capture a choice set";
    case "post_action": return "Quick post-action report";
    case "interview": return "Link a later interview";
  }
}

function makeContext(
  uiLabel: string,
  confidencePpm: string,
  urgency: string,
  whyNow: string,
  note: string,
): CaptureContext {
  return {
    uiLabel,
    uiLabelVersion: "1",
    confidencePpm: confidencePpm || null,
    urgency: (urgency || null) as CaptureContext["urgency"],
    whyNow: whyNow.trim() || null,
    note: note.trim() || null,
  };
}

export function emptyCaptureContext(label: string): CaptureContext {
  return makeContext(label, "", "", "", "");
}

function intentFor(
  preset: CapturePreset,
  candidate: Candidate,
  choiceSets: ChoiceSets,
  values: {
    confidencePpm: string;
    urgency: string;
    whyNow: string;
    note: string;
    openValue: string;
    choiceSetKind: ChoiceSetKind;
    outcomeVisibility: "hidden" | "aware";
  },
): OperatorIntent {
  const label = titleFor(preset);
  const context = makeContext(label, values.confidencePpm, values.urgency, values.whyNow, values.note);
  const candidateSubject = { kind: "candidate", key: candidate.id };
  switch (preset.type) {
    case "focus":
      return { commandKind: "record_focus", subject: candidateSubject, label, payload: { context, dwellMilliseconds: null } };
    case "nominate":
      return { commandKind: "nominate_candidate", subject: candidateSubject, label, payload: { context, nomination: values.openValue.trim() } };
    case "hot_scope":
      return {
        commandKind: "request_hot_scope",
        subject: candidateSubject,
        label,
        payload: { context, scope: { family: values.openValue.trim(), subject: { kind: "mint", key: candidate.mint } } },
      };
    case "disposition":
      return { commandKind: "record_disposition", subject: candidateSubject, label, payload: { context, disposition: values.openValue.trim(), provisional: true } };
    case "crackle":
      return { commandKind: "record_crackle_family", subject: candidateSubject, label, payload: { context, crackleFamily: values.openValue.trim(), provisional: true } };
    case "gesture":
      return {
        commandKind: "record_gesture",
        subject: candidateSubject,
        label,
        payload: {
          context,
          gestureLabel: preset.gestureLabel,
          episodeRef: preset.episodeId ? { episodeId: preset.episodeId } : null,
          observedExternally: true,
        },
      };
    case "annotation":
      return {
        commandKind: "record_annotation",
        subject: candidateSubject,
        label,
        payload: {
          context,
          annotationId: artifactId("chart-annotation"),
          chart: { candidateId: candidate.id, seriesId: "observed-price-sol", anchor: preset.anchor },
        },
      };
    case "choice_set": {
      const ids = [...choiceSets[values.choiceSetKind]].sort();
      return {
        commandKind: "record_choice_set",
        subject: candidateSubject,
        label,
        payload: {
          context,
          choiceSet: {
            setKind: values.choiceSetKind,
            subjects: ids.map((key) => ({ kind: "candidate" as const, key })),
            selectedSubject: ids.includes(candidate.id) ? { kind: "candidate" as const, key: candidate.id } : null,
          },
        },
      };
    }
    case "post_action":
      return {
        commandKind: "record_post_action_report",
        subject: candidateSubject,
        label,
        payload: {
          context,
          reportId: artifactId("post-action-report"),
          episodeRef: preset.episodeId ? { episodeId: preset.episodeId } : null,
          relatedCommandId: preset.relatedCommandId,
          actionObservedAt: null,
          outcomeHidden: values.outcomeVisibility === "hidden",
        },
      };
    case "interview":
      return {
        commandKind: "link_interview",
        subject: candidateSubject,
        label,
        payload: {
          context,
          interviewId: artifactId("interview"),
          timing: "later",
          outcomeVisibility: values.outcomeVisibility,
          episodeRef: preset.episodeId ? { episodeId: preset.episodeId } : null,
          sourceCommandIds: [...new Set(preset.sourceCommandIds)].sort(),
        },
      };
  }
}

function initialOpenValue(preset: CapturePreset): string {
  if (preset.type === "nominate") return "operator nomination";
  if (preset.type === "hot_scope") return "candidate-attention";
  if (preset.type === "disposition") return "";
  if (preset.type === "crackle") return "";
  return "recorded observation";
}

function requiresOpenValue(preset: CapturePreset): boolean {
  return preset.type === "nominate" || preset.type === "hot_scope" || preset.type === "disposition" || preset.type === "crackle";
}

export function OperatorCaptureDialog({
  preset,
  candidate,
  mode,
  choiceSets,
  onClose,
  onRecord,
}: {
  preset: CapturePreset | null;
  candidate: Candidate;
  mode: ReplayMode;
  choiceSets: ChoiceSets;
  onClose(): void;
  onRecord(intent: OperatorIntent): void;
}) {
  const [confidencePpm, setConfidencePpm] = useState("");
  const [urgency, setUrgency] = useState("");
  const [whyNow, setWhyNow] = useState("");
  const [note, setNote] = useState("");
  const [openValue, setOpenValue] = useState("");
  const [choiceSetKind, setChoiceSetKind] = useState<ChoiceSetKind>("viewport");
  const [outcomeVisibility, setOutcomeVisibility] = useState<"hidden" | "aware">("hidden");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!preset) return;
    setConfidencePpm("");
    setUrgency("");
    setWhyNow("");
    setNote("");
    setOpenValue(initialOpenValue(preset));
    setChoiceSetKind("viewport");
    setOutcomeVisibility(preset.type === "interview" && preset.defaultOutcomeVisibility
      ? preset.defaultOutcomeVisibility
      : mode === "retrospective" ? "aware" : "hidden");
    setFormError(null);
  }, [mode, preset]);

  if (!preset) return null;
  const title = titleFor(preset);
  const subjects = choiceSets[choiceSetKind];

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="capture-overlay" />
        <Dialog.Content className="capture-dialog" aria-describedby="capture-description" data-shortcuts-disabled="true">
          <header>
            <span><Sparkles aria-hidden="true" /><Dialog.Title>{title}</Dialog.Title></span>
            <Dialog.Close className="icon-button" aria-label="Close capture form"><X aria-hidden="true" /></Dialog.Close>
          </header>
          <Dialog.Description id="capture-description">
            This appends evidence about your interpretation of {candidateSymbol(candidate.symbol, candidate.mint)} in the exact {mode.replaceAll("_", " ")} scene. It cannot place or claim a trade.
          </Dialog.Description>
          <form onSubmit={(event) => {
            event.preventDefault();
            setFormError(null);
            try {
              const intent = intentFor(preset, candidate, choiceSets, { confidencePpm, urgency, whyNow, note, openValue, choiceSetKind, outcomeVisibility });
              onRecord(intent);
              onClose();
            } catch (error) {
              setFormError(error instanceof Error ? error.message : "This record is not valid.");
            }
          }}>
            {requiresOpenValue(preset) && (
              <label>
                <span>{preset.type === "disposition" ? "Disposition in your own language" : preset.type === "crackle" ? "Crackle family in your own language" : preset.type === "hot_scope" ? "Observation family" : "Nomination label"}</span>
                <input required value={openValue} onChange={(event) => setOpenValue(event.target.value)} list={preset.type === "disposition" ? "disposition-suggestions" : preset.type === "crackle" ? "crackle-suggestions" : undefined} />
              </label>
            )}
            <datalist id="disposition-suggestions"><option value="microdip watch" /><option value="might send; retain attention" /><option value="flat; consider re-entry later" /></datalist>
            <datalist id="crackle-suggestions"><option value="microdip scalp" /><option value="crackle then runner" /><option value="social transition watch" /></datalist>

            {preset.type === "choice_set" && (
              <label>
                <span>Which honest set are you recording?</span>
                <select value={choiceSetKind} onChange={(event) => setChoiceSetKind(event.target.value as ChoiceSetKind)}>
                  <option value="surfaced">Served by this scene ({choiceSets.surfaced.length})</option>
                  <option value="filtered">After current filters ({choiceSets.filtered.length})</option>
                  <option value="viewport">Actually in the feed viewport ({choiceSets.viewport.length})</option>
                  <option value="interacted">Explicitly focused this visit ({choiceSets.interacted.length})</option>
                  <option value="compared">Recent comparison set ({choiceSets.compared.length})</option>
                </select>
                <small>{subjects.length > 0 ? subjects.join(", ") : "This set is empty and cannot be recorded."}</small>
              </label>
            )}

            {(preset.type === "post_action" || preset.type === "interview") && (
              <fieldset>
                <legend>Outcome visibility for this report</legend>
                {mode !== "retrospective"
                  ? <label className="radio-row"><input type="radio" name="outcome" checked readOnly /> Outcome hidden by this exact scene</label>
                  : <label className="radio-row"><input type="radio" name="outcome" checked readOnly /> Outcome aware in the retrospective scene</label>}
              </fieldset>
            )}

            {preset.type === "annotation" && <p className="anchor-summary"><Crosshair aria-hidden="true" /> Semantic chart anchor: {preset.anchor.anchorKind}. No pixel coordinate is stored.</p>}

            <div className="capture-grid">
              <label>
                <span>Confidence</span>
                <select value={confidencePpm} onChange={(event) => setConfidencePpm(event.target.value)}>
                  <option value="">Unspecified</option><option value="200000">Low · 20%</option><option value="500000">Middle · 50%</option><option value="800000">High · 80%</option>
                </select>
              </label>
              <label>
                <span>Urgency of attention</span>
                <select value={urgency} onChange={(event) => setUrgency(event.target.value)}>
                  <option value="">Unspecified</option><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="immediate">Immediate observation</option>
                </select>
              </label>
            </div>
            <label>
              <span>Why now?</span>
              <input value={whyNow} onChange={(event) => setWhyNow(event.target.value)} placeholder="What changed or caught your attention?" />
            </label>
            <label>
              <span>Free-text fragment</span>
              <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4} placeholder="Preserve the words you would naturally use." />
            </label>
            {formError && <p className="capture-error" role="alert">{formError}</p>}
            <footer>
              <Dialog.Close type="button" className="secondary-button">Cancel</Dialog.Close>
              <button type="submit" className="primary-button" disabled={preset.type === "choice_set" && subjects.length === 0}>Append evidence record</button>
            </footer>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function OperatorPanel({
  candidate,
  episode,
  sceneEntries,
  compensatedIds,
  onCapture,
  onRetry,
  onUndo,
  onInspectScene,
  nominationQualifies = true,
  pendingReadbackError = null,
  currentClientSessionId,
}: {
  candidate: Candidate;
  episode: Episode | undefined;
  sceneEntries: JournalEntry[];
  compensatedIds: Set<string>;
  onCapture(preset: CapturePreset): void;
  onRetry(commandId: string): void;
  onUndo(entry: JournalEntry): void;
  onInspectScene(): void;
  nominationQualifies?: boolean;
  pendingReadbackError?: string | null;
  currentClientSessionId: string;
}) {
  const candidateEntries = sceneEntries.filter((entry) => entry.command.subject.key === candidate.id || entry.command.subject.key === candidate.mint);
  const committed = candidateEntries.filter((entry) => entry.status === "committed");
  const latestCommandId = committed.at(-1)?.command.commandId ?? null;
  const sourceCommandIds = episode ? committed.filter((entry) => {
    const payload = entry.command.payload as { episodeRef?: { episodeId?: string } | null };
    return payload.episodeRef?.episodeId === episode.id;
  }).slice(-6).map((entry) => entry.command.commandId).sort() : [];
  return (
    <section className="panel operator-panel" aria-labelledby="operator-title">
      <div className="panel-header">
        <div><p className="eyebrow">Semantic capture</p><h2 id="operator-title">Operator exocortex</h2></div>
        <button type="button" className="disclosure-button" onClick={onInspectScene}><History aria-hidden="true" /> Inspect scene</button>
      </div>
      <p className="operator-boundary">Records are append-only evidence. Controls below cannot construct, sign, submit, or verify a transaction.</p>
      <div className="operator-actions" aria-label={`Record observations for ${candidateSymbol(candidate.symbol, candidate.mint)}`}>
        <button type="button" onClick={() => onCapture({ type: "focus" })}><Focus aria-hidden="true" /><span><strong>Deliberate focus</strong><small>Explicit research gesture</small></span></button>
        <button type="button" disabled={!nominationQualifies} aria-describedby={!nominationQualifies ? "protocol-nomination-block" : undefined} onClick={() => onCapture({ type: "nominate" })}><Tag aria-hidden="true" /><span><strong>Nominate</strong><small>{nominationQualifies ? "Left-truncated discovery is honest" : "No qualifying protocol nomination contract"}</small></span></button>
        <button type="button" onClick={() => onCapture({ type: "hot_scope" })}><Flame aria-hidden="true" /><span><strong>Request hot scope</strong><small>Ask sensing planner for richer observation</small></span></button>
        <button type="button" onClick={() => onCapture({ type: "disposition" })}><MessageSquareText aria-hidden="true" /><span><strong>Disposition</strong><small>Use your own provisional language</small></span></button>
        <button type="button" onClick={() => onCapture({ type: "crackle" })}><Sparkles aria-hidden="true" /><span><strong>Crackle family</strong><small>Name the shape without freezing it</small></span></button>
        <button type="button" onClick={() => onCapture({ type: "choice_set" })}><ListChecks aria-hidden="true" /><span><strong>Capture choices</strong><small>Served, filtered, viewport, or compared</small></span></button>
        <button type="button" onClick={() => onCapture({ type: "post_action", episodeId: episode?.id ?? null, relatedCommandId: latestCommandId })}><BookOpenCheck aria-hidden="true" /><span><strong>Quick report</strong><small>Post-action operator report</small></span></button>
        <button type="button" disabled={!episode || sourceCommandIds.length === 0} onClick={() => onCapture({ type: "interview", episodeId: episode?.id ?? null, sourceCommandIds })}><MessageSquareText aria-hidden="true" /><span><strong>Later interview</strong><small>{sourceCommandIds.length > 0 ? "Link reflection to exact episode records" : "Record an episode-linked report first"}</small></span></button>
      </div>
      {!nominationQualifies && <p id="protocol-nomination-block" className="operator-boundary">Prospective nomination is disabled: ordinary evidence command V2 does not bind the preregistered launch, as-of cut, universe, and deadline. Missing input is not a choice.</p>}
      {pendingReadbackError && <p className="replay-error" role="alert">Local pending-command readback gap: {pendingReadbackError}</p>}

      <div className="receipt-log" aria-live="polite" aria-label="Operator command receipts">
        <h3>Scene records</h3>
        {candidateEntries.length === 0 && <p>No semantic record has been appended for this candidate in this exact scene.</p>}
        {candidateEntries.slice().reverse().map((entry) => {
          const compensated = compensatedIds.has(entry.command.commandId);
          const priorSession = entry.command.clientSessionId !== currentClientSessionId;
          const repairOverdue = Date.parse(entry.pendingRepairRequiredAt) <= Date.now();
          return <article key={entry.command.commandId} data-status={entry.status}>
            <header><strong>{entry.label}</strong><span>{entry.status}</span></header>
            {entry.status === "submitting" && <small>Waiting for a durable receipt; no committed mark is rendered yet.</small>}
            {entry.status === "retaining_local" && <small>Retaining the exact canonical command in the bounded local pending cache before any server attempt.</small>}
            {entry.status === "queued" && <small><WifiOff aria-hidden="true" /> {priorSession ? "Recovered exact bytes from an earlier browser session. A freshly paired core can explicitly recover the unchanged command." : "Disconnected. The exact command envelope is retained for retry."}</small>}
            {entry.status === "queued" && repairOverdue && <small className="error-text">Retention repair is overdue. The bytes were not deleted; recover them against the paired core to release bounded local capacity.</small>}
            {entry.status === "rejected" && <small>{entry.error}</small>}
            {entry.receipt && <small>Commit {entry.receipt.commitSeq} · {entry.receipt.status} · {entry.receipt.commandDigest.slice(0, 20)}…</small>}
            {entry.receipt && entry.error && <small>Store ACK is authoritative; local cache cleanup needs repair: {entry.error}</small>}
            {compensated && <small>Compensated by a later append-only record.</small>}
            <div className="receipt-actions">
              {entry.status === "queued" && <button type="button" onClick={() => onRetry(entry.command.commandId)}><RotateCcw aria-hidden="true" /> {priorSession ? "Recover retained exact bytes" : "Retry exact record"}</button>}
              {entry.status === "committed" && entry.command.commandKind !== "compensate_command" && !compensated && <button type="button" onClick={() => onUndo(entry)}><Undo2 aria-hidden="true" /> Compensate</button>}
            </div>
          </article>;
        })}
      </div>
    </section>
  );
}
