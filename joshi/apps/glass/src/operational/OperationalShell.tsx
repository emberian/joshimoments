import { useEffect, useMemo, useState } from "react";
import { KeyRound, LockKeyhole, RotateCcw, ShieldCheck } from "lucide-react";

import { GlassApp } from "../App";
import { LoopbackOperatorSink } from "../operator/client";
import type { OperatorCommandSink } from "../operator/client";
import { LoopbackPresentationSink } from "../presentation/client";
import type { PresentationSink } from "../presentation/client";
import type { GlassDataSource } from "../data/client";
import {
  glassPairingSession,
  MemoryOnlyPairingSession,
  PairingSessionRejectedError,
} from "../security/pairing";
import { CockpitPublicationDataSource, SameOriginOperationalClient } from "./client";
import { ProspectiveAbstention } from "./ProspectiveAbstention";
import { ProspectiveNomination, type ProspectiveChoiceBranch } from "./ProspectiveNomination";
import type {
  CockpitPublicationIndexV1,
  CockpitLaunchEnvelopeV1,
  PairingSessionV1,
  SessionLaunchV1,
  ExplicitAbstentionCommandV1,
  ExplicitAbstentionReceiptV1,
  ProspectiveNominationCommandV1,
  ProspectiveNominationReceiptV1,
} from "./contract";
import { digestExplorationBundle, digestPresentationPolicy } from "../presentation/contract";

export interface OperationalClient {
  exchange(oneTimeCode: string, signal?: AbortSignal): Promise<Omit<PairingSessionV1, "capability">>;
  listPublications(signal?: AbortSignal): Promise<CockpitPublicationIndexV1>;
  openPublication(cockpitPublicationId: string, signal?: AbortSignal): Promise<CockpitLaunchEnvelopeV1>;
  loadSessionLaunch?(signal?: AbortSignal): Promise<SessionLaunchV1>;
  appendAbstention?(command: ExplicitAbstentionCommandV1, signal?: AbortSignal): Promise<ExplicitAbstentionReceiptV1>;
  appendProspectiveNomination?(command: ProspectiveNominationCommandV1, signal?: AbortSignal): Promise<ProspectiveNominationReceiptV1>;
}

export type OperationalRuntime = {
  source: GlassDataSource;
  operatorSink: OperatorCommandSink;
  presentationSink: PresentationSink;
};

