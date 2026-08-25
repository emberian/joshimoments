import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Command, Crosshair, Database, Grid2X2, Microscope, Search, ShieldCheck } from "lucide-react";

import { AttentionFeed, type BoardFilter } from "./components/AttentionFeed";
import { boardView } from "./components/boardSemantics";
import { CoinWorkbench } from "./components/CoinWorkbench";
import { CommandPalette, type ShellCommand } from "./components/CommandPalette";
import { EpisodeRail } from "./components/EpisodeRail";
import { HeldCoins, type HeldVenueLookup, type RetainedObservation } from "./components/HeldCoins";
import { JournalRail } from "./components/JournalRail";
import { HypothesisLab } from "./components/HypothesisLab";
import { emptyCaptureContext, OperatorCaptureDialog, OperatorPanel, type CapturePreset, type ChoiceSets } from "./components/OperatorCapture";
import { ReplaySwitch, type LensAvailability } from "./components/ReplaySwitch";
import { ReplayInterviewQueue } from "./components/ReplayInterviewQueue";
import { SceneInspector } from "./components/SceneInspector";
import { SourcePanel } from "./components/SourcePanel";
import type { Candidate, GlassSnapshotV1, ReplayMode } from "./contract/v1";
import { candidateSymbol } from "./format";
import { configuredDataSource, type GlassDataSource } from "./data/client";
import { configuredOperatorSink, type OperatorCommandSink } from "./operator/client";
import { exactUtcNow } from "./operator/contract";
import { inspectAssertionIntent, pointedAssertionIntent, viewportAssertionIntent } from "./operator/attention";
import { heldSubjectKeys, holdIntent, holdNoteIntent, isHoldCommand } from "./operator/holds";
import { journalEntryIntent } from "./operator/journal";
import { configuredOperatorReader, type OperatorCommandReader } from "./operator/readback";
import { useDurableSceneCommands } from "./operator/useDurableSceneCommands";
import { useOperatorJournal, type OperatorIntent } from "./operator/useOperatorJournal";
import type { PendingOperatorCommandQueue } from "./operator/pendingQueue";
import { configuredPresentationSink, type PresentationSink } from "./presentation/client";
import { explorationBundleFor } from "./presentation/fixtures";
import { defaultPresentationPolicy, presentationPolicies } from "./presentation/policies";
import { usePresentationWitness } from "./presentation/usePresentationWitness";
import { useStableCandidateOrder } from "./sensorium/useStableCandidateOrder";
import { useGlobalShortcuts } from "./useGlobalShortcuts";
import { configuredVenueReadoutSource } from "./venue/client";
import { useVenueReadouts } from "./venue/useVenueReadouts";

export type Density = "comfortable" | "compact";

/**
 * The two lenses on one scene. `hunt` is the racing default of a live session: one dense
 * board of coins, scannable at a glance, with the epistemics collapsed to chips. `inspect`
 * is the evidence workbench this cockpit grew up as: the full prose, provenance, journal,
 * and rails. Both read the exact same immutable snapshot and share every piece of state —
 * selection, holds, the journal, and the scene's attention sets — so switching costs one
 * gesture and loses nothing.
 */
export type GlassSurface = "hunt" | "inspect";

function nextMode(mode: ReplayMode): ReplayMode {
  if (mode === "knowledge_cutoff") return "witnessed";
  if (mode === "witnessed") return "retrospective";
  return "knowledge_cutoff";
}

