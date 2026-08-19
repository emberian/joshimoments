import { useEffect, useMemo, useRef, useState } from "react";
import { KeyRound, LockKeyhole, RotateCcw, ShieldCheck } from "lucide-react";

import {
  glassPairingSession,
  MemoryOnlyPairingSession,
  PairingSessionRejectedError,
} from "../security/pairing";
import {
  buildCockpitV2BrowserPresentationClaim,
  type CockpitV2BrowserPresentationClaim,
  type CockpitV2BrowserPresentationReceipt,
  type CockpitV2Index,
  type CockpitV2IndexEntry,
  type CockpitV2Open,
} from "./cockpitV2";
import {
  SameOriginCockpitV2InspectorClient,
  type CockpitV2InspectorTransport,
} from "./cockpitV2Client";

type PresentationStatus = "idle" | "scope_absent" | "submitting" | "stored" | "failed";

function pageIdentity(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return `browser-page-${[...bytes].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function exactBrowserNow(): string {
  return new Date().toISOString().replace("Z", "000Z");
}

export function CockpitV2InspectorShell({
  session = glassPairingSession,
  client,
  sourceKind = "offline_fixture",
}: {
  session?: MemoryOnlyPairingSession;
  client?: CockpitV2InspectorTransport;
  sourceKind?: "offline_fixture" | "local_store";
}) {
  const resolvedClient = useMemo(() => client ?? new SameOriginCockpitV2InspectorClient(session), [client, session]);
  const [sessionVersion, setSessionVersion] = useState(0);
  const [oneTimeCode, setOneTimeCode] = useState("");
  const [index, setIndex] = useState<CockpitV2Index | null>(null);
  const [opened, setOpened] = useState<CockpitV2Open | null>(null);
  const [presentationOrdinal, setPresentationOrdinal] = useState(0);
  const [presentationStatus, setPresentationStatus] = useState<PresentationStatus>("idle");
  const [presentationReceipt, setPresentationReceipt] = useState<CockpitV2BrowserPresentationReceipt | null>(null);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const [status, setStatus] = useState<"unpaired" | "pairing" | "loading" | "selecting" | "opening" | "open">("unpaired");
  const [error, setError] = useState<string | null>(null);
  const browserPageId = useRef("");
  if (browserPageId.current === "") browserPageId.current = pageIdentity();
  const nextPresentationOrdinal = useRef(0);
  const activePresentationOrdinal = useRef(0);
  const presentationAttempt = useRef<{ ordinal: number; claim: CockpitV2BrowserPresentationClaim } | null>(null);
  const fixtureOnly = sourceKind === "offline_fixture";

  useEffect(() => session.subscribe(() => setSessionVersion((value) => value + 1)), [session]);
  const paired = session.paired();
  const descriptor = session.descriptor();

  useEffect(() => {
    if (paired) return;
    setIndex(null);
    setOpened(null);
    activePresentationOrdinal.current = 0;
    setPresentationStatus("idle");
    setPresentationReceipt(null);
    setPresentationError(null);
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

  const canWritePresentation = descriptor?.scopes.includes("presentation_evidence_write") ?? false;

  const submitPresentation = (
    ordinal: number,
    claim: CockpitV2BrowserPresentationClaim,
  ) => {
    setPresentationStatus("submitting");
    setPresentationError(null);
    void resolvedClient.present(claim).then((receipt) => {
      if (activePresentationOrdinal.current !== ordinal) return;
      setPresentationReceipt(receipt);
      setPresentationStatus("stored");
    }).catch((cause: unknown) => {
      if (activePresentationOrdinal.current !== ordinal) return;
      setPresentationStatus("failed");
      setPresentationError(cause instanceof Error ? cause.message : "Durable browser report was refused.");
    });
  };

  useEffect(() => {
    if (!opened || presentationOrdinal === 0) return;
    if (!canWritePresentation) {
      setPresentationStatus("scope_absent");
      return;
    }
    if (presentationAttempt.current?.ordinal === presentationOrdinal) return;
    try {
      const devicePixelRatioMilli = Math.round(window.devicePixelRatio * 1_000);
      const monotonicNs = BigInt(Math.floor(performance.now() * 1_000_000)).toString();
      const claim = buildCockpitV2BrowserPresentationClaim(opened, {
        clientPresentationId: `browser-presentation-${browserPageId.current}-${presentationOrdinal}`,
        browserPageId: browserPageId.current,
        presentationSeq: String(presentationOrdinal),
        mountedAt: exactBrowserNow(),
        clientClockId: `${browserPageId.current}-performance`,
        monotonicNs,
        viewport: {
          widthCssPx: String(window.innerWidth),
          heightCssPx: String(window.innerHeight),
          devicePixelRatioMilli: String(devicePixelRatioMilli),
        },
        documentVisibility: document.visibilityState === "hidden" ? "hidden" : "visible",
        documentHasFocus: document.hasFocus(),
      });
      presentationAttempt.current = { ordinal: presentationOrdinal, claim };
      submitPresentation(presentationOrdinal, claim);
    } catch (cause) {
      setPresentationStatus("failed");
      setPresentationError(cause instanceof Error ? cause.message : "Browser mount measurement was invalid.");
    }
  }, [canWritePresentation, opened, presentationOrdinal, resolvedClient]);

  const loadIndex = async () => {
    setStatus("loading");
    setError(null);
    try {
      setIndex(await resolvedClient.list());
      setStatus("selecting");
    } catch (cause) {
      if (cause instanceof PairingSessionRejectedError) setStatus("unpaired");
      else setStatus("selecting");
      setError(cause instanceof Error ? cause.message : "Could not load the exact Cockpit V2 index.");
    }
  };

  const pair = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submitted = oneTimeCode;
    setOneTimeCode("");
    setStatus("pairing");
    setError(null);
    try {
      await resolvedClient.exchange(submitted);
      await loadIndex();
    } catch (cause) {
      session.clear();
      setStatus("unpaired");
      setError(cause instanceof Error ? cause.message : "Pairing failed.");
    }
  };

  const open = async (entry: CockpitV2IndexEntry) => {
    setStatus("opening");
    setError(null);
    try {
      const selected = await resolvedClient.open(entry);
      const ordinal = nextPresentationOrdinal.current + 1;
      nextPresentationOrdinal.current = ordinal;
      activePresentationOrdinal.current = ordinal;
      presentationAttempt.current = null;
      setPresentationReceipt(null);
      setPresentationError(null);
      setPresentationStatus("idle");
      setPresentationOrdinal(ordinal);
      setOpened(selected);
      setStatus("open");
    } catch (cause) {
      if (cause instanceof PairingSessionRejectedError) setStatus("unpaired");
      else setStatus("selecting");
      setError(cause instanceof Error ? cause.message : "Could not verify the selected Cockpit V2 publication.");
    }
  };

  const end = () => {
    activePresentationOrdinal.current = 0;
    setOneTimeCode("");
    setError(null);
    session.clear();
  };

  if (!paired || !descriptor) {
    return (
      <main className="operational-gate">
        <section className="operational-card" aria-labelledby="v2-pairing-title">
          <div className="operational-icon" aria-hidden="true"><LockKeyhole /></div>
          <p className="eyebrow">{fixtureOnly ? "Offline G0 inspection" : "Local store inspection"}</p>
          <h1 id="v2-pairing-title">Pair this read-only inspector</h1>
          <p id="v2-pairing-help">Enter the one-time Cockpit-read code printed by the {fixtureOnly ? "explicit local fixture launcher" : "opt-in local Core server"}. The capability remains only in this page’s memory and disappears on reload.</p>
          <form onSubmit={(event) => void pair(event)} className="pairing-form">
            <label htmlFor="v2-pairing-code">One-time pairing code</label>
            <input
              id="v2-pairing-code"
              autoComplete="one-time-code"
              spellCheck={false}
              autoCapitalize="characters"
              required
              minLength={45}
              maxLength={45}
              pattern="JOSHI-(?:[0-9A-HJKMNP-TV-Z]{4}-){7}[0-9A-HJKMNP-TV-Z]{4}"
              value={oneTimeCode}
              onChange={(event) => setOneTimeCode(event.target.value)}
              aria-describedby="v2-pairing-help"
            />
            <button type="submit" className="primary-action" disabled={status === "pairing"}>
              <KeyRound aria-hidden="true" /> {status === "pairing" ? "Pairing…" : "Pair locally"}
            </button>
          </form>
          <p className="safety-ceiling"><ShieldCheck aria-hidden="true" /> {fixtureOnly ? "Offline fixture" : "Local store"} inspection only. A separately scoped browser-report receipt may record an exact mount; no signer, wallet, transaction builder, provider I/O, trading authority, or pixel verification is mounted.</p>
          {error && <p role="alert" className="operational-error">{error}</p>}
        </section>
      </main>
    );
  }

  if (opened) {
    const manifest = opened.publication.manifest;
    const membership = new Map(manifest.memberships.map((entry) => [entry.subject, entry.membership]));
    return (
      <main className="operational-gate operational-selection">
        <section className="operational-card wide" aria-labelledby="v2-open-title">
          <p className="eyebrow">Exact Cockpit V2 · unverified semantic ceiling</p>
          <h1 id="v2-open-title">{opened.publication.publicationId}</h1>
          <p>The browser independently reparsed the strict body and head, recomputed their semantic and exact-byte digests, and closed the selected durable index entry. This is descriptive {fixtureOnly ? "offline-fixture" : "local-store"} evidence, not a recommendation, quote, or live-data qualification.</p>
          {presentationStatus === "submitting" && <p role="status">Recording the exact browser-reported mount…</p>}
          {presentationStatus === "stored" && presentationReceipt && (
            <p role="status" className="safety-ceiling">
              <ShieldCheck aria-hidden="true" /> Durable browser report stored at commit {presentationReceipt.storeCommitSeq}. This is not pixel verification or product qualification.
            </p>
          )}
          {presentationStatus === "scope_absent" && (
            <p className="safety-ceiling">This pairing session has no presentation-evidence scope, so no browser report was sent.</p>
          )}
          {presentationStatus === "failed" && presentationError && (
            <div>
              <p role="alert" className="operational-error">{presentationError}</p>
              <button type="button" onClick={() => {
                const attempt = presentationAttempt.current;
                if (attempt && attempt.ordinal === activePresentationOrdinal.current) {
                  submitPresentation(attempt.ordinal, attempt.claim);
                }
              }}>Retry exact browser report</button>
            </div>
          )}
          <dl className="session-summary">
            <div><dt>Publication commit</dt><dd>{opened.publicationCommitSeq}</dd></div>
            <div><dt>Head commit</dt><dd>{opened.headCommitSeq}</dd></div>
            <div><dt>Knowledge cutoff</dt><dd>{manifest.cutoff.knowledgeAt}</dd></div>
            <div><dt>Catalog cutoff</dt><dd>{manifest.cutoff.commitThrough ?? "absent"}</dd></div>
            <div><dt>Eligible</dt><dd>{manifest.observedUniverse.eligibleCount}</dd></div>
            <div><dt>Facts / gaps</dt><dd>{manifest.sourceFacts.length} / {manifest.gaps.length}</dd></div>
          </dl>
          <h2>Eligible denominator and presentation partition</h2>
          <ul className="publication-list" aria-label="Cockpit V2 eligible subjects">
            {manifest.observedUniverse.eligibleSubjects.map((subject) => (
              <li key={subject}>
                <div>
                  <strong>{subject}</strong>
                  <span>{membership.get(subject)?.replaceAll("_", " ") ?? "missing membership"}</span>
                  <small>{manifest.renderedSubjects.includes(subject) ? "rendered" : `omitted · ${manifest.omissions.find((entry) => entry.subject === subject)?.reason ?? "missing reason"}`}</small>
                </div>
              </li>
            ))}
          </ul>
          <h2>Store-resolved public facts</h2>
          <ul className="publication-list" aria-label="Cockpit V2 source facts">
            {manifest.sourceFacts.map((fact) => (
              <li key={fact.factId}>
                <div>
                  <strong>{fact.subject} · {fact.field}</strong>
                  <span>{fact.surfaceId} · {fact.sourceId} · known {fact.knownAt}</span>
                  <code>{fact.factId}</code>
                  <small>{fact.factDigest}</small>
                </div>
              </li>
            ))}
          </ul>
          <h2>Exact coverage cells</h2>
          <ul className="publication-list" aria-label="Cockpit V2 coverage cells">
            {manifest.coverage.map((cell) => (
              <li key={`${cell.surfaceId}|${cell.sourceId}|${cell.subject}|${cell.field}`}>
                <div>
                  <strong>{cell.subject} · {cell.field} · {cell.state}</strong>
                  <span>{cell.surfaceId} · {cell.sourceId} · {cell.factIds.length} fact reference(s)</span>
                  <small>{cell.coverageDigest}</small>
                </div>
              </li>
            ))}
          </ul>
          <details>
            <summary>Exact identities and digests</summary>
            <dl className="session-summary">
              <div><dt>Source occurrence</dt><dd>{opened.sourceOccurrenceId}</dd></div>
              <div><dt>Publication semantic</dt><dd>{opened.publication.publicationDigest}</dd></div>
              <div><dt>Publication bytes</dt><dd>{opened.publicationBytesDigest}</dd></div>
              <div><dt>Head semantic</dt><dd>{opened.head.headDigest}</dd></div>
              <div><dt>Head bytes</dt><dd>{opened.headBytesDigest}</dd></div>
              <div><dt>Universe</dt><dd>{manifest.observedUniverse.universeDigest}</dd></div>
            </dl>
          </details>
          <div className="operational-actions">
            <button type="button" onClick={() => {
              activePresentationOrdinal.current = 0;
              setOpened(null);
              setPresentationStatus("idle");
              setPresentationReceipt(null);
              setPresentationError(null);
              setStatus("selecting");
            }}><RotateCcw aria-hidden="true" /> Choose publication</button>
            <button type="button" onClick={end}>End session</button>
          </div>
          {error && <p role="alert" className="operational-error">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="operational-gate operational-selection">
      <section className="operational-card wide" aria-labelledby="v2-index-title">
        <p className="eyebrow">Paired · Cockpit read{canWritePresentation ? " + browser-report evidence" : " only"} · {fixtureOnly ? "offline fixture" : "local store"}</p>
        <h1 id="v2-index-title">Choose an exact Cockpit V2 head</h1>
        <p>The list is the complete bounded set rederived by the store. Nothing opens automatically, and no “latest” pointer is inferred.</p>
        <dl className="session-summary">
          <div><dt>Session</dt><dd>{descriptor.sessionId}</dd></div>
          <div><dt>Expires</dt><dd>{descriptor.expiresAt}</dd></div>
          <div><dt>Scope</dt><dd>{descriptor.scopes.join(" · ")}</dd></div>
          <div><dt>Authority</dt><dd>{descriptor.authority.replaceAll("_", " ")}</dd></div>
        </dl>
        {status === "loading" && <p role="status">Loading exact durable heads…</p>}
        {status === "opening" && <p role="status">Reparsing and recomputing the selected body/head…</p>}
        {index === null && <button type="button" className="primary-action" onClick={() => void loadIndex()} disabled={status === "loading"}>Load exact index</button>}
        {index?.items.length === 0 && <p>No headed {fixtureOnly ? "offline-fixture" : "local-store"} publications are available.</p>}
        {index && index.items.length > 0 && (
          <ul className="publication-list" aria-label="Exact Cockpit V2 heads">
            {index.items.map((entry) => (
              <li key={entry.publicationId}>
                <div>
                  <strong>{entry.publicationId}</strong>
                  <span>head commit {entry.headCommitSeq} · {entry.eligibleCount} eligible · {entry.factCount} facts · {entry.gapCount} gaps</span>
                  <code>{entry.sourceOccurrenceId}</code>
                  <small>{entry.publicationDigest}</small>
                </div>
                <button type="button" className="primary-action" onClick={() => void open(entry)} disabled={status === "opening"}>Inspect exact bytes</button>
              </li>
            ))}
          </ul>
        )}
        {error && <p role="alert" className="operational-error">{error}</p>}
        <div className="operational-actions">
          <button type="button" onClick={() => void loadIndex()} disabled={status === "loading"}>Refresh exact IDs</button>
          <button type="button" onClick={end}>End session</button>
        </div>
      </section>
    </main>
  );
}

export default CockpitV2InspectorShell;