export function OperationalGlassShell({
  session = glassPairingSession,
  client,
  runtimeFactory,
  mode = "browse",
}: {
  session?: MemoryOnlyPairingSession;
  client?: OperationalClient;
  runtimeFactory?: (client: OperationalClient, publication: CockpitLaunchEnvelopeV1, session: MemoryOnlyPairingSession) => OperationalRuntime;
  mode?: "browse" | "prospective";
}) {
  // The core deliberately does not mount ordinary pairing in this settle.  A supplied client is
  // a test-only/integration seam; the production entrypoint passes none, so Glass must show an
  // honest unavailable state rather than collect a code for a route that does not exist.
  const ordinaryPairingRouteReviewed = client !== undefined;
  const resolvedClient = useMemo<OperationalClient>(() => client ?? new SameOriginOperationalClient(session), [client, session]);
  const [sessionVersion, setSessionVersion] = useState(0);
  const [oneTimeCode, setOneTimeCode] = useState("");
  const [index, setIndex] = useState<CockpitPublicationIndexV1 | null>(null);
  const [publication, setPublication] = useState<CockpitLaunchEnvelopeV1 | null>(null);
  const [sessionLaunch, setSessionLaunch] = useState<SessionLaunchV1 | null>(null);
  const [presentationBinding, setPresentationBinding] = useState<{ presentationId: string; presentationDigest: string; assignmentId: string } | null>(null);
  const [prospectiveChoiceBranch, setProspectiveChoiceBranch] = useState<ProspectiveChoiceBranch | null>(null);
  const [status, setStatus] = useState<"unpaired" | "pairing" | "loading_index" | "selecting" | "opening" | "open">("unpaired");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => session.subscribe(() => setSessionVersion((value) => value + 1)), [session]);

  const paired = session.paired();
  const descriptor = session.descriptor();
  const runtime = useMemo(() => publication
    ? runtimeFactory?.(resolvedClient, publication, session) ?? {
        source: new CockpitPublicationDataSource(resolvedClient, publication),
        operatorSink: new LoopbackOperatorSink(window.location.origin, session, true),
        presentationSink: new LoopbackPresentationSink(window.location.origin, session, true),
      }
    : null, [publication, resolvedClient, runtimeFactory, session]);

  useEffect(() => {
    if (paired) return;
    setIndex(null);
    setPublication(null);
    setSessionLaunch(null);
    setPresentationBinding(null);
    setProspectiveChoiceBranch(null);
    setStatus("unpaired");
  }, [paired, sessionVersion]);

  useEffect(() => {
    if (!descriptor) return;
    const remaining = Date.parse(descriptor.expiresAt) - Date.now();
    if (remaining <= 0) {
      session.clear();
      return;
    }
    const timer = window.setTimeout(() => session.clear(), Math.min(remaining, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [descriptor?.expiresAt, session]);

  const loadIndex = async () => {
    setStatus("loading_index");
    setError(null);
    try {
      const nextIndex = await resolvedClient.listPublications();
      setIndex(nextIndex);
      setStatus("selecting");
    } catch (cause) {
      if (cause instanceof PairingSessionRejectedError) setStatus("unpaired");
      else setStatus("selecting");
      setError(cause instanceof Error ? cause.message : "Could not load immutable cockpit publications.");
    }
  };

  const pair = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submittedCode = oneTimeCode;
    setOneTimeCode("");
    setStatus("pairing");
    setError(null);
    try {
      await resolvedClient.exchange(submittedCode);
      if (mode === "prospective") await loadProspectiveSession();
      else await loadIndex();
    } catch (cause) {
      session.clear();
      setStatus("unpaired");
      setError(cause instanceof Error ? cause.message : "Pairing failed.");
    }
  };

  const loadProspectiveSession = async () => {
    if (!resolvedClient.loadSessionLaunch) throw new Error("Prospective session-launch transport is unavailable.");
    setStatus("opening");
    const bound = await resolvedClient.loadSessionLaunch();
    const opened = await resolvedClient.openPublication(bound.registration.cockpit.publicationId);
    if (opened.launch.cockpitPublication.cockpitPublicationId !== bound.registration.cockpit.publicationId
      || opened.launch.cockpitPublication.cockpitPublicationDigest !== bound.registration.cockpit.publicationDigest
      || opened.launch.snapshot.view.sceneId !== bound.registration.scene.sceneId
      || opened.launch.snapshot.snapshotDigest !== bound.registration.scene.viewDigest
      || opened.launch.presentationPolicy.policyId !== bound.registration.presentation.policyId
      || digestPresentationPolicy(opened.launch.presentationPolicy) !== bound.registration.presentation.policyDigest
      || opened.launch.explorationBundle.bundleId !== bound.registration.presentation.bundleId
      || digestExplorationBundle(opened.launch.explorationBundle) !== bound.registration.presentation.bundleDigest) {
      throw new Error("Server-bound prospective launch does not close to the exact cockpit, scene, policy, or bundle.");
    }
    setSessionLaunch(bound);
    setProspectiveChoiceBranch(null);
    setPublication(opened);
    setStatus("open");
  };

  const open = async (cockpitPublicationId: string) => {
    const summary = index?.publications.find((candidate) => candidate.cockpitPublicationId === cockpitPublicationId);
    if (!summary) return;
    setStatus("opening");
    setError(null);
    try {
      const opened = await resolvedClient.openPublication(cockpitPublicationId);
      if (opened.launch.cockpitPublication.cockpitPublicationDigest !== summary.cockpitPublicationDigest
        || opened.launch.snapshot.view.sceneId !== summary.scene.sceneId
        || opened.launch.snapshot.snapshotDigest !== summary.scene.viewDigest) {
        throw new Error("Opened cockpit publication does not match the explicitly selected immutable index entry.");
      }
      setPublication(opened);
      setStatus("open");
    } catch (cause) {
      if (cause instanceof PairingSessionRejectedError) setStatus("unpaired");
      else setStatus("selecting");
      setError(cause instanceof Error ? cause.message : "Could not open the selected cockpit publication.");
    }
  };

  const leavePublication = () => {
    if (mode === "prospective") {
      endSession();
      return;
    }
    setPublication(null);
    setStatus("selecting");
  };

  const endSession = () => {
    setOneTimeCode("");
    setError(null);
    session.clear();
  };

  if (!ordinaryPairingRouteReviewed) {
    return (
      <main className="operational-gate">
        <section className="operational-card" aria-labelledby="pairing-title">
          <div className="operational-icon" aria-hidden="true"><LockKeyhole /></div>
          <p className="eyebrow">Local operational shell</p>
          <h1 id="pairing-title">Live pairing is unavailable</h1>
          <p>The ordinary same-origin pairing exchange and store-backed cockpit publication routes are not mounted or qualified. Glass will not collect a one-time code, synthesize a session, or select a current publication.</p>
          <p className="safety-ceiling"><ShieldCheck aria-hidden="true" /> Read-only fixture development remains separate. No live publication, scientific-memory act, research admission, signer, wallet, transaction builder, or trading authority is available here.</p>
        </section>
      </main>
    );
  }

  if (!paired || !descriptor) {
    return (
      <main className="operational-gate">
        <section className="operational-card" aria-labelledby="pairing-title">
          <div className="operational-icon" aria-hidden="true"><LockKeyhole /></div>
          <p className="eyebrow">Local operational shell</p>
          <h1 id="pairing-title">Pair this Glass session</h1>
          <p id="pairing-help">Enter the short-lived one-time code shown by the local Joshi launcher. It is consumed once. The resulting capability stays only in this page’s memory and disappears on reload.</p>
          <form onSubmit={(event) => void pair(event)} className="pairing-form">
            <label htmlFor="pairing-code">One-time pairing code</label>
            <input
              id="pairing-code"
              name="pairing-code"
              autoComplete="one-time-code"
              inputMode="text"
              spellCheck={false}
              autoCapitalize="characters"
              required
              minLength={45}
              maxLength={45}
              pattern="JOSHI-(?:[0-9A-HJKMNP-TV-Z]{4}-){7}[0-9A-HJKMNP-TV-Z]{4}"
              value={oneTimeCode}
              onChange={(event) => setOneTimeCode(event.target.value)}
              aria-describedby="pairing-help"
            />
            <button type="submit" className="primary-action" disabled={status === "pairing"}>
              <KeyRound aria-hidden="true" /> {status === "pairing" ? "Pairing…" : "Pair locally"}
            </button>
          </form>
          <p className="safety-ceiling"><ShieldCheck aria-hidden="true" /> Read, record, and replay only. No signer, wallet, transaction builder, or trading authority exists here.</p>
          {error && <p role="alert" className="operational-error">{error}</p>}
        </section>
      </main>
    );
  }

  if (publication && runtime) {
    return (
      <div className="operational-session">
        <nav className="operational-session-bar" aria-label="Operational session">
          <span><ShieldCheck aria-hidden="true" /> Evidence-only session · expires {descriptor.expiresAt}</span>
          <span>{sessionLaunch ? `Registered launch ${sessionLaunch.registration.launchId}` : "Publication"} · {publication.launch.cockpitPublication.cockpitPublicationId} · {publication.launch.freshness}</span>
          <button type="button" onClick={leavePublication}><RotateCcw aria-hidden="true" /> {mode === "prospective" ? "End registered session" : "Choose publication"}</button>
          <button type="button" onClick={endSession}>End session</button>
        </nav>
        <GlassApp
          key={publication.launch.cockpitPublication.cockpitPublicationId}
          dataSource={runtime.source}
          operatorSink={runtime.operatorSink}
          presentationSink={runtime.presentationSink}
          launchMode={publication.launch.snapshot.view.mode}
          requireOperationalWitness={mode === "prospective"}
          presentationIdentity={sessionLaunch ? {
            presentationId: sessionLaunch.registration.reservedPresentationId,
            assignmentId: sessionLaunch.registration.presentation.assignmentId,
          } : null}
          onPresentationBinding={setPresentationBinding}
          prospectiveProtocol={mode === "prospective"}
        />
        {mode === "prospective" && sessionLaunch && presentationBinding && (
          resolvedClient.appendAbstention && resolvedClient.appendProspectiveNomination
            ? <section className="prospective-choice-branches" aria-label="Preregistered prospective choice branches">
                <ProspectiveNomination
                  launch={sessionLaunch}
                  protocol={sessionLaunch.protocol}
                  presentation={presentationBinding}
                  clientSessionId={descriptor.sessionId}
                  sink={{ appendProspectiveNomination: resolvedClient.appendProspectiveNomination.bind(resolvedClient) }}
                  lockedBranch={prospectiveChoiceBranch}
                  onBranchPrepared={setProspectiveChoiceBranch}
                />
                <ProspectiveAbstention
                launch={sessionLaunch}
                protocol={sessionLaunch.protocol}
                presentation={presentationBinding}
                clientSessionId={descriptor.sessionId}
                sink={{ appendAbstention: resolvedClient.appendAbstention.bind(resolvedClient) }}
                lockedBranch={prospectiveChoiceBranch}
                onBranchPrepared={setProspectiveChoiceBranch}
              />
              </section>
            : <p className="operational-error" role="alert">The dedicated prospective nomination and explicit-abstention receipt paths are unavailable. General evidence commands and missing input will not be counted as a protocol choice.</p>
        )}
      </div>
    );
  }

  return (
    <main className="operational-gate operational-selection">
      <section className="operational-card wide" aria-labelledby="publication-title">
        <p className="eyebrow">Paired · evidence-only</p>
        <h1 id="publication-title">Choose an immutable cockpit publication</h1>
        <p>Nothing opens automatically. Each row names an exact scene and digest; newer publications append and supersede instead of moving a “latest” pointer.</p>
        <dl className="session-summary">
          <div><dt>Session</dt><dd>{descriptor.sessionId}</dd></div>
          <div><dt>Expires</dt><dd>{descriptor.expiresAt}</dd></div>
          <div><dt>Scope</dt><dd>{descriptor.scopes.join(" · ")}</dd></div>
          <div><dt>Authority</dt><dd>{descriptor.authority.replaceAll("_", " ")}</dd></div>
        </dl>
        {status === "loading_index" && <p role="status">Loading durable publication IDs…</p>}
        {status === "opening" && <p role="status">Verifying the selected publication and its evidence closure…</p>}
        {index && index.publications.length === 0 && <p>No durable cockpit publications are available. Glass will not invent a current view.</p>}
        {index && index.publications.length > 0 && (
          <ul className="publication-list" aria-label="Immutable cockpit publications">
            {index.publications.map((item) => (
              <li key={item.cockpitPublicationId}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.mode.replaceAll("_", " ")} · {item.freshness} · {item.publishedAt}</span>
                  <code>{item.scene.sceneId}</code>
                  <small>{item.cockpitPublicationDigest}</small>
                </div>
                <button type="button" className="primary-action" onClick={() => void open(item.cockpitPublicationId)} disabled={status === "opening"}>Open exact publication</button>
              </li>
            ))}
          </ul>
        )}
        {error && <p role="alert" className="operational-error">{error}</p>}
        <div className="operational-actions">
          <button type="button" onClick={() => void loadIndex()} disabled={status === "loading_index"}>Refresh IDs</button>
          <button type="button" onClick={endSession}>End session</button>
        </div>
      </section>
    </main>
  );
}

export default OperationalGlassShell;