export function GlassApp({
  dataSource,
  operatorSink,
  operatorReader,
  presentationSink,
  launchMode = "witnessed",
  requireOperationalWitness = false,
  presentationIdentity = null,
  onPresentationBinding,
  prospectiveProtocol = false,
  pendingOperatorQueue,
  venueReadout,
  newerScene = null,
  unavailableLenses,
  initialSurface = "inspect",
}: {
  dataSource?: GlassDataSource;
  operatorSink?: OperatorCommandSink;
  /** Read-back for durable operator acts; defaults to the configured loopback/fixture reader. */
  operatorReader?: OperatorCommandReader;
  presentationSink?: PresentationSink;
  launchMode?: ReplayMode;
  requireOperationalWitness?: boolean;
  presentationIdentity?: { presentationId: string; assignmentId: string } | null;
  onPresentationBinding?: (binding: { presentationId: string; presentationDigest: string; assignmentId: string } | null) => void;
  prospectiveProtocol?: boolean;
  pendingOperatorQueue?: PendingOperatorCommandQueue;
  /**
   * The venue-and-clip answer for a held coin, when a test wants to state it directly.
   *
   * Unset in a real session, where it is built from the local core's `venue-readouts` route below.
   * `joshi-market-math` and `joshi-liquidity` remain the only things allowed to produce those
   * numbers; this cockpit renders what the core sends and computes nothing.
   */
  venueReadout?: HeldVenueLookup;
  /**
   * A newer immutable scene the shell learned about from the scene feed, with the act that
   * rebinds this cockpit to it. On the hunt board it renders as the loud advance pill —
   * while she is scanning, "newer scenes exist" decides whether the board is still worth
   * scanning — and it is always a command-palette action. What never changes: no new
   * single-letter key (six of the eight existing ones already collide with screen-reader
   * quick-nav), no focus theft, and the current scene never changes without this explicit
   * act. `newerCount` is how many listed scenes are strictly newer than the bound one, or
   * null when the feed no longer lists the bound scene and the count is not knowable.
   */
  newerScene?: { sceneId: string; derivedAt: string; newerCount?: number | null; advance(): void } | null;
  /**
   * Replay lenses this shell's scenes structurally cannot serve, with the one reason why.
   *
   * A live scene exists only as witnessed — separate as-known and retrospective reconstructions
   * do not exist for it — so those lenses render disabled with the reason, the R key skips them,
   * and no request that can only 409 is ever manufactured. The core's mode_mismatch answer stays
   * the backstop, never the UX.
   */
  unavailableLenses?: LensAvailability;
  /** Which lens a session opens into. The live shell launches into `hunt`; fixtures inspect. */
  initialSurface?: GlassSurface;
}) {
  const [snapshot, setSnapshot] = useState<GlassSnapshotV1 | null>(null);
  const [surface, setSurface] = useState<GlassSurface>(initialSurface);
  const [pendingMode, setPendingMode] = useState<ReplayMode | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [density, setDensity] = useState<Density>("comfortable");
  const [board, setBoard] = useState<BoardFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("radon");
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [provenanceOpen, setProvenanceOpen] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const [capturePreset, setCapturePreset] = useState<CapturePreset | null>(null);
  const [sceneInspectorOpen, setSceneInspectorOpen] = useState(false);
  /**
   * Candidates the operator could actually see in this scene, in the order they were seen.
   *
   * This is the scene's `viewport` choice set — the selection instrument's pre-registered
   * denominator — and `operator/attention.ts` states exactly what it does and does not claim
   * (definition v2). It grows from the observable events of a primarily visual operator: a
   * row's pixels intersecting the visible scroll rectangle, the feed listbox's active
   * descendant reaching a row while the listbox holds focus (the single-tab-stop successor to
   * per-row focus), the pointer entering a row, an explicit selection gesture, and an evidence
   * act naming a candidate. Virtualizer overscan mounting still never counts: mounted is not
   * presented.
   */
  const [attendedIds, setAttendedIds] = useState<string[]>([]);
  const attendedRef = useRef<Set<string>>(new Set());
  const lastAssertedViewport = useRef<{ sceneId: string; key: string } | null>(null);
  /**
   * Candidates whose row the pointer entered in this scene. Its own honest kind (`pointed`),
   * never blurred into `viewport`, because Ember points DELIBERATELY as an attention marker —
   * the instrument watches where she points, and she points on purpose. Pointer entry also
   * feeds the seen set: a pointed row is a seen row.
   */
  const [pointedIds, setPointedIds] = useState<string[]>([]);
  const pointedRef = useRef<Set<string>>(new Set());
  const lastAssertedPointed = useRef<{ sceneId: string; key: string } | null>(null);
  const lastAssertedInspect = useRef<{ sceneId: string; candidateId: string } | null>(null);
  const [interactedIds, setInteractedIds] = useState<string[]>([]);
  const [heldObservations, setHeldObservations] = useState<Record<string, RetainedObservation>>({});
  const [holdAnnouncement, setHoldAnnouncement] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const commandButtonRef = useRef<HTMLButtonElement>(null);
  const replayAbortRef = useRef<AbortController | null>(null);
  const resolvedDataSource = useMemo(() => dataSource ?? configuredDataSource(), [dataSource]);
  const resolvedOperatorSink = useMemo(() => operatorSink ?? configuredOperatorSink(), [operatorSink]);
  const resolvedOperatorReader = useMemo(() => operatorReader ?? configuredOperatorReader(), [operatorReader]);
  const resolvedPresentationSink = useMemo(() => presentationSink ?? configuredPresentationSink(), [presentationSink]);
  const presentationMaterials = useMemo(() => {
    if (!snapshot) return null;
    const admitted = resolvedDataSource.presentationMaterials?.(snapshot);
    if (admitted) return admitted;
    if (resolvedDataSource.kind === "offline_fixture") {
      return { policy: defaultPresentationPolicy, bundle: explorationBundleFor(snapshot), publication: null };
    }
    return null;
  }, [resolvedDataSource, snapshot]);
  const explorationBundle = presentationMaterials?.bundle ?? null;
  const presentationPolicy = presentationMaterials?.policy ?? defaultPresentationPolicy;
  const availablePolicies = presentationMaterials?.publication ? [presentationPolicy] : presentationPolicies;
  const presentationWitness = usePresentationWitness(resolvedPresentationSink, snapshot, explorationBundle, presentationPolicy, presentationIdentity);
  const presentationCompleteBinding = useMemo(() => {
    if (!presentationMaterials?.publication || !presentationWitness.receipt) return null;
    return {
      presentation: {
        presentationId: presentationWitness.receipt.presentationId,
        presentationDigest: presentationWitness.receipt.presentationDigest,
        assignmentId: presentationWitness.receipt.assignmentId,
      },
      cockpitPublication: presentationMaterials.publication,
    };
  }, [presentationMaterials?.publication, presentationWitness.receipt]);
  const operatorJournal = useOperatorJournal(resolvedOperatorSink, snapshot, presentationCompleteBinding, requireOperationalWitness, pendingOperatorQueue);
  const durableJournal = useDurableSceneCommands(resolvedOperatorReader, snapshot?.view.sceneId ?? null);

  useEffect(() => {
    onPresentationBinding?.(presentationCompleteBinding?.presentation ?? null);
    return () => onPresentationBinding?.(null);
  }, [onPresentationBinding, presentationCompleteBinding?.presentation]);
  const witnessedPresentationDigests = useRef(new Set<string>());

  useEffect(() => {
    const presentationScene = presentationWitness.scene;
    const presentationReceipt = presentationWitness.receipt;
    if (!snapshot || !presentationScene || !presentationReceipt) return;
    if (presentationScene.scene.sceneId !== snapshot.view.sceneId || presentationScene.scene.viewDigest !== snapshot.snapshotDigest) return;
    if (witnessedPresentationDigests.current.has(presentationReceipt.presentationDigest)) return;
    witnessedPresentationDigests.current.add(presentationReceipt.presentationDigest);
    for (const itemId of presentationScene.manifest.plannedRenderItemIds) {
      const item = presentationScene.manifest.items.find((candidate) => candidate.itemId === itemId);
      void presentationWitness.recordEvent({
        eventKind: "visibility_started",
        subject: { kind: item?.itemKind === "overlay" ? "overlay" : "panel", key: itemId },
        payload: { reason: "initial_reveal" },
      });
    }
  }, [presentationWitness.receipt?.presentationDigest, snapshot?.snapshotDigest]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();
    resolvedDataSource
      .loadSnapshot({ mode: launchMode, basisSceneId: null, signal: controller.signal })
      .then(setSnapshot)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Unknown load failure");
      });
    return () => {
      controller.abort();
      replayAbortRef.current?.abort();
    };
  }, [launchMode, resolvedDataSource]);

  const unavailableModes = useMemo(
    () => new Set(unavailableLenses?.modes ?? []),
    [unavailableLenses],
  );

  const requestMode = useCallback((mode: ReplayMode) => {
    if (!snapshot || pendingMode !== null || mode === snapshot.view.mode) return;
    // A lens the scene structurally lacks is never requested: the switch renders it disabled
    // with the reason, so reaching here with one is a programming error, not an operator act.
    if (unavailableModes.has(mode)) return;
    const basisSceneId = snapshot.view.mode === "witnessed"
      ? snapshot.view.sceneId
      : snapshot.view.basisSceneId;
    if (mode !== "witnessed" && basisSceneId === null) {
      setLoadError("Cannot request a recomputed view without an immutable witnessed basis scene.");
      return;
    }

    replayAbortRef.current?.abort();
    const controller = new AbortController();
    replayAbortRef.current = controller;
    setPendingMode(mode);
    setLoadError(null);
    resolvedDataSource
      .loadSnapshot({
        mode,
        basisSceneId: mode === "witnessed" ? null : basisSceneId,
        signal: controller.signal,
      })
      .then((nextSnapshot) => {
        if (!controller.signal.aborted) setSnapshot(nextSnapshot);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Unknown replay load failure");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPendingMode(null);
      });
  }, [pendingMode, resolvedDataSource, snapshot, unavailableModes]);

  const candidates = snapshot?.view.payload.candidates ?? [];
  const stableOrder = useStableCandidateOrder(candidates, snapshot?.view.sceneId ?? "scene-not-loaded");
  /**
   * The current tab's real sort or filter over the frozen display order, with its basis
   * stated (`boardSemantics.ts`). Pure over one immutable scene's accepted order, so within
   * a scene no tab's order can move under her; only her own tab switch or an explicit
   * order acceptance reorders anything.
   */
  const boardLens = useMemo(
    () => boardView(stableOrder.orderedCandidates, board),
    [board, stableOrder.orderedCandidates],
  );
  const visibleCandidates = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (normalized.length === 0) return boardLens.candidates;
    return boardLens.candidates.filter((candidate) => {
      const searchable = `${candidate.mint} ${candidate.id} ${candidate.symbol ?? ""} ${candidate.name ?? ""} ${candidate.attentionReason} ${candidate.socialSummary} ${candidate.tags.join(" ")}`.toLowerCase();
      return searchable.includes(normalized);
    });
  }, [boardLens, query]);

  useEffect(() => {
    // A new scene is a new choice context: what was seen in the previous scene says nothing
    // about what has been seen in this one, even for the same coin at a newer price.
    attendedRef.current = new Set();
    setAttendedIds([]);
    pointedRef.current = new Set();
    setPointedIds([]);
    setInteractedIds([]);
  }, [snapshot?.view.sceneId]);

  const noteAttended = useCallback((candidateId: string) => {
    if (attendedRef.current.has(candidateId)) return;
    attendedRef.current.add(candidateId);
    setAttendedIds((current) => current.includes(candidateId) ? current : [...current, candidateId]);
  }, []);

  /** The visible-rectangle channel: every id the scroll viewport currently presents is seen. */
  const noteScrollViewport = useCallback((candidateIds: string[]) => {
    const fresh = candidateIds.filter((id) => !attendedRef.current.has(id));
    if (fresh.length === 0) return;
    for (const id of fresh) attendedRef.current.add(id);
    setAttendedIds((current) => [...current, ...fresh.filter((id) => !current.includes(id))]);
  }, []);

  /** The pointer channel: feeds `pointed` and the seen set, and never moves selection. */
  const notePointed = useCallback((candidateId: string) => {
    noteAttended(candidateId);
    if (pointedRef.current.has(candidateId)) return;
    pointedRef.current.add(candidateId);
    setPointedIds((current) => current.includes(candidateId) ? current : [...current, candidateId]);
  }, [noteAttended]);

  const selectCandidate = useCallback((candidateId: string) => {
    noteAttended(candidateId);
    setSelectedId(candidateId);
    setInteractedIds((current) => current.includes(candidateId) ? current : [...current, candidateId]);
  }, [noteAttended]);

  /**
   * The active descendant reaching a row is the reading event this cockpit can actually
   * observe: the feed is one tab stop (a listbox), so Tab landing on it, J/K and arrow
   * movement while it holds focus, and screen-reader navigation in focus mode all surface as
   * `aria-activedescendant` announcements and land here — the same claim per-row DOM focus
   * used to carry. It feeds the viewport set and keeps selection in step, so what is being
   * read and what a keystroke acts on stay the same thing. Deliberately not `selectCandidate`:
   * reading reaching a row is not an interaction gesture, and the `interacted` set keeps that
   * narrower meaning.
   */
  const attendCandidate = useCallback((candidateId: string) => {
    noteAttended(candidateId);
    setSelectedId(candidateId);
  }, [noteAttended]);

  useEffect(() => {
    if (visibleCandidates.some((candidate) => candidate.id === selectedId)) return;
    const first = visibleCandidates[0];
    if (first) setSelectedId(first.id);
  }, [selectedId, visibleCandidates]);

  const moveSelection = useCallback((direction: 1 | -1) => {
    if (visibleCandidates.length === 0) return;
    const index = visibleCandidates.findIndex((candidate) => candidate.id === selectedId);
    const nextIndex = index < 0 ? 0 : (index + direction + visibleCandidates.length) % visibleCandidates.length;
    const next = visibleCandidates[nextIndex];
    if (next) {
      selectCandidate(next.id);
      setFocusRequest((value) => value + 1);
    }
  }, [selectCandidate, selectedId, visibleCandidates]);

  /**
   * Record one operator act, then let the act carry its scene's honest attention sets with it.
   *
   * A candidate-named act is what makes a scene durable and scoreable, so it is exactly the
   * moment the selection instrument's denominator matters. Each assertion is a second ordinary
   * evidence command on the same route (`operator/attention.ts` states precisely what each
   * claims and refuses to claim); they cost no keystroke, move no focus, render nothing, and
   * are skipped when their set has not changed. When one cannot be recorded, the scene keeps
   * what it has — `rendered` at worst — and the instrument reports that fallback; absence
   * stays visible, never backfilled. The two assertions fail independently: a refused pointer
   * record must not cost the viewport record, or the act itself.
   */
  const recordCommand = useCallback((intent: OperatorIntent) => {
    const commandId = operatorJournal.record(intent);
    if (snapshot && intent.commandKind !== "record_choice_set" && intent.subject.kind === "candidate") {
      noteAttended(intent.subject.key);
      const inScene = new Set(snapshot.view.payload.candidates.map((candidate) => candidate.id));
      const sceneId = snapshot.view.sceneId;
      const seen = [...attendedRef.current].filter((id) => inScene.has(id)).sort();
      const seenKey = seen.join("\0");
      const lastSeen = lastAssertedViewport.current;
      if (seen.length > 0 && (lastSeen === null || lastSeen.sceneId !== sceneId || lastSeen.key !== seenKey)) {
        try {
          operatorJournal.record(viewportAssertionIntent(sceneId, seen, intent.subject.key));
          lastAssertedViewport.current = { sceneId, key: seenKey };
        } catch {
          // Her act must never fail because its instrumentation could not be recorded. The
          // scene then keeps only its rendered choice set, which the instrument reports as
          // the fallback it is.
        }
      }
      const pointed = [...pointedRef.current].filter((id) => inScene.has(id)).sort();
      const pointedKey = pointed.join("\0");
      const lastPointed = lastAssertedPointed.current;
      if (pointed.length > 0 && (lastPointed === null || lastPointed.sceneId !== sceneId || lastPointed.key !== pointedKey)) {
        try {
          operatorJournal.record(pointedAssertionIntent(sceneId, pointed, intent.subject.key));
          lastAssertedPointed.current = { sceneId, key: pointedKey };
        } catch {
          // Same rule: a scene with no pointer record simply has no pointer record.
        }
      }
    }
    return commandId;
  }, [noteAttended, operatorJournal.record, snapshot]);

  /**
   * Keep the retained copy of every held coin as fresh as the feed actually made it.
   *
   * The copy exists so that a coin the feed later stops carrying still has something true to
   * show. That is only worth anything if it is the last observation this cockpit really saw, so
   * it is refreshed from each served scene and never recomputed from anything else.
   */
  useEffect(() => {
    if (!snapshot) return;
    const served = snapshot.view.payload.candidates;
    setHeldObservations((current) => {
      let changed = false;
      const next = { ...current };
      for (const candidate of served) {
        const existing = next[candidate.id];
        if (!existing) continue;
        next[candidate.id] = { ...existing, candidate };
        changed = true;
      }
      return changed ? next : current;
    });
  }, [snapshot]);

  /**
   * One keystroke, committed immediately.
   *
   * No dialog, no confirmation, no field to fill: the whole defect being fixed is that the coin
   * is gone by the time a form has been answered. The act itself is an ordinary evidence command
   * on the ordinary route, so it is durable the moment the store answers, and it is retained in
   * the local pending cache before that.
   */
  const holdSelected = useCallback(() => {
    // Deliberately no fallback to "the first one". Holding a coin she did not choose is worse
    // than holding none, and it would be indistinguishable to her from having held the right one.
    const candidate = candidates.find((item) => item.id === selectedId);
    if (!snapshot || !candidate) {
      setHoldAnnouncement("Nothing was held: no candidate in this scene is selected.");
      return;
    }
    const label = candidateSymbol(candidate.symbol, candidate.mint);
    try {
      recordCommand(holdIntent(candidate.id));
    } catch (error) {
      setHoldAnnouncement(`${label} was not held: ${error instanceof Error ? error.message : "the mark could not be recorded"}`);
      return;
    }
    setHeldObservations((current) => current[candidate.id]
      ? current
      : { ...current, [candidate.id]: { candidate, sceneId: snapshot.view.sceneId, heldAt: exactUtcNow() } });
    setHoldAnnouncement(`Held ${label}. It is pinned in held coins and will not scroll away.`);
  }, [candidates, recordCommand, selectedId, snapshot]);

  const appendJournalEntry = useCallback((words: string) => {
    if (!snapshot) throw new Error("a journal entry needs a loaded scene to bind to");
    // Throws on blank or oversized words; the composer renders the refusal as its own alert.
    recordCommand(journalEntryIntent(snapshot.view.sceneId, words));
    setHoldAnnouncement("Journal entry appended for this scene.");
  }, [recordCommand, snapshot]);

  const appendHoldNote = useCallback((subjectKey: string, note: string) => {
    recordCommand(holdNoteIntent(subjectKey, note));
    const candidate = candidates.find((item) => item.id === subjectKey) ?? heldObservations[subjectKey]?.candidate;
    setHoldAnnouncement(`Note appended to ${candidate ? candidateSymbol(candidate.symbol, candidate.mint) : subjectKey}.`);
  }, [candidates, heldObservations, recordCommand]);

  const refusedHold = useMemo(
    () => operatorJournal.entries.find((entry) => isHoldCommand(entry.command) && entry.status === "rejected") ?? null,
    [operatorJournal.entries],
  );

  // A held coin's subject key is the identity the feed used; the venue route is addressed by mint.
  // In a live surface those are the same string, but they are not the same *thing*, and resolving
  // one to the other through what was actually served keeps a subject key from being posted to the
  // core as if it were an address.
  const heldMintsBySubject = useMemo(() => {
    const resolved: Record<string, string> = {};
    for (const subjectKey of heldSubjectKeys(operatorJournal.entries)) {
      const candidate = candidates.find((item) => item.id === subjectKey)
        ?? heldObservations[subjectKey]?.candidate;
      if (candidate) resolved[subjectKey] = candidate.mint;
    }
    return resolved;
  }, [candidates, heldObservations, operatorJournal.entries]);
  // Built once and only when this cockpit is not given a lookup directly, so a test that states
  // one never opens a socket.
  const venueSource = useMemo(
    () => (venueReadout ? null : configuredVenueReadoutSource()),
    [venueReadout],
  );
  /**
   * The coin page asks the venue question for the coin actually on it, not only for held
   * coins: focus-in is exactly the moment the fee floor and the break-even clip matter. Still
   * never per feed row — the feed carries hundreds and none of them have been chosen — and
   * `useVenueReadouts` keeps its ask-once-per-mint discipline, so browsing five coins costs
   * five reads of retained bytes, not a poll.
   */
  const inspectedMint = useMemo(() => {
    if (surface !== "inspect") return null;
    return candidates.find((item) => item.id === selectedId)?.mint ?? null;
  }, [candidates, selectedId, surface]);
  const venueMints = useMemo(() => {
    const mints = new Set(Object.values(heldMintsBySubject));
    if (inspectedMint !== null) mints.add(inspectedMint);
    return [...mints].sort();
  }, [heldMintsBySubject, inspectedMint]);
  const measuredVenues = useVenueReadouts(venueSource, venueMints);

  /**
   * The coin page's candidate slice: `GET /scenes/{scene}/candidates/{id}`, served verbatim
   * from the same canonical bytes as the loaded view and verified against its digest. Today
   * the loaded snapshot already carries every rendered candidate, so a verified slice is
   * byte-identical and is deliberately DISCARDED (adopting an equal copy would only churn the
   * chart); the fetch still runs on the coin page because it is the live integrity probe of
   * the slice path — the QA walk watches it answer — and because a future slimmer snapshot
   * (candles served per-slice instead of per-scene) lights up the adopt branch with no shell
   * change. Feature-detected: a core without the route costs nothing and renders nothing.
   */
  const [slicedCandidate, setSlicedCandidate] = useState<{ key: string; candidate: Candidate } | null>(null);
  useEffect(() => {
    const sliceLoad = resolvedDataSource.candidateSlice?.bind(resolvedDataSource);
    if (surface !== "inspect" || !snapshot || !sliceLoad) {
      setSlicedCandidate(null);
      return;
    }
    const inScene = snapshot.view.payload.candidates.find((item) => item.id === selectedId);
    if (!inScene) {
      setSlicedCandidate(null);
      return;
    }
    const sceneId = snapshot.view.sceneId;
    const expectedDigest = snapshot.snapshotDigest;
    const key = `${sceneId}/${inScene.id}`;
    const controller = new AbortController();
    sliceLoad(sceneId, inScene.id, controller.signal)
      .then((answer) => {
        if (controller.signal.aborted) return;
        if (answer.state !== "sliced"
          || answer.slice.viewDigest !== expectedDigest
          || answer.slice.candidate.id !== inScene.id
          || JSON.stringify(answer.slice.candidate) === JSON.stringify(inScene)) {
          // Unavailable, render-bound, digest-mismatched, or byte-identical: the loaded
          // snapshot remains the authority and the page keeps its stable candidate identity.
          setSlicedCandidate(null);
          return;
        }
        setSlicedCandidate({ key, candidate: answer.slice.candidate });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSlicedCandidate(null);
      });
    return () => controller.abort();
  }, [resolvedDataSource, selectedId, snapshot, surface]);
  const venueLookup = useMemo<HeldVenueLookup | undefined>(() => {
    if (venueReadout) return venueReadout;
    if (!venueSource) return undefined;
    return (subjectKey: string) => {
      const mint = heldMintsBySubject[subjectKey];
      if (mint === undefined) {
        return {
          state: "absent",
          absence: "This cockpit is holding a mark whose coin the current view does not carry, so "
            + "it has no mint to ask the core about. The mark itself is unaffected.",
        };
      }
      return measuredVenues[mint] ?? null;
    };
  }, [heldMintsBySubject, measuredVenues, venueReadout, venueSource]);

  const toggleDensity = useCallback(() => setDensity((value) => value === "comfortable" ? "compact" : "comfortable"), []);
  /**
   * The automatic focus-in assertion (`operator/attention.ts` states exactly what it claims and
   * why its subject is the scene, never the candidate): entering the coin page on a coin asks
   * the keeper to start tapping its candles while her attention is on it. Recorded by BOTH ways
   * in — the `'` lens switch and the board's click-through — because they are the same focusing
   * event; debounced per (scene, coin) the same way the viewport assertion debounces an
   * unchanged set, and a refused record never costs the lens itself.
   */
  const recordInspectAssertion = useCallback((candidateId: string) => {
    if (!snapshot) return;
    const candidate = candidates.find((item) => item.id === candidateId);
    if (!candidate) return;
    const sceneId = snapshot.view.sceneId;
    const last = lastAssertedInspect.current;
    if (last && last.sceneId === sceneId && last.candidateId === candidate.id) return;
    try {
      recordCommand(inspectAssertionIntent(sceneId, candidate.mint));
      lastAssertedInspect.current = { sceneId, candidateId: candidate.id };
    } catch {
      // Her lens must never fail to open because its instrumentation could not be recorded;
      // the sensing side then simply hears nothing about this inspect.
    }
  }, [candidates, recordCommand, snapshot]);
  /** The `'` lens switch: hunt ↔ inspect, recording the focus-in assertion on the way in. */
  const toggleSurface = useCallback(() => {
    const next = surface === "hunt" ? "inspect" : "hunt";
    setSurface(next);
    if (next === "inspect") recordInspectAssertion(selectedId);
  }, [recordInspectAssertion, selectedId, surface]);
  /**
   * The click-through: one click (or Enter) on a hunt-board row opens that coin's page — the
   * inspect lens, led by the coin itself — the way pump.fun's board opens its coin page. It is
   * the selection gesture plus the same focus-in assertion the `'` switch records, so the
   * attention instrument sees a click-through and a lens flip as the same honest events, and
   * `;` keeps acting on the same coin on both sides of the click.
   */
  const openCandidate = useCallback((candidateId: string) => {
    selectCandidate(candidateId);
    setSurface("inspect");
    recordInspectAssertion(candidateId);
  }, [recordInspectAssertion, selectCandidate]);
  const cycleReplay = useCallback(() => {
    if (!snapshot || pendingMode !== null) return;
    // Cycle over the lenses that exist for this scene. When none besides the current one exist
    // (a live scene is witnessed-only), R deliberately does nothing rather than manufacturing a
    // request that can only fail.
    let candidate = nextMode(snapshot.view.mode);
    for (let step = 0; step < 2 && unavailableModes.has(candidate); step += 1) {
      candidate = nextMode(candidate);
    }
    if (candidate === snapshot.view.mode || unavailableModes.has(candidate)) return;
    requestMode(candidate);
  }, [pendingMode, requestMode, snapshot, unavailableModes]);
  const anotherLensAvailable = useMemo(() => {
    if (!snapshot) return false;
    const modes: ReplayMode[] = ["knowledge_cutoff", "witnessed", "retrospective"];
    return modes.some((mode) => mode !== snapshot.view.mode && !unavailableModes.has(mode));
  }, [snapshot, unavailableModes]);
  // The provenance panel, hypothesis lab, and journal are inspect-lens surfaces. Their
  // commands stay honest from the hunt board by switching the lens first and then landing
  // where they always landed — a command that could only act on an unmounted panel would be
  // a command that can only fail. Under the inspect lens the lens switch is a no-op.
  const toggleProvenance = useCallback(() => {
    setSurface("inspect");
    setProvenanceOpen((value) => !value);
  }, []);
  const openCommands = useCallback(() => setCommandsOpen(true), []);
  const openInspector = useCallback(() => setSceneInspectorOpen(true), []);
  const recordFocus = useCallback(() => setCapturePreset({ type: "focus" }), []);
  const focusSearch = useCallback(() => searchRef.current?.focus(), []);
  const openHypothesisLab = useCallback(() => {
    if (surface === "inspect") {
      document.querySelector<HTMLElement>("#hypothesis-lab")?.focus();
      return;
    }
    setSurface("inspect");
    requestAnimationFrame(() => document.querySelector<HTMLElement>("#hypothesis-lab")?.focus());
  }, [surface]);
  const openJournal = useCallback(() => {
    if (surface === "inspect") {
      document.querySelector<HTMLElement>("#journal")?.focus();
      return;
    }
    setSurface("inspect");
    requestAnimationFrame(() => document.querySelector<HTMLElement>("#journal")?.focus());
  }, [surface]);
  const annotateChart = useCallback((anchor: import("./operator/contract").ChartAnchor) => setCapturePreset({ type: "annotation", anchor }), []);

  useGlobalShortcuts(useMemo(() => ({
    onOpenCommands: openCommands,
    onFocusSearch: focusSearch,
    onMoveSelection: moveSelection,
    onToggleDensity: toggleDensity,
    onCycleReplay: cycleReplay,
    onToggleProvenance: toggleProvenance,
    onOpenInspector: openInspector,
    onRecordFocus: recordFocus,
    onHoldCandidate: holdSelected,
    onOpenHypothesisLab: openHypothesisLab,
    onToggleSurface: toggleSurface,
  }), [cycleReplay, focusSearch, holdSelected, moveSelection, openCommands, openHypothesisLab, openInspector, recordFocus, toggleDensity, toggleProvenance, toggleSurface]));

  const shellCommands: ShellCommand[] = useMemo(() => [
    // First when present, because it is time-sensitive; still an explicit choice, never automatic.
    ...(newerScene ? [{
      id: "advance-scene",
      label: "Advance to the newer scene",
      detail: `Rebind to scene ${newerScene.sceneId}, derived ${newerScene.derivedAt}. Held coins and the journal stay.`,
      run: newerScene.advance,
    }] : []),
    { id: "search", label: "Focus market search", detail: "Filter only this immutable view", shortcut: "/", run: focusSearch },
    {
      id: "surface",
      label: surface === "hunt" ? "Open the evidence workbench" : "Open the hunt board",
      detail: "The other lens on this same scene; selection, holds, and the journal stay",
      shortcut: "'",
      run: toggleSurface,
    },
    // Offered only when another lens actually exists for this scene: a live scene is
    // witnessed-only, and a command that can only fail is not a command.
    ...(anotherLensAvailable ? [{ id: "replay", label: "Load the next replay mode", detail: "Fetch a distinct cutoff, witnessed, or retrospective DTO", shortcut: "R", run: cycleReplay }] : []),
    { id: "density", label: "Toggle density", detail: "Keep large targets; reduce surrounding detail", shortcut: "D", run: toggleDensity },
    { id: "provenance", label: "Toggle provenance", detail: "Inspect field lineage and the full as-of vector", shortcut: "P", run: toggleProvenance },
    { id: "scene-inspector", label: "Inspect current scene", detail: "Review exact digest, choice context, clocks, and receipts", shortcut: "I", run: openInspector },
    { id: "hold", label: "Hold the selected coin", detail: "One keystroke; it stops scrolling away and the mark is retained", shortcut: ";", run: holdSelected },
    { id: "record-focus", label: "Record deliberate focus", detail: "Append an explicit research gesture for the selected coin", shortcut: "F", run: recordFocus },
    { id: "hypothesis-lab", label: "Focus presentation hypothesis lab", detail: "Compare wallet, attention, liquidity, topology, and coupled-field views", shortcut: "H", run: openHypothesisLab },
    // Deliberately no single-letter shortcut: the journal is reached by tab order or from here.
    { id: "journal", label: "Open the journal", detail: "Read what was said over this scene, verbatim, and append an entry", run: openJournal },
    { id: "clear", label: "Clear feed filters", detail: "Return to this snapshot's full served choice set", run: () => { setQuery(""); setBoard("all"); } },
  ], [anotherLensAvailable, cycleReplay, focusSearch, holdSelected, newerScene, openHypothesisLab, openInspector, openJournal, recordFocus, surface, toggleDensity, toggleProvenance, toggleSurface]);

  const closeCommands = useCallback(() => {
    setCommandsOpen(false);
    requestAnimationFrame(() => commandButtonRef.current?.focus());
  }, []);

  // Stable while the same newer scene stands, so the memoized board is not re-rendered by
  // every unrelated shell render.
  const advanceNotice = useMemo(
    () => (newerScene ? { count: newerScene.newerCount ?? null, derivedAt: newerScene.derivedAt, advance: newerScene.advance } : null),
    [newerScene],
  );

  if (!snapshot && loadError) {
    return <main className="load-state"><strong>Glass could not load its read-only snapshot.</strong><p>{loadError}</p></main>;
  }
  if (!snapshot) return <main className="load-state" aria-live="polite">Loading the immutable witnessed glass…</main>;
  if (!presentationMaterials) {
    return <main className="load-state" role="alert"><strong>Publication is incomplete.</strong><p>The selected production publication did not close to exact presentation policy and exploration-bundle bytes. Nothing was revealed.</p></main>;
  }
  const presentationSceneMatches = presentationWitness.scene?.scene.sceneId === snapshot.view.sceneId
    && presentationWitness.scene.scene.viewDigest === snapshot.snapshotDigest;
  if (!presentationSceneMatches || (!presentationWitness.receipt && presentationWitness.status !== "gap")) {
    return <main className="load-state" aria-live="polite"><strong>Snapshot verified.</strong><p>Staging the exact presentation policy, evidence artifacts, ordering, salience, and omissions before revealing the witnessed glass…</p></main>;
  }
  if (requireOperationalWitness && !presentationWitness.receipt) {
    return <main className="load-state" role="alert"><strong>Presentation admission failed.</strong><p>{presentationWitness.error ?? "No durable presentation receipt was returned."} The operational surface remains concealed.</p></main>;
  }

  const selected = candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0];
  if (!selected) return <main className="load-state">This served snapshot contains no candidates.</main>;
  const episode = snapshot.view.payload.episodes.find((item) => item.candidateId === selected.id);
  const mode = snapshot.view.mode;
  // Membership in this scene's choice context requires being in this scene: a coin reached or
  // selected from the held rail after the feed stopped carrying it is real attention, but it is
  // not part of this scene's choice set and asserting it would be refused against these bytes.
  const inThisScene = (id: string) => candidates.some((candidate) => candidate.id === id);
  const interactedHere = interactedIds.filter(inThisScene);
  const choiceSets: ChoiceSets = {
    surfaced: candidates.map((candidate) => candidate.id),
    filtered: visibleCandidates.map((candidate) => candidate.id),
    viewport: attendedIds.filter(inThisScene),
    pointed: pointedIds.filter(inThisScene),
    interacted: interactedHere,
    compared: interactedHere.slice(-3),
  };

  // Rendered by both lenses: a refused hold she must hear about, and the rail that refuses
  // to forget. The held rail is scene-independent state, so it survives the lens switch the
  // same way it survives a scene advance.
  const heldRefusalNotice = refusedHold && (
    <p className="held-refusal" role="alert">
      The local core refused this hold: {refusedHold.error} The coin stays listed below.
    </p>
  );
  const heldRail = (
    <HeldCoins
      entries={operatorJournal.entries}
      candidates={candidates}
      retained={heldObservations}
      {...(venueLookup ? { venueReadout: venueLookup } : {})}
      onSelect={selectCandidate}
      onAppendNote={appendHoldNote}
    />
  );

  return (
    <div className="app" data-density={density}>
      <a className="skip-link" href="#held-coins">Skip to held coins</a>
      {/* The workbench exists only under the inspect lens; a skip link must never point at nothing. */}
      {surface === "inspect" && <a className="skip-link skip-link-second" href="#selected-coin">Skip to selected coin</a>}
      {/*
        Mounted from the first render so a hold announcement is an update to an existing live
        region rather than an insertion, which several screen readers drop. Polite on purpose:
        a hold is confirmation, and interrupting her mid-row while she is racing costs more than
        it gives. A refused hold is separately assertive below, because that one she must hear.
      */}
      <p className="sr-only" role="status">{holdAnnouncement}</p>
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Joshi glass home">
          <span className="brand-mark" aria-hidden="true">J</span>
          <span><strong>Joshi</strong><small>attention glass</small></span>
        </a>
        <label className="market-search">
          <Search aria-hidden="true" />
          <span className="sr-only">Search candidates in this served snapshot</span>
          <input ref={searchRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this immutable choice set…" />
          <kbd>/</kbd>
        </label>
        <div className="header-actions">
          {/*
            The lens switch: cheap in both directions, pointer and keyboard alike. The
            button names the lens it goes TO, and the apostrophe key (next to the hold
            semicolon, equally uncontested by screen-reader quick-nav) does the same.
          */}
          <button type="button" className="header-button" onClick={toggleSurface} aria-label={surface === "hunt" ? "Switch to the inspect lens: the evidence workbench" : "Switch to the hunt lens: the dense candidate board"}>
            {surface === "hunt" ? <Microscope aria-hidden="true" /> : <Crosshair aria-hidden="true" />}
            <span>{surface === "hunt" ? "Inspect" : "Hunt"}</span><kbd>'</kbd>
          </button>
          <button type="button" className="header-button" onClick={toggleDensity} aria-label={`Use ${density === "comfortable" ? "compact" : "comfortable"} density`}>
            <Grid2X2 aria-hidden="true" /><span>{density === "comfortable" ? "Comfortable" : "Compact"}</span><kbd>D</kbd>
          </button>
          <button ref={commandButtonRef} type="button" className="header-button" onClick={openCommands}>
            <Command aria-hidden="true" /><span>Commands</span><kbd>⌘K</kbd>
          </button>
        </div>
      </header>

      <div className="status-strip" id="top">
        <span><ShieldCheck aria-hidden="true" /> Read, record &amp; replay only</span>
        <span><Database aria-hidden="true" /> Contract v{snapshot.schemaVersion} · {snapshot.transport === "offline_fixture" ? "offline fixture" : "loopback core"} · commit {snapshot.view.asOf.catalogCommit}</span>
        <span className="status-help">Move <kbd>J</kbd>/<kbd>K</kbd> · hold <kbd>;</kbd> · lens <kbd>'</kbd> · record focus <kbd>F</kbd> · scene <kbd>I</kbd></span>
      </div>

      {surface === "inspect" ? (
        <section className="replay-bar" aria-label="Replay controls">
          <div>
            <p className="eyebrow">Scene {snapshot.view.sceneId}</p>
            <p className="replay-explanation" aria-live="polite">
              {mode === "witnessed" && `Exact witnessed view · digest verified · rendered ${snapshot.view.asOf.renderedAt}`}
              {mode === "retrospective" && `Separate later reconstruction · basis ${snapshot.view.basisSceneId ?? "missing"}`}
              {mode === "knowledge_cutoff" && `Separate as-known reconstruction · catalog cutoff ${snapshot.view.asOf.catalogCommit}`}
            </p>
            {pendingMode && <p className="replay-pending" role="status">Loading a distinct {pendingMode.replaceAll("_", " ")} snapshot; the current view remains unchanged.</p>}
            {loadError && <p className="replay-error" role="alert">Replay load failed: {loadError}. The prior verified view remains on screen.</p>}
            {presentationWitness.status === "gap" && (presentationWitness.unavailable
              ? (
                /*
                  A core without the witness route is a stated absence of the instrument, not a
                  failure of this scene: said once, quietly, with the sentence on hover — never
                  a red alert that screams forever over an ordinary live session.
                */
                <p
                  className="replay-note"
                  title={`${presentationWitness.error ?? "This core mounts no presentation-witness route."} What is revealed is unwitnessed by construction on this core; nothing about this scene failed.`}
                >
                  Presentation witness: not mounted on this core.
                </p>
              )
              : <p className="replay-error" role="alert">Presentation not witnessed: {presentationWitness.error}. Rich information is visible as an explicit presentation-coverage gap.</p>)}
          </div>
          <ReplaySwitch
            value={mode}
            onChange={requestMode}
            pending={pendingMode}
            {...(unavailableLenses ? { unavailable: unavailableLenses } : {})}
          />
        </section>
      ) : (
        /*
          Hunt keeps the scene's honesty to one line: which immutable scene, which lens,
          and — only when true — a load problem or the presentation-coverage gap, each
          compressed to a short flagged phrase with the full sentence on hover. The replay
          switch lives in the inspect lens; the R key and palette still work from here, and
          the same one-line strip states the result.
        */
        <section className="hunt-strip" aria-label="Scene status">
          <span className="eyebrow">Scene {snapshot.view.sceneId}</span>
          <span className="hunt-mode">
            {mode === "witnessed" && `witnessed · rendered ${snapshot.view.asOf.renderedAt.slice(11, 19)}Z`}
            {mode === "retrospective" && `later reconstruction · basis ${snapshot.view.basisSceneId ?? "missing"}`}
            {mode === "knowledge_cutoff" && `as-known reconstruction · cutoff commit ${snapshot.view.asOf.catalogCommit}`}
          </span>
          {pendingMode && <span className="replay-pending" role="status">loading a distinct {pendingMode.replaceAll("_", " ")} snapshot…</span>}
          {loadError && <span className="replay-error" role="alert">Replay load failed: {loadError}. The prior verified view remains.</span>}
          {presentationWitness.status === "gap" && (presentationWitness.unavailable
            ? (
              <span
                className="hunt-note"
                title={`${presentationWitness.error ?? "This core mounts no presentation-witness route."} A stated absence of the witness instrument, not a failure of this scene.`}
              >
                witness not mounted
              </span>
            )
            : (
              <span
                className="hunt-flag"
                role="alert"
                title={`Presentation not witnessed: ${presentationWitness.error ?? "no receipt"}. What is on screen is an explicit presentation-coverage gap, not a witnessed reveal.`}
              >
                presentation gap — reveal not witnessed
              </span>
            ))}
        </section>
      )}

      {surface === "hunt" ? (
        /*
          The hunt lens: the board IS the page. One dense scannable surface — held coins
          that refuse to scroll away, then every candidate in tight rows — and nothing
          else competing for the glance. The board is the SAME AttentionFeed (one listbox
          tab stop, `aria-activedescendant`, the virtualizer) wired to the SAME three
          attention channels as the inspect column, so the scene's seen/pointed sets have
          one source of truth regardless of which lens she was in, and `;` holds the same
          selected coin either way.
        */
        <main className="glass-layout hunt-layout">
          {heldRefusalNotice}
          {/*
            On the hunt the board is the page, so the held rail compresses to one chip strip:
            the same journal-derived list, the sentences on hover, the full cards one lens
            switch away. Opening a held chip is the same click-through a board row gets.
          */}
          <HeldCoins
            variant="strip"
            entries={operatorJournal.entries}
            candidates={candidates}
            retained={heldObservations}
            onSelect={openCandidate}
            onAppendNote={appendHoldNote}
          />
          <AttentionFeed variant="board" candidates={visibleCandidates} selectedId={selected.id} onSelect={selectCandidate} onOpen={openCandidate} onFocusCandidate={attendCandidate} onScrollViewportChange={noteScrollViewport} onPointerCandidate={notePointed} board={board} onBoardChange={setBoard} density={density} focusRequest={focusRequest}
            orderUpdatePending={stableOrder.pending} pendingNewCount={stableOrder.pendingNewCount} onAcceptOrderUpdate={stableOrder.acceptPendingOrder}
            boardBasis={boardLens.basis}
            advanceNotice={advanceNotice} />
        </main>
      ) : (
      <main className="glass-layout">
        {heldRefusalNotice}
        {heldRail}
        <AttentionFeed candidates={visibleCandidates} selectedId={selected.id} onSelect={selectCandidate} onFocusCandidate={attendCandidate} onScrollViewportChange={noteScrollViewport} onPointerCandidate={notePointed} board={board} onBoardChange={setBoard} density={density} focusRequest={focusRequest}
          orderUpdatePending={stableOrder.pending} pendingNewCount={stableOrder.pendingNewCount} onAcceptOrderUpdate={stableOrder.acceptPendingOrder}
          boardBasis={boardLens.basis} />
        <div id="selected-coin" tabIndex={-1}>
          <CoinWorkbench
            candidate={slicedCandidate !== null && slicedCandidate.key === `${snapshot.view.sceneId}/${selected.id}`
              ? slicedCandidate.candidate
              : selected}
            episode={episode}
            socialEvents={snapshot.view.payload.socialEvents}
            onAnnotate={annotateChart}
            onHold={holdSelected}
            onOpenJournal={openJournal}
            held={heldMintsBySubject[selected.id] !== undefined}
            venueAnswer={venueReadout
              ? venueReadout(selected.id)
              : venueSource
                ? measuredVenues[selected.mint] ?? null
                : null}
          />
          {explorationBundle && <HypothesisLab key={explorationBundle.bundleId}
            bundle={explorationBundle}
            policies={availablePolicies}
            initialPolicy={presentationPolicy}
            presentationReceipt={presentationWitness.receipt}
            presentationError={presentationWitness.error}
            eventReceipts={presentationWitness.eventReceipts}
            eventGap={presentationWitness.eventGap}
            onRecordEvent={presentationWitness.recordEvent}
            onAdmitPolicy={presentationWitness.admitPolicy}
          />}
        </div>
        <div className="right-rail">
          <OperatorPanel
            candidate={selected}
            episode={episode}
            sceneEntries={operatorJournal.sceneEntries}
            compensatedIds={operatorJournal.compensatedIds}
            onCapture={setCapturePreset}
            onRetry={operatorJournal.retry}
            onUndo={(entry) => operatorJournal.compensate(entry, "operator requested semantic undo", emptyCaptureContext("Compensate operator record"))}
            onInspectScene={openInspector}
            nominationQualifies={!prospectiveProtocol}
            pendingReadbackError={operatorJournal.pendingReadbackError}
            currentClientSessionId={operatorJournal.clientSessionId}
          />
          <JournalRail
            sceneId={snapshot.view.sceneId}
            candidates={candidates}
            readback={durableJournal.readback}
            sessionEntries={operatorJournal.entries}
            onReread={durableJournal.reread}
            onAppendEntry={appendJournalEntry}
          />
          <EpisodeRail episodes={snapshot.view.payload.episodes} candidates={candidates} selectedId={selected.id} onFocus={selectCandidate} onRecordGesture={(candidateId, episodeId, gestureLabel) => {
            selectCandidate(candidateId);
            setCapturePreset({ type: "gesture", episodeId, gestureLabel });
          }} />
          <ReplayInterviewQueue episodes={snapshot.view.payload.episodes} candidates={candidates} mode={mode} sceneEntries={operatorJournal.sceneEntries} onCapture={setCapturePreset} />
          <SourcePanel
            sources={snapshot.view.payload.sources}
            candidate={selected}
            expanded={provenanceOpen}
            onExpandedChange={setProvenanceOpen}
            asOf={snapshot.view.asOf}
            snapshotDigest={snapshot.snapshotDigest}
            mode={mode}
          />
        </div>
      </main>
      )}

      <CommandPalette open={commandsOpen} commands={shellCommands} candidates={candidates} onClose={closeCommands} onSelectCandidate={selectCandidate} />
      <OperatorCaptureDialog
        preset={capturePreset}
        candidate={selected}
        sceneId={snapshot.view.sceneId}
        mode={mode}
        choiceSets={choiceSets}
        onClose={() => setCapturePreset(null)}
        onRecord={recordCommand}
      />
      <SceneInspector open={sceneInspectorOpen} onOpenChange={setSceneInspectorOpen} snapshot={snapshot} choiceSets={choiceSets} sceneEntries={operatorJournal.sceneEntries} presentationScene={presentationWitness.scene} presentationReceipt={presentationWitness.receipt} presentationEventReceipts={presentationWitness.eventReceipts} presentationGap={presentationWitness.error ?? presentationWitness.eventGap} />
    </div>
  );
}

export default GlassApp;
