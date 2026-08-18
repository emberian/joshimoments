import { useEffect, useMemo, useRef, useState } from "react";
import { CircleSlash2 } from "lucide-react";

import { exactUtcNow } from "../operator/contract";
import { monotonicNanoseconds } from "../operator/useOperatorJournal";
import {
  decisionDeadlineFor,
  explicitAbstentionCommandV1Schema,
  warmupEndsAt,
  type EpisodeProtocolRegistrationV1,
  type ExplicitAbstentionCommandV1,
  type ExplicitAbstentionReceiptV1,
  type SessionLaunchV1,
} from "./contract";
import type { ProspectiveChoiceBranch } from "./ProspectiveNomination";

export interface AbstentionSink {
  appendAbstention(command: ExplicitAbstentionCommandV1, signal?: AbortSignal): Promise<ExplicitAbstentionReceiptV1>;
}

const reasons = [
  ["no_acceptable_candidate", "No acceptable candidate"],
  ["insufficient_evidence", "Insufficient evidence"],
  ["risk_boundary", "Risk boundary"],
  ["attention_limit", "Attention limit"],
] as const;

export function ProspectiveAbstention({
  launch,
  protocol,
  presentation,
  clientSessionId,
  sink,
  lockedBranch = null,
  onBranchPrepared,
  onCommitted,
}: {
  launch: SessionLaunchV1;
  protocol: EpisodeProtocolRegistrationV1;
  presentation: { presentationId: string; presentationDigest: string; assignmentId: string };
  clientSessionId: string;
  sink: AbstentionSink;
  lockedBranch?: ProspectiveChoiceBranch | null;
  onBranchPrepared?: (branch: ProspectiveChoiceBranch) => void;
  onCommitted?: (branch: ProspectiveChoiceBranch) => void;
}) {
  const [reason, setReason] = useState<"" | typeof reasons[number][0]>("");
  const [confirmed, setConfirmed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [pending, setPending] = useState<ExplicitAbstentionCommandV1 | null>(null);
  const [receipt, setReceipt] = useState<ExplicitAbstentionReceiptV1 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const clockId = useRef(`abstention-clock-${globalThis.crypto?.randomUUID?.().replaceAll("-", "") ?? "fixture"}`).current;
  const deadline = useMemo(() => decisionDeadlineFor(protocol, launch.registration), [launch.registration, protocol]);
  const warmupEnd = useMemo(() => warmupEndsAt(protocol, launch.registration), [launch.registration, protocol]);
  const warmupComplete = now >= Date.parse(warmupEnd);
  const beforeDeadline = now < Date.parse(deadline);
  const otherBranchLocked = lockedBranch !== null && lockedBranch !== "abstention";
  const disabled = !warmupComplete || !beforeDeadline || otherBranchLocked || Boolean(receipt);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const append = async (command: ExplicitAbstentionCommandV1) => {
    setPending(command);
    setError(null);
    try {
      const nextReceipt = await sink.appendAbstention(command);
      setReceipt(nextReceipt);
      setPending(null);
      onCommitted?.("abstention");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Explicit abstention was not durably received.");
    }
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!reason || !confirmed || disabled || pending) return;
    const command = explicitAbstentionCommandV1Schema.parse({
      contract: "joshi.operator.explicit_abstention",
      schemaVersion: 1,
      abstentionId: launch.registration.reservedCommandId,
      idempotencyKey: launch.registration.reservedCommandIdempotencyKey,
      episodeLaunchId: launch.registration.launchId,
      clientSessionId,
      clientCommandSeq: "1",
      cockpitPublicationId: launch.registration.cockpit.publicationId,
      scene: {
        sceneId: launch.registration.scene.sceneId,
        viewDigest: launch.registration.scene.viewDigest,
      },
      presentation: {
        presentationId: presentation.presentationId,
        presentationDigest: presentation.presentationDigest,
      },
      assignmentId: presentation.assignmentId,
      asOfDigest: launch.registration.asOfDigest,
      choiceUniverseDigest: launch.registration.choiceUniverseDigest,
      decisionDeadline: deadline,
      reason,
      issuedAt: exactUtcNow(),
      clientClock: { clockId, monotonicNs: monotonicNanoseconds() },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    onBranchPrepared?.("abstention");
    void append(command);
  };

  return (
    <aside className="prospective-decision" aria-labelledby="abstention-title">
      <div>
        <p className="eyebrow">Registered prospective choice</p>
        <h2 id="abstention-title"><CircleSlash2 aria-hidden="true" /> Explicit abstention</h2>
        <p>This records “choose none” for the preregistered universe. It does not trade, cancel, close, or modify a position.</p>
        <p className="protocol-window" role="status">
          {otherBranchLocked && "The nomination branch already owns this reserved decision occurrence."}
          {!otherBranchLocked && !warmupComplete && `Warmup: choice remains disabled until ${warmupEnd}.`}
          {!otherBranchLocked && warmupComplete && beforeDeadline && `Choice window open · deadline ${deadline}.`}
          {!otherBranchLocked && !beforeDeadline && `Choice deadline passed at ${deadline}; no late abstention can qualify.`}
        </p>
      </div>
      <form onSubmit={submit}>
        <label htmlFor="abstention-reason">Reason</label>
        <select id="abstention-reason" value={reason} onChange={(event) => setReason(event.target.value as typeof reason)} disabled={disabled}>
          <option value="">Choose a registered reason…</option>
          {reasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <label className="confirm-abstention"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={disabled} /> Record an explicit abstention for this exact choice universe</label>
        <button type="submit" className="primary-action" disabled={!reason || !confirmed || disabled || Boolean(pending)}>{pending ? "Awaiting durable receipt…" : receipt ? "Abstention committed" : "Record explicit abstention"}</button>
        {error && pending && <button type="button" onClick={() => void append(pending)}>Retry exact bytes</button>}
      </form>
      {receipt && <p className="receipt-line" role="status">Durable abstention receipt · commit {receipt.commitSeq} · {receipt.status}</p>}
      {error && <p className="operational-error" role="alert">{error}</p>}
    </aside>
  );
}
