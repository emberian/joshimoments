import * as Dialog from "@radix-ui/react-dialog";
import { Activity, Columns3, FlaskConical, MessageSquarePlus, Mic, Pin, ShieldCheck, X } from "lucide-react";
import { memo, useCallback, useMemo, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";

import type {
  ExplorationBundleV1,
  ExplorationPanel,
  PresentationEventReceiptV1,
  PresentationEvidenceClass,
  PresentationPolicyV1,
  PresentationSceneReceiptV1,
  PresentationViewKind,
} from "../presentation/contract";
import type { PresentationEventIntent } from "../presentation/usePresentationWitness";
import { presentationItemIdForView } from "../presentation/manifest";

const VIEW_ORDER: PresentationViewKind[] = [
  "wallet_cluster_flow",
  "caller_response_kernel",
  "attention_arrival",
  "marked_order_timing_size",
  "liquidity_susceptibility_resilience",
  "pvp_compression_churn",
  "lifecycle_topology",
  "field_bundle",
];

const EVIDENCE_CLASSES: Array<Exclude<PresentationEvidenceClass, "mixed">> = ["observed", "derived", "inferred", "uncertain"];

const VIEW_SHORT_LABELS: Record<PresentationViewKind, string> = {
  wallet_cluster_flow: "Wallet flow",
  caller_response_kernel: "Caller kernel",
  attention_arrival: "Attention",
  marked_order_timing_size: "Order marks",
  liquidity_susceptibility_resilience: "Liquidity",
  pvp_compression_churn: "PvP churn",
  lifecycle_topology: "Lifecycle",
  field_bundle: "Field bundle",
};

function evidenceLabel(value: PresentationEvidenceClass): string {
  if (value === "mixed") return "Mixed evidence — inspect every row";
  return `${value[0]?.toUpperCase()}${value.slice(1)}`;
}

function EvidenceBadge({ value }: { value: PresentationEvidenceClass }) {
  return <span className="lab-evidence" data-evidence={value}>{evidenceLabel(value)}</span>;
}

function PanelTable({ panel, visibleEvidence }: { panel: ExplorationPanel; visibleEvidence: Set<string> }) {
  const signals = panel.signals.filter((item) => visibleEvidence.has(item.lineage.evidenceClass));
  const relations = panel.relations.filter((item) => visibleEvidence.has(item.lineage.evidenceClass));
  const marks = panel.marks.filter((item) => visibleEvidence.has(item.lineage.evidenceClass));
  const hidden = panel.signals.length + panel.relations.length + panel.marks.length - signals.length - relations.length - marks.length;
  // A panel the evidence cut produced no row for must say so. Rendering the header and then
  // nothing reads as a load failure, and a blank is exactly the shape a reader fills in.
  const empty = panel.signals.length === 0 && panel.relations.length === 0 && panel.marks.length === 0;

  return <article className="field-view" aria-labelledby={`${panel.panelId}-title`} data-presentation-item={panel.panelId}>
    <header className="field-view-header">
      <div>
        <p className="eyebrow">Exploratory view · {panel.viewKind.replaceAll("_", " ")}</p>
        <h3 id={`${panel.panelId}-title`}>{panel.title}</h3>
      </div>
      <EvidenceBadge value={panel.evidenceClass} />
    </header>
    <p className="field-question"><strong>Question:</strong> {panel.question}</p>
    <p className="claim-boundary"><ShieldCheck aria-hidden="true" /><span><strong>Claim boundary.</strong> {panel.claimBoundary}</span></p>
    {hidden > 0 && <p className="lab-omission" role="status">{hidden} row{hidden === 1 ? "" : "s"} intentionally hidden by the current evidence toggle; the presentation event records that omission.</p>}
    {empty && <p className="lab-absence" role="status"><strong>No rows in this evidence cut.</strong> This view carries no signal, relation, or mark for the served scene. That is an absent record, not a zero and not a finding.</p>}

    {signals.length > 0 && <div className="field-table-wrap">
      <table className="field-table">
        <caption>Measures, exact display values, support, and lineage</caption>
        <thead><tr><th scope="col">Field</th><th scope="col">Value</th><th scope="col">Evidence</th><th scope="col">Support and uncertainty</th></tr></thead>
        <tbody>{signals.map((signal) => <tr key={signal.signalId}>
          <th scope="row">{signal.label}</th>
          <td><strong>{signal.value.value}</strong>{signal.value.unit ? ` ${signal.value.unit}` : ""}{signal.interval && <small>interval {signal.interval.lower}–{signal.interval.upper}</small>}</td>
          <td><EvidenceBadge value={signal.lineage.evidenceClass} /><small>{signal.lineage.epistemicLabel.replaceAll("_", " ")} · {signal.lineage.coverage.replaceAll("_", " ")}</small></td>
          <td>{signal.support}<small>{signal.lineage.uncertainty} · ref {signal.lineage.sourceRef}</small></td>
        </tr>)}</tbody>
      </table>
    </div>}

    {relations.length > 0 && <div className="field-table-wrap">
      <table className="field-table">
        <caption>Typed, directed relations with competing explanations</caption>
        <thead><tr><th scope="col">From → to</th><th scope="col">Relation</th><th scope="col">Evidence</th><th scope="col">Alternative</th></tr></thead>
        <tbody>{relations.map((relation) => <tr key={relation.relationId}>
          <th scope="row">{relation.from} <span aria-hidden="true">→</span><span className="sr-only">to</span> {relation.to}</th>
          <td>{relation.relation}{relation.value && <small>{relation.value.value}{relation.value.unit ? ` ${relation.value.unit}` : ""}</small>}</td>
          <td><EvidenceBadge value={relation.lineage.evidenceClass} /><small>{relation.direction}</small></td>
          <td>{relation.alternative ?? "No alternative encoded"}<small>{relation.lineage.uncertainty}</small></td>
        </tr>)}</tbody>
      </table>
    </div>}

    {marks.length > 0 && <div className="field-table-wrap">
      <table className="field-table">
        <caption>Time and size marks; text equivalent to any future chart overlay</caption>
        <thead><tr><th scope="col">At</th><th scope="col">Mark</th><th scope="col">Exact size</th><th scope="col">Lineage</th></tr></thead>
        <tbody>{marks.map((mark) => <tr key={mark.markId}>
          <th scope="row"><time dateTime={mark.at}>{mark.at}</time></th>
          <td>{mark.label}<small>{mark.detail}</small></td>
          <td>{mark.size ? `${mark.size.value}${mark.size.unit ? ` ${mark.size.unit}` : ""}` : "not applicable"}</td>
          <td><EvidenceBadge value={mark.lineage.evidenceClass} /><small>{mark.lineage.uncertainty}</small></td>
        </tr>)}</tbody>
      </table>
    </div>}
  </article>;
}

function UsefulnessDialog({
  open,
  onOpenChange,
  onRecord,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  onRecord(intent: PresentationEventIntent): Promise<string | null>;
}) {
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    await onRecord({
      eventKind: "usefulness_reported",
      subject: { kind: "presentation", key: "hypothesis-lab" },
      payload: {
        usefulness: String(data.get("usefulness")) as "helpful" | "neutral" | "harmful" | "unknown",
        decisionLatency: String(data.get("decisionLatency")) as "faster" | "unchanged" | "slower" | "unknown",
        attentionCost: String(data.get("attentionCost")) as "lower" | "unchanged" | "higher" | "unknown",
        overtrading: String(data.get("overtrading")) as "less" | "unchanged" | "more" | "unknown",
        regret: String(data.get("regret")) as "present" | "absent" | "unknown",
        missedOpportunity: String(data.get("missedOpportunity")) as "present" | "absent" | "unknown",
        pnl: { status: "awaiting_reconciled_projection", projectionDigest: null },
        note: String(data.get("note") ?? "").trim() || null,
      },
    });
    setSubmitting(false);
    onOpenChange(false);
  }

  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="capture-overlay" />
      <Dialog.Content className="capture-dialog usefulness-dialog" aria-describedby="usefulness-description" data-shortcuts-disabled="true">
        <header><span><MessageSquarePlus aria-hidden="true" /><Dialog.Title>Was this presentation useful?</Dialog.Title></span><Dialog.Close className="icon-button" aria-label="Close usefulness annotation"><X aria-hidden="true" /></Dialog.Close></header>
        <Dialog.Description id="usefulness-description">A short after-action report. PnL is linked later from reconciled accounting; this form never computes or accepts financial truth.</Dialog.Description>
        <form onSubmit={submit} className="usefulness-form">
          <label>Overall usefulness<select name="usefulness" defaultValue="unknown"><option value="unknown">Unknown</option><option value="helpful">Helpful</option><option value="neutral">Neutral</option><option value="harmful">Harmful</option></select></label>
          <label>Decision latency<select name="decisionLatency" defaultValue="unknown"><option value="unknown">Unknown</option><option value="faster">Felt faster</option><option value="unchanged">Unchanged</option><option value="slower">Felt slower</option></select></label>
          <label>Attention cost<select name="attentionCost" defaultValue="unknown"><option value="unknown">Unknown</option><option value="lower">Lower</option><option value="unchanged">Unchanged</option><option value="higher">Higher</option></select></label>
          <label>Overtrading tendency<select name="overtrading" defaultValue="unknown"><option value="unknown">Unknown</option><option value="less">Less</option><option value="unchanged">Unchanged</option><option value="more">More</option></select></label>
          <label>Regret<select name="regret" defaultValue="unknown"><option value="unknown">Unknown</option><option value="absent">Absent</option><option value="present">Present</option></select></label>
          <label>Missed opportunity<select name="missedOpportunity" defaultValue="unknown"><option value="unknown">Unknown</option><option value="absent">Absent</option><option value="present">Present</option></select></label>
          <label className="full-span">Optional note<textarea name="note" maxLength={2000} rows={4} placeholder="What became easier, harder, or newly visible?" /></label>
          <p className="pnl-boundary full-span"><strong>PnL:</strong> awaiting a reconciled, versioned accounting projection. No number is entered or derived here.</p>
          <div className="dialog-actions full-span"><button type="button" className="secondary-action" onClick={() => onOpenChange(false)}>Cancel</button><button type="submit" className="primary-action" disabled={submitting}>{submitting ? "Recording…" : "Record usefulness"}</button></div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

export const HypothesisLab = memo(function HypothesisLab({
  bundle,
  policies,
  initialPolicy,
  presentationReceipt,
  presentationError,
  eventReceipts,
  eventGap,
  onRecordEvent,
  onAdmitPolicy,
}: {
  bundle: ExplorationBundleV1;
  policies: PresentationPolicyV1[];
  initialPolicy: PresentationPolicyV1;
  presentationReceipt: PresentationSceneReceiptV1 | null;
  presentationError: string | null;
  eventReceipts: PresentationEventReceiptV1[];
  eventGap: string | null;
  onRecordEvent(intent: PresentationEventIntent): Promise<string | null>;
  onAdmitPolicy(policy: PresentationPolicyV1): Promise<boolean>;
}) {
  const [policyId, setPolicyId] = useState(initialPolicy.policyId);
  const [assigningPolicy, setAssigningPolicy] = useState(false);
  const [activeKind, setActiveKind] = useState<PresentationViewKind>(initialPolicy.primaryView);
  const [pinnedKinds, setPinnedKinds] = useState<PresentationViewKind[]>([]);
  const [compare, setCompare] = useState(false);
  const [usefulnessOpen, setUsefulnessOpen] = useState(false);
  const [visibleEvidence, setVisibleEvidence] = useState<Set<string>>(() => new Set(EVIDENCE_CLASSES));
  const panels = useMemo(() => new Map(bundle.panels.map((panel) => [panel.viewKind, panel])), [bundle]);
  const activePolicy = policies.find((policy) => policy.policyId === policyId) ?? initialPolicy;

  const record = useCallback((intent: PresentationEventIntent) => { void onRecordEvent(intent); }, [onRecordEvent]);

  const selectView = useCallback((nextKind: PresentationViewKind) => {
    if (nextKind === activeKind) return;
    if (!compare || !pinnedKinds.includes(activeKind)) {
      record({ eventKind: "visibility_ended", subject: { kind: "panel", key: presentationItemIdForView(activeKind) }, payload: { reason: "operator_navigation" } });
    }
    record({ eventKind: "control_changed", subject: { kind: "control", key: "active-view" }, payload: { controlKind: "filter", controlId: "active-view", previousValue: activeKind, nextValue: nextKind } });
    if (!compare || !pinnedKinds.includes(nextKind)) {
      record({ eventKind: "visibility_started", subject: { kind: "panel", key: presentationItemIdForView(nextKind) }, payload: { reason: "operator_navigation" } });
    }
    setActiveKind(nextKind);
  }, [activeKind, compare, pinnedKinds, record]);

  const selectPolicy = async (nextPolicyId: string) => {
    const nextPolicy = policies.find((policy) => policy.policyId === nextPolicyId);
    if (!nextPolicy || nextPolicy.policyId === activePolicy.policyId) return;
    setAssigningPolicy(true);
    const admitted = await onAdmitPolicy(nextPolicy);
    setAssigningPolicy(false);
    if (!admitted) return;
    setPolicyId(nextPolicy.policyId);
    setActiveKind(nextPolicy.primaryView);
    setPinnedKinds([]);
    setCompare(false);
  };

  const toggleEvidence = (evidence: string) => {
    const wasVisible = visibleEvidence.has(evidence);
    setVisibleEvidence((current) => {
      const next = new Set(current);
      if (wasVisible) next.delete(evidence); else next.add(evidence);
      return next;
    });
    record({ eventKind: "control_changed", subject: { kind: "overlay", key: evidence }, payload: { controlKind: "toggle", controlId: `evidence-${evidence}`, previousValue: String(wasVisible), nextValue: String(!wasVisible) } });
    record({ eventKind: wasVisible ? "visibility_ended" : "visibility_started", subject: { kind: "overlay", key: evidence }, payload: { reason: "policy_change" } });
  };

  const togglePin = () => {
    const pinned = pinnedKinds.includes(activeKind);
    const next = pinned ? pinnedKinds.filter((kind) => kind !== activeKind) : [...pinnedKinds, activeKind].slice(-3);
    setPinnedKinds(next);
    record({ eventKind: "control_changed", subject: { kind: "panel", key: presentationItemIdForView(activeKind) }, payload: { controlKind: "pin", controlId: "pinned-views", previousValue: pinnedKinds.join(",") || "none", nextValue: next.join(",") || "none" } });
  };

  const toggleCompare = () => {
    setCompare(!compare);
    record({ eventKind: "control_changed", subject: { kind: "control", key: "comparison" }, payload: { controlKind: "comparison", controlId: "comparison", previousValue: String(compare), nextValue: String(!compare) } });
    for (const kind of pinnedKinds) {
      if (kind === activeKind) continue;
      record({ eventKind: compare ? "visibility_ended" : "visibility_started", subject: { kind: "panel", key: presentationItemIdForView(kind) }, payload: { reason: "policy_change" } });
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.target instanceof HTMLElement && event.target.matches("input, textarea, select")) return;
    let nextIndex: number | null = null;
    if (event.key === "]") nextIndex = (VIEW_ORDER.indexOf(activeKind) + 1) % VIEW_ORDER.length;
    if (event.key === "[") nextIndex = (VIEW_ORDER.indexOf(activeKind) - 1 + VIEW_ORDER.length) % VIEW_ORDER.length;
    if (/^[1-8]$/.test(event.key)) nextIndex = Number(event.key) - 1;
    const next = nextIndex === null ? undefined : VIEW_ORDER[nextIndex];
    if (next) {
      event.preventDefault();
      selectView(next);
    }
  };

  const shownKinds = compare
    ? [...new Set([activeKind, ...pinnedKinds])]
    : [activeKind];

  if (!presentationReceipt && !presentationError) {
    return <section id="hypothesis-lab" className="panel hypothesis-lab lab-staging" aria-labelledby="hypothesis-lab-title" tabIndex={-1} data-presentation-item="hypothesis-lab">
      <header className="panel-header lab-header"><div><p className="eyebrow">Presentation hypothesis · operator selected</p><h2 id="hypothesis-lab-title"><FlaskConical aria-hidden="true" /> Field lab</h2></div><span className="presentation-receipt" data-status="staging"><span aria-hidden="true">●</span> recording exact scene…</span></header>
      <p role="status">Staging the exact policy, evidence bundle, visibility, ordering, salience, toggles, and omissions before revealing this lab.</p>
    </section>;
  }

  return <section
    id="hypothesis-lab"
    className="panel hypothesis-lab"
    aria-labelledby="hypothesis-lab-title"
    onKeyDown={onKeyDown}
    onFocusCapture={(event) => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
        record({ eventKind: "focus_started", subject: { kind: "panel", key: "hypothesis-lab" }, payload: { reason: "operator_navigation" } });
      }
    }}
    onBlurCapture={(event) => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
        record({ eventKind: "focus_ended", subject: { kind: "panel", key: "hypothesis-lab" }, payload: { reason: "operator_navigation" } });
      }
    }}
    tabIndex={-1}
    data-presentation-item="hypothesis-lab"
  >
    <header className="panel-header lab-header">
      <div><p className="eyebrow">Presentation hypothesis · operator selected</p><h2 id="hypothesis-lab-title"><FlaskConical aria-hidden="true" /> Field lab</h2></div>
      <span className="presentation-receipt" data-status={presentationReceipt ? "witnessed" : presentationError ? "gap" : "staging"}><span aria-hidden="true">●</span> {presentationReceipt ? `witnessed · commit ${presentationReceipt.commitSeq}` : presentationError ? "capture gap" : "recording exact scene…"}</span>
    </header>
    <div className="lab-policy-row">
      <label>Presentation policy<select value={activePolicy.policyId} disabled={assigningPolicy} onChange={(event) => { void selectPolicy(event.target.value); }} data-voice-command="select-presentation-policy">{policies.map((policy) => <option key={policy.policyId} value={policy.policyId}>{policy.title}</option>)}</select></label>
      <p><strong>Hypothesis:</strong> {activePolicy.hypothesis}</p>
      <p className="lab-safety">Manual selection only. No live randomization. Exposure and source truth remain visible outside this lab.</p>
    </div>

    <div className="lab-view-strip" aria-label="Exploratory views">
      {VIEW_ORDER.map((kind, index) => <button key={kind} type="button" className="lab-view-button" aria-label={VIEW_SHORT_LABELS[kind]} aria-pressed={kind === activeKind} onClick={() => selectView(kind)} data-voice-command={`show-${kind}`} aria-keyshortcuts={String(index + 1)}><span aria-hidden="true">{index + 1}</span>{VIEW_SHORT_LABELS[kind]}</button>)}
    </div>
    <div className="lab-controls">
      <fieldset><legend>Evidence overlays</legend>{EVIDENCE_CLASSES.map((evidence) => <label key={evidence} className="evidence-toggle"><input type="checkbox" checked={visibleEvidence.has(evidence)} onChange={() => toggleEvidence(evidence)} /><EvidenceBadge value={evidence} /></label>)}</fieldset>
      <div className="lab-actions">
        <button type="button" className="secondary-action" aria-pressed={pinnedKinds.includes(activeKind)} onClick={togglePin} data-voice-command="pin-current-view"><Pin aria-hidden="true" />{pinnedKinds.includes(activeKind) ? "Unpin" : "Pin"}</button>
        <button type="button" className="secondary-action" aria-pressed={compare} onClick={toggleCompare} data-voice-command="compare-pinned-views"><Columns3 aria-hidden="true" />Compare {pinnedKinds.length > 0 ? `(${pinnedKinds.length + 1})` : ""}</button>
        <button type="button" className="secondary-action" onClick={() => { record({ eventKind: "voice_capture_hook", subject: { kind: "control", key: "voice-capture" }, payload: { actionId: "hypothesis-lab-context", transcript: null } }); }} data-voice-command="capture-current-lab-context"><Mic aria-hidden="true" />Voice-ready hook</button>
        <button type="button" className="secondary-action" onClick={() => setUsefulnessOpen(true)} data-voice-command="report-presentation-usefulness"><MessageSquarePlus aria-hidden="true" />After-action note</button>
      </div>
    </div>
    <p className="lab-shortcuts"><Activity aria-hidden="true" /> Use <kbd>1</kbd>–<kbd>8</kbd> or <kbd>[</kbd>/<kbd>]</kbd> while this lab is focused. Every policy, view, overlay, pin, and comparison change is a semantic presentation event.</p>
    {eventGap && <p className="presentation-gap" role="alert"><strong>Presentation capture gap.</strong> {eventGap} Information remains visible; this interval must not be treated as fully witnessed.</p>}
    {presentationError && <p className="presentation-gap" role="alert"><strong>Initial presentation was not durably witnessed.</strong> {presentationError} Rich information remains visible, but this exposure is an explicit coverage gap.</p>}
    <div className={`field-view-grid${compare ? " is-comparing" : ""}`}>
      {shownKinds.map((kind) => {
        const panel = panels.get(kind);
        return panel ? <PanelTable key={panel.panelId} panel={panel} visibleEvidence={visibleEvidence} /> : null;
      })}
    </div>
    <details className="lab-artifact-closure">
      <summary>Exact exploration artifact closure · {bundle.sourceArtifacts.length} source artifacts</summary>
      <div className="field-table-wrap"><table className="field-table"><caption>Source artifacts bound into this exploration bundle · claim {bundle.claim.replaceAll("_", " ")}</caption><thead><tr><th scope="col">Artifact</th><th scope="col">Admission</th><th scope="col">Available</th><th scope="col">Digest</th></tr></thead><tbody>{bundle.sourceArtifacts.map((artifact) => <tr key={artifact.artifactId}><th scope="row">{artifact.artifactId}<small>{artifact.contract}</small></th><td>{artifact.admissionStatus.replaceAll("_", " ")}<small>{artifact.coverageBinding.replaceAll("_", " ")}</small></td><td><time dateTime={artifact.availableAt}>{artifact.availableAt}</time></td><td>{artifact.artifactDigest}</td></tr>)}</tbody></table></div>
    </details>
    <footer className="lab-footer">
      <span>Policy {activePolicy.policyId} v{activePolicy.policyVersion}</span>
      <span>Evidence cut {bundle.scene.sceneId}</span>
      <span>{eventReceipts.length} interaction receipt{eventReceipts.length === 1 ? "" : "s"}</span>
      <span>No scalar pressure · no client-side financial truth</span>
    </footer>
    <UsefulnessDialog open={usefulnessOpen} onOpenChange={setUsefulnessOpen} onRecord={onRecordEvent} />
  </section>;
});
