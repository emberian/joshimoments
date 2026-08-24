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

/** How close to expiry the session line turns into a countdown. */
const EXPIRY_WARNING_MS = 15 * 60_000;

/**
 * The session-health line: one line, and honest BEFORE the lapse, not only after it.
 *
 * The pairing descriptor carries its own `expiresAt`, so this cockpit can know the lapse is
 * coming instead of discovering it as a dead feed. Beyond fifteen minutes the line states
 * the expiry instant and stays still; inside fifteen minutes it counts down and says what
 * to do about it. The visible countdown is deliberately NOT a live region — a per-second
 * announcement would be hostile — so a separate always-mounted status region announces the
 * threshold once, when crossing into the final fifteen minutes.
 */
function SessionExpiryNote({ expiresAt }: { expiresAt: string }) {
  const [now, setNow] = useState(() => Date.now());
  const remaining = Date.parse(expiresAt) - now;
  const counting = remaining <= EXPIRY_WARNING_MS;

  useEffect(() => {
    if (remaining <= 0) return;
    // Tick each second inside the countdown; otherwise sleep until the countdown starts.
    const delay = counting ? 1_000 : Math.min(remaining - EXPIRY_WARNING_MS, 2_147_483_647);
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(delay, 250));
    return () => window.clearTimeout(timer);
  }, [counting, remaining]);

  const wholeSeconds = Math.max(0, Math.floor(remaining / 1000));
  const minutes = Math.floor(wholeSeconds / 60);
  const seconds = wholeSeconds % 60;
  return (
    <span className={counting ? "session-expiry-countdown" : undefined}>
      <ShieldCheck aria-hidden="true" />
      {counting
        ? `Session expires in ${minutes}m ${seconds}s — re-pair with a fresh code before it lapses`
        : `Evidence-only session · expires ${expiresAt}`}
      <span className="sr-only" role="status">
        {counting
          ? "The pairing session expires in under fifteen minutes. Re-pair with a fresh one-time code before it lapses."
          : ""}
      </span>
    </span>
  );
}

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
 * no focus theft, no swap) and offered as the hunt board's advance pill, a session-bar button,
 * and a command-palette action; the cockpit rebinds only when the operator runs one of those,
 * and holds and the journal carry across because the app is not remounted — only its data source
 * changes, exactly the machinery replay-mode selection already uses.
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
  /**
   * Whether the pairing gate is showing because a previously live session LAPSED, as opposed
   * to never having been paired or the operator ending it herself. A lapsed session must say
   * "session expired — re-pair", with what to do about it, instead of degrading into scene-feed
   * error noise: once the capability is gone every route stops answering, and "unreachable"
   * would be the wrong diagnosis of a known, dated fact.
   */
  const [expiredLapse, setExpiredLapse] = useState(false);
  const wasPairedRef = useRef(false);
  const lastExpiryRef = useRef<string | null>(null);

  useEffect(() => session.subscribe(() => setSessionVersion((value) => value + 1)), [session]);
  const paired = session.paired();
  const descriptor = session.descriptor();

  useEffect(() => {
    setStatus(paired ? "paired" : "unpaired");
  }, [paired, sessionVersion]);

  useEffect(() => {
    if (descriptor) lastExpiryRef.current = descriptor.expiresAt;
  }, [descriptor?.expiresAt]); // eslint-disable-line react-hooks/exhaustive-deps

  // Decide WHY the session ended by the clock, at the paired -> unpaired transition: the
  // expiry timer, a poll-time self-clear, and a sleep/wake lapse all land here identically.
  // An operator "End session" click clears a descriptor whose expiry is still ahead, so it
  // stays an ordinary re-pair gate.
  useEffect(() => {
    if (paired) {
      wasPairedRef.current = true;
      setExpiredLapse(false);
      return;
    }
    if (!wasPairedRef.current) return;
    wasPairedRef.current = false;
    const lastExpiry = lastExpiryRef.current;
    if (lastExpiry !== null && Date.parse(lastExpiry) <= Date.now()) setExpiredLapse(true);
  }, [paired]);

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
  // How many listed scenes are strictly newer than the bound one (the feed is newest-first,
  // so that is the bound scene's index). When the feed no longer lists the bound scene the
  // count is not knowable and is not claimed: null renders as "newer scenes exist".
  const boundSceneIndex = boundSceneId === null
    ? -1
    : (sceneFeed.feed?.scenes.findIndex((scene) => scene.sceneId === boundSceneId) ?? -1);
  const newerCount = newerScene === null ? null : boundSceneIndex > 0 ? boundSceneIndex : null;

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
        + "The advance button at the top of the board, in the session bar, or in the "
        + "command palette (Cmd+K or Ctrl+K) rebinds to it. Held coins and the journal stay.",
    );
  }, [newerScene]);

  const newerSceneForApp = useMemo(
    () => (newerScene ? { sceneId: newerScene.sceneId, derivedAt: newerScene.derivedAt, newerCount, advance } : null),
    [advance, newerCount, newerScene],
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
          <h1 id="live-surface-title">{expiredLapse ? "Session expired — pair again" : "Pair this Glass session"}</h1>
          {expiredLapse && (
            <p role="alert" className="operational-error">
              This session&rsquo;s pairing capability reached its stated expiry and was discarded, so
              the core no longer answers it. Nothing recorded is lost: every committed act is
              durable in the store. Run <code>joshi-core live-surface-inspect</code> again and
              pair with the fresh one-time code it prints.
            </p>
          )}
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
        <SessionExpiryNote expiresAt={descriptor.expiresAt} />
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
        // A live session opens hunting: the dense board is the default lens, and the
        // evidence workbench stays one gesture away (the apostrophe key, the header
        // button, or the palette).
        initialSurface="hunt"
        newerScene={newerSceneForApp}
        // A live scene exists only as witnessed. The as-known and retrospective lenses are
        // structurally unavailable — separate reconstructions do not exist for it — so they
        // render disabled with that reason instead of as clickable controls that can only fail
        // into the core's 409 mode_mismatch backstop.
        unavailableLenses={{
          modes: ["knowledge_cutoff", "retrospective"],
          reason: "A live scene is witnessed-only; separate as-known and retrospective "
            + "reconstructions do not exist for it.",
        }}
        {...(pendingOperatorQueue ? { pendingOperatorQueue } : {})}
      />
    </div>
  );
}

export default LiveSurfaceShell;
