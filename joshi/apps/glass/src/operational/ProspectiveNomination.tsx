import { useEffect, useMemo, useRef, useState } from "react";
import { BadgeCheck } from "lucide-react";

import { exactUtcNow } from "../operator/contract";
import { monotonicNanoseconds } from "../operator/useOperatorJournal";
import {
  decisionDeadlineFor,
  prospectiveNominationCommandV1Schema,
  warmupEndsAt,
  type EpisodeProtocolRegistrationV1,
  type ProspectiveNominationCommandV1,
  type ProspectiveNominationReceiptV1,
  type SessionLaunchV1,
} from "./contract";

export interface ProspectiveNominationSink {
  appendProspectiveNomination(command: ProspectiveNominationCommandV1, signal?: AbortSignal): Promise<ProspectiveNominationReceiptV1>;
}

export type ProspectiveChoiceBranch = "nomination" | "abstention";

export function ProspectiveNomination({
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
  sink: ProspectiveNominationSink;
  lockedBranch?: ProspectiveChoiceBranch | null;
  onBranchPrepared?: (branch: ProspectiveChoiceBranch) => void;
  onCommitted?: (branch: ProspectiveChoiceBranch) => void;
}) {
  const [subjectId, setSubjectId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [pending, setPending] = useState<ProspectiveNominationCommandV1 | null>(null);
  const [receipt, setReceipt] = useState<ProspectiveNominationReceiptV1 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const clockId = useRef(`nomination-clock-${globalThis.crypto?.randomUUID?.().replaceAll("-", "") ?? "fixture"}`).current;
  const deadline = useMemo(() => decisionDeadlineFor(protocol, launch.registration), [launch.registration, protocol]);
  const warmupEnd = useMemo(() => warmupEndsAt(protocol, launch.registration), [launch.registration, protocol]);
  const warmupComplete = now >= Date.parse(warmupEnd);
  const beforeDeadline = now < Date.parse(deadline);
  const otherBranchLocked = lockedBranch !== null && lockedBranch !== "nomination";
  const disabled = !warmupComplete || !beforeDeadline || otherBranchLocked || Boolean(receipt);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const append = async (command: ProspectiveNominationCommandV1) => {
    setPending(command);
    setError(null);
    try {
      const nextReceipt = await sink.appendProspectiveNomination(command);
      setReceipt(nextReceipt);
      setPending(null);
      onCommitted?.("nomination");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Prospective nomination was not durably received.");
    }
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const subject = launch.registration.choiceMembers.find((member) => member.subjectId === subjectId);
    if (!subject || !confirmed || disabled || pending) return;
    const command = prospectiveNominationCommandV1Schema.parse({
      contract: "joshi.operator.prospective_nomination",
      schemaVersion: 1,
      nominationId: launch.registration.reservedCommandId,
      idempotencyKey: launch.registration.reservedCommandIdempotencyKey,
      episodeLaunchId: launch.registration.launchId,
      clientSessionId,
      clientCommandSeq: "1",
      subject,
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
      issuedAt: exactUtcNow(),
      clientClock: { clockId, monotonicNs: monotonicNanoseconds() },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    onBranchPrepared?.("nomination");
    void append(command);
  };

  return (
    <aside className="prospective-decision" aria-labelledby="nomination-title">
      <div>
        <p className="eyebrow">Registered prospective choice</p>
        <h2 id="nomination-title"><BadgeCheck aria-hidden="true" /> Qualifying nomination</h2>
        <p>Choose only from the exact preregistered universe. Glass echoes the server-issued membership; it cannot add a candidate or mint membership evidence.</p>
        <p className="protocol-window" role="status">
          {otherBranchLocked && "The explicit-abstention branch already owns this reserved decision occurrence."}
          {!otherBranchLocked && !warmupComplete && `Warmup: choice remains disabled until ${warmupEnd}.`}
          {!otherBranchLocked && warmupComplete && beforeDeadline && `Choice window open · deadline ${deadline}.`}
          {!otherBranchLocked && !beforeDeadline && `Choice deadline passed at ${deadline}; no late nomination can qualify.`}
        </p>
      </div>
      <form onSubmit={submit}>
        <label htmlFor="prospective-nomination-subject">Preregistered subject</label>
        <select id="prospective-nomination-subject" value={subjectId} onChange={(event) => setSubjectId(event.target.value)} disabled={disabled}>
          <option value="">Choose an exact universe member…</option>
          {launch.registration.choiceMembers.map((member) => <option key={member.subjectId} value={member.subjectId}>{member.subjectId}</option>)}
        </select>
        <label className="confirm-abstention"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={disabled} /> Record this subject as the one prospective nomination</label>
        <button type="submit" className="primary-action" disabled={!subjectId || !confirmed || disabled || Boolean(pending)}>{pending ? "Awaiting durable receipt…" : receipt ? "Nomination committed" : "Record qualifying nomination"}</button>
        {error && pending && <button type="button" onClick={() => void append(pending)}>Retry exact bytes</button>}
      </form>
      {receipt && <p className="receipt-line" role="status">Durable nomination receipt · commit {receipt.commitSeq} · {receipt.status}</p>}
      {error && <p className="operational-error" role="alert">{error}</p>}
    </aside>
  );
}
