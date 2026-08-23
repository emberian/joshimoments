import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { KeyRound, LockKeyhole, ShieldCheck } from "lucide-react";

import { GlassApp } from "../App";
import { LoopbackDataSource } from "../data/client";
import { LoopbackSceneFeedSource } from "../data/sceneFeed";
import { LoopbackOperatorSink } from "../operator/client";
import { LoopbackOperatorReader } from "../operator/readback";
import { LoopbackPresentationSink } from "../presentation/client";
import {
  glassPairingSession,
  MemoryOnlyPairingSession,
  type PairingSessionDescriptor,
} from "../security/pairing";
import type { PendingOperatorCommandQueue } from "../operator/pendingQueue";
import { SameOriginOperationalClient } from "./client";
import { useSceneFeed } from "./useSceneFeed";

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
 *
 * When the core follows a live catalog it also serves a scene *feed*: a list of immutable scenes,
 * newest first. This shell polls it gently. A newer scene is announced politely (a status line —
 * no focus theft, no swap) and offered as a command-palette action plus a session-bar button;
 * the cockpit rebinds only when the operator runs that action, and holds and the journal carry
 * across because the app is not remounted — only its data source changes, exactly the machinery
 * replay-mode selection already uses.
 */
export function LiveSurfaceShell({
  session = glassPairingSession,
  client,
  launchSceneId = (import.meta.env.VITE_JOSHI_LAUNCH_SCENE_ID as string | undefined) ?? null,
  pendingOperatorQueue,
  sceneFeedIntervalMs = 20_000,
}: {
  session?: MemoryOnlyPairingSession;
  client?: LiveSurfacePairing;
  launchSceneId?: string | null;
  // Retention seam for pending marks; the browser default is the IndexedDB-backed queue.
  pendingOperatorQueue?: PendingOperatorCommandQueue;
  /** How often to poll the scene feed for newer immutable scenes. */
  sceneFeedIntervalMs?: number;
}) {
  const resolvedClient = useMemo<LiveSurfacePairing>(
    () => client ?? new SameOriginOperationalClient(session),
    [client, session],
  );
  const [sessionVersion, setSessionVersion] = useState(0);
  const [oneTimeCode, setOneTimeCode] = useState("");
  const [status, setStatus] = useState<"unpaired" | "pairing" | "paired">("unpaired");
  const [error, setError] = useState<string | null>(null);
  // The scene this cockpit is bound to. It starts at the named launch scene and changes ONLY by
  // the operator's own advance act below — never because the feed listed something newer.
  const [boundSceneId, setBoundSceneId] = useState(launchSceneId);
  const [sceneAnnouncement, setSceneAnnouncement] = useState("");
  const announcedSceneRef = useRef<string | null>(null);

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
    if (!paired || boundSceneId === null) return null;
    const origin = window.location.origin;
    return {
      source: new LoopbackDataSource(origin, boundSceneId, session),
      operatorSink: new LoopbackOperatorSink(origin, session, true),
      operatorReader: new LoopbackOperatorReader(origin, session, true),
      presentationSink: new LoopbackPresentationSink(origin, session, true),
    };
  }, [boundSceneId, paired, session, sessionVersion]);

  // The scene feed is a list of immutable facts served by the core. Polling it can only teach
  // this shell that newer scenes exist; the operator chooses whether to advance.
  const feedSource = useMemo(
    () => (paired ? new LoopbackSceneFeedSource(window.location.origin, session) : null),
    [paired, session, sessionVersion], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const sceneFeed = useSceneFeed(feedSource, sceneFeedIntervalMs);
  const newestScene = sceneFeed.feed?.scenes[0] ?? null;
  const newerScene = newestScene !== null && boundSceneId !== null && newestScene.sceneId !== boundSceneId
    ? newestScene
    : null;

  const advance = useCallback(() => {
    if (!newerScene) return;
    setBoundSceneId(newerScene.sceneId);
    setSceneAnnouncement(
      `Advanced to the scene derived at ${newerScene.derivedAt.slice(11, 16)} UTC. `
        + "Held coins and the journal are unchanged; the previous scene remains readable.",
    );
  }, [newerScene]);

  // Announce a newer scene once, politely: an update to an existing status region, no focus
  // change, no swap. Silence again until an even newer scene appears.
  useEffect(() => {
    if (!newerScene || announcedSceneRef.current === newerScene.sceneId) return;
    announcedSceneRef.current = newerScene.sceneId;
    setSceneAnnouncement(
      `A newer scene exists, derived at ${newerScene.derivedAt.slice(11, 16)} UTC. `
        + 'Open commands with Cmd+K or Ctrl+K and choose "Advance to the newer scene". '
        + "Held coins and the journal stay.",
    );
  }, [newerScene]);

  const newerSceneForApp = useMemo(
    () => (newerScene ? { sceneId: newerScene.sceneId, derivedAt: newerScene.derivedAt, advance } : null),
    [advance, newerScene],
  );

  // Feed trouble is stated, never silently blank — and never mistaken for "no newer scene".
  const feedNote = sceneFeed.absent
    ? null
    : sceneFeed.error !== null
      ? "Scene feed unreachable; newer scenes may exist unseen."
      : sceneFeed.feed?.catalog.outcome === "unreachable"
        ? "The core reports its source catalog unreachable; the scenes listed remain served."
        : null;

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
      {/*
        Mounted from the first paired render so a newer-scene notice is an update to an existing
        live region, not an insertion. Polite on purpose: a newer scene is information, and the
        operator's current scene never changes without her own act.
      */}
      <p className="sr-only" role="status">{sceneAnnouncement}</p>
      <nav className="operational-session-bar" aria-label="Live surface session">
        <span><ShieldCheck aria-hidden="true" /> Evidence-only session · expires {descriptor.expiresAt}</span>
        <span>Scene {boundSceneId ?? launchSceneId}</span>
        {feedNote && <span>{feedNote}</span>}
        {newerScene && (
          <button type="button" onClick={advance}>
            Advance to the newer scene
          </button>
        )}
        <button type="button" onClick={() => session.clear()}>End session</button>
      </nav>
      {/*
        The key is the *launch* scene, deliberately stable across advances: advancing swaps the
        data source (the same machinery replay-mode selection uses) while the held rail, the
        session journal, and the pending queue keep their state. Remounting here would forget
        every committed hold, which is exactly the forgetting the hold rail exists to end.
      */}
      <GlassApp
        key={launchSceneId}
        dataSource={runtime.source}
        operatorSink={runtime.operatorSink}
        operatorReader={runtime.operatorReader}
        presentationSink={runtime.presentationSink}
        launchMode="witnessed"
        newerScene={newerSceneForApp}
        {...(pendingOperatorQueue ? { pendingOperatorQueue } : {})}
      />
    </div>
  );
}

export default LiveSurfaceShell;
