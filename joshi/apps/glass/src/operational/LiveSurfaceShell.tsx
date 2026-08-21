import { useEffect, useMemo, useState } from "react";
import { KeyRound, LockKeyhole, ShieldCheck } from "lucide-react";

import { GlassApp } from "../App";
import { LoopbackDataSource } from "../data/client";
import { LoopbackOperatorSink } from "../operator/client";
import { LoopbackPresentationSink } from "../presentation/client";
import {
  glassPairingSession,
  MemoryOnlyPairingSession,
  type PairingSessionDescriptor,
} from "../security/pairing";
import type { PendingOperatorCommandQueue } from "../operator/pendingQueue";
import { SameOriginOperationalClient } from "./client";

export type LiveSurfacePairing = {
  exchange(oneTimeCode: string, signal?: AbortSignal): Promise<Omit<PairingSessionDescriptor, "capability">>;
};

/**
 * The paired live-surface cockpit: exactly the ordinary keyboard Glass, reading one immutable
 * scene that `joshi-core live-surface-inspect` derived from a real catalog and is serving.
 *
 * There is no publication index to choose from here and nothing opens automatically. The launch
 * scene is named explicitly at build time by `VITE_JOSHI_LAUNCH_SCENE_ID`, which the launcher
 * prints next to the one-time code; Glass never asks for a "current" or "latest" scene.
 */
export function LiveSurfaceShell({
  session = glassPairingSession,
  client,
  launchSceneId = (import.meta.env.VITE_JOSHI_LAUNCH_SCENE_ID as string | undefined) ?? null,
  pendingOperatorQueue,
}: {
  session?: MemoryOnlyPairingSession;
  client?: LiveSurfacePairing;
  launchSceneId?: string | null;
  // Retention seam for pending marks; the browser default is the IndexedDB-backed queue.
  pendingOperatorQueue?: PendingOperatorCommandQueue;
}) {
  const resolvedClient = useMemo<LiveSurfacePairing>(
    () => client ?? new SameOriginOperationalClient(session),
    [client, session],
  );
  const [sessionVersion, setSessionVersion] = useState(0);
  const [oneTimeCode, setOneTimeCode] = useState("");
  const [status, setStatus] = useState<"unpaired" | "pairing" | "paired">("unpaired");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => session.subscribe(() => setSessionVersion((value) => value + 1)), [session]);
  const paired = session.paired();
  const descriptor = session.descriptor();

  useEffect(() => {
    setStatus(paired ? "paired" : "unpaired");
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

  const runtime = useMemo(() => {
    if (!paired || launchSceneId === null) return null;
    const origin = window.location.origin;
    return {
      source: new LoopbackDataSource(origin, launchSceneId, session),
      operatorSink: new LoopbackOperatorSink(origin, session, true),
      presentationSink: new LoopbackPresentationSink(origin, session, true),
    };
  }, [launchSceneId, paired, session, sessionVersion]);

  const pair = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submitted = oneTimeCode;
    setOneTimeCode("");
    setStatus("pairing");
    setError(null);
    try {
      await resolvedClient.exchange(submitted);
    } catch (cause) {
      session.clear();
      setStatus("unpaired");
      setError(cause instanceof Error ? cause.message : "Pairing failed.");
    }
  };

  if (launchSceneId === null) {
    return (
      <main className="operational-gate">
        <section className="operational-card" aria-labelledby="live-surface-title">
          <div className="operational-icon" aria-hidden="true"><LockKeyhole /></div>
          <p className="eyebrow">Local live surface</p>
          <h1 id="live-surface-title">No launch scene was named</h1>
          <p>
            This build has no <code>VITE_JOSHI_LAUNCH_SCENE_ID</code>. Glass will not ask the core
            for a &ldquo;current&rdquo; scene, so nothing is shown. Start
            <code> joshi-core live-surface-inspect</code> and use the scene ID it prints.
          </p>
        </section>
      </main>
    );
  }

  if (!paired || !descriptor || !runtime) {
    return (
      <main className="operational-gate">
        <section className="operational-card" aria-labelledby="live-surface-title">
          <div className="operational-icon" aria-hidden="true"><LockKeyhole /></div>
          <p className="eyebrow">Local live surface</p>
          <h1 id="live-surface-title">Pair this Glass session</h1>
          <p id="live-surface-help">
            Enter the one-time code printed by <code>joshi-core live-surface-inspect</code>. It is
            consumed once. The capability stays in this page&rsquo;s memory and disappears on reload.
          </p>
          <form onSubmit={(event) => void pair(event)} className="pairing-form">
            <label htmlFor="live-surface-code">One-time pairing code</label>
            <input
              id="live-surface-code"
              name="live-surface-code"
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
              aria-describedby="live-surface-help"
            />
            <button type="submit" className="primary-action" disabled={status === "pairing"}>
              <KeyRound aria-hidden="true" /> {status === "pairing" ? "Pairing…" : "Pair locally"}
            </button>
          </form>
          <p className="safety-ceiling">
            <ShieldCheck aria-hidden="true" /> Read, record, and replay only. No signer, wallet,
            transaction builder, or trading authority exists here.
          </p>
          {error && <p role="alert" className="operational-error">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <div className="operational-session">
      <nav className="operational-session-bar" aria-label="Live surface session">
        <span><ShieldCheck aria-hidden="true" /> Evidence-only session · expires {descriptor.expiresAt}</span>
        <span>Scene {launchSceneId}</span>
        <button type="button" onClick={() => session.clear()}>End session</button>
      </nav>
      <GlassApp
        key={launchSceneId}
        dataSource={runtime.source}
        operatorSink={runtime.operatorSink}
        presentationSink={runtime.presentationSink}
        launchMode="witnessed"
        {...(pendingOperatorQueue ? { pendingOperatorQueue } : {})}
      />
    </div>
  );
}

export default LiveSurfaceShell;
