import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Command, Database, Grid2X2, Search, ShieldCheck } from "lucide-react";

import { AttentionFeed, type BoardFilter } from "./components/AttentionFeed";
import { CoinWorkbench } from "./components/CoinWorkbench";
import { CommandPalette, type ShellCommand } from "./components/CommandPalette";
import { EpisodeRail } from "./components/EpisodeRail";
import { HeldCoins, type HeldVenueLookup, type RetainedObservation } from "./components/HeldCoins";
import { HypothesisLab } from "./components/HypothesisLab";
import { emptyCaptureContext, OperatorCaptureDialog, OperatorPanel, type CapturePreset, type ChoiceSets } from "./components/OperatorCapture";
import { ReplaySwitch } from "./components/ReplaySwitch";
import { ReplayInterviewQueue } from "./components/ReplayInterviewQueue";
import { SceneInspector } from "./components/SceneInspector";
import { SourcePanel } from "./components/SourcePanel";
import type { GlassSnapshotV1, ReplayMode } from "./contract/v1";
import { candidateSymbol } from "./format";
import { configuredDataSource, type GlassDataSource } from "./data/client";
import { configuredOperatorSink, type OperatorCommandSink } from "./operator/client";
import { exactUtcNow } from "./operator/contract";
import { heldSubjectKeys, holdIntent, holdNoteIntent, isHoldCommand } from "./operator/holds";
import { useOperatorJournal } from "./operator/useOperatorJournal";
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

function nextMode(mode: ReplayMode): ReplayMode {
  if (mode === "knowledge_cutoff") return "witnessed";
  if (mode === "witnessed") return "retrospective";
  return "knowledge_cutoff";
}

export function GlassApp({
  dataSource,
  operatorSink,
  presentationSink,
  launchMode = "witnessed",
  requireOperationalWitness = false,
  presentationIdentity = null,
  onPresentationBinding,
  prospectiveProtocol = false,
  pendingOperatorQueue,
  venueReadout,
}: {
  dataSource?: GlassDataSource;
  operatorSink?: OperatorCommandSink;
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
}) {
  const [snapshot, setSnapshot] = useState<GlassSnapshotV1 | null>(null);
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
  const [viewportIds, setViewportIds] = useState<string[]>([]);
  const [interactedIds, setInteractedIds] = useState<string[]>([]);
  const [heldObservations, setHeldObservations] = useState<Record<string, RetainedObservation>>({});
  const [holdAnnouncement, setHoldAnnouncement] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const commandButtonRef = useRef<HTMLButtonElement>(null);
  const replayAbortRef = useRef<AbortController | null>(null);
  const resolvedDataSource = useMemo(() => dataSource ?? configuredDataSource(), [dataSource]);
  const resolvedOperatorSink = useMemo(() => operatorSink ?? configuredOperatorSink(), [operatorSink]);
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

  const requestMode = useCallback((mode: ReplayMode) => {
    if (!snapshot || pendingMode !== null || mode === snapshot.view.mode) return;
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
  }, [pendingMode, resolvedDataSource, snapshot]);

  const candidates = snapshot?.view.payload.candidates ?? [];
  const stableOrder = useStableCandidateOrder(candidates, snapshot?.view.sceneId ?? "scene-not-loaded");
  const visibleCandidates = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return stableOrder.orderedCandidates
      .filter((candidate) => {
        const matchesBoard = board === "all" || candidate.board === board;
        const searchable = `${candidate.mint} ${candidate.id} ${candidate.symbol ?? ""} ${candidate.name ?? ""} ${candidate.attentionReason} ${candidate.socialSummary} ${candidate.tags.join(" ")}`.toLowerCase();
        return matchesBoard && (normalized.length === 0 || searchable.includes(normalized));
      });
  }, [board, query, stableOrder.orderedCandidates]);

  useEffect(() => {
    setViewportIds([]);
    setInteractedIds([]);
  }, [snapshot?.view.sceneId]);

  const selectCandidate = useCallback((candidateId: string) => {
    setSelectedId(candidateId);
    setInteractedIds((current) => current.includes(candidateId) ? current : [...current, candidateId]);
  }, []);

  const updateViewport = useCallback((candidateIds: string[]) => {
    setViewportIds((current) => current.length === candidateIds.length && current.every((id, index) => id === candidateIds[index])
      ? current
      : candidateIds);
  }, []);

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

  const recordCommand = operatorJournal.record;

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
  const heldMints = useMemo(
    () => [...new Set(Object.values(heldMintsBySubject))].sort(),
    [heldMintsBySubject],
  );
  const measuredVenues = useVenueReadouts(venueSource, heldMints);
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
  const cycleReplay = useCallback(() => {
    if (snapshot && pendingMode === null) requestMode(nextMode(snapshot.view.mode));
  }, [pendingMode, requestMode, snapshot]);
  const toggleProvenance = useCallback(() => setProvenanceOpen((value) => !value), []);
  const openCommands = useCallback(() => setCommandsOpen(true), []);
  const openInspector = useCallback(() => setSceneInspectorOpen(true), []);
  const recordFocus = useCallback(() => setCapturePreset({ type: "focus" }), []);
  const focusSearch = useCallback(() => searchRef.current?.focus(), []);
  const openHypothesisLab = useCallback(() => document.querySelector<HTMLElement>("#hypothesis-lab")?.focus(), []);
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
  }), [cycleReplay, focusSearch, holdSelected, moveSelection, openCommands, openHypothesisLab, openInspector, recordFocus, toggleDensity, toggleProvenance]));

  const shellCommands: ShellCommand[] = useMemo(() => [
    { id: "search", label: "Focus market search", detail: "Filter only this immutable view", shortcut: "/", run: focusSearch },
    { id: "replay", label: "Load the next replay mode", detail: "Fetch a distinct cutoff, witnessed, or retrospective DTO", shortcut: "R", run: cycleReplay },
    { id: "density", label: "Toggle density", detail: "Keep large targets; reduce surrounding detail", shortcut: "D", run: toggleDensity },
    { id: "provenance", label: "Toggle provenance", detail: "Inspect field lineage and the full as-of vector", shortcut: "P", run: toggleProvenance },
    { id: "scene-inspector", label: "Inspect current scene", detail: "Review exact digest, choice context, clocks, and receipts", shortcut: "I", run: openInspector },
    { id: "hold", label: "Hold the selected coin", detail: "One keystroke; it stops scrolling away and the mark is retained", shortcut: ";", run: holdSelected },
    { id: "record-focus", label: "Record deliberate focus", detail: "Append an explicit research gesture for the selected coin", shortcut: "F", run: recordFocus },
    { id: "hypothesis-lab", label: "Focus presentation hypothesis lab", detail: "Compare wallet, attention, liquidity, topology, and coupled-field views", shortcut: "H", run: openHypothesisLab },
    { id: "clear", label: "Clear feed filters", detail: "Return to this snapshot's full served choice set", run: () => { setQuery(""); setBoard("all"); } },
  ], [cycleReplay, focusSearch, holdSelected, openHypothesisLab, openInspector, recordFocus, toggleDensity, toggleProvenance]);

  const closeCommands = useCallback(() => {
    setCommandsOpen(false);
    requestAnimationFrame(() => commandButtonRef.current?.focus());
  }, []);

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
  const choiceSets: ChoiceSets = {
    surfaced: candidates.map((candidate) => candidate.id),
    filtered: visibleCandidates.map((candidate) => candidate.id),
    viewport: viewportIds,
    interacted: interactedIds,
    compared: interactedIds.slice(-3),
  };

  return (
    <div className="app" data-density={density}>
      <a className="skip-link" href="#held-coins">Skip to held coins</a>
      <a className="skip-link skip-link-second" href="#selected-coin">Skip to selected coin</a>
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
        <span className="status-help">Move <kbd>J</kbd>/<kbd>K</kbd> · record focus <kbd>F</kbd> · scene <kbd>I</kbd> · replay <kbd>R</kbd></span>
      </div>

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
          {presentationWitness.status === "gap" && <p className="replay-error" role="alert">Presentation not witnessed: {presentationWitness.error}. Rich information is visible as an explicit presentation-coverage gap.</p>}
        </div>
        <ReplaySwitch value={mode} onChange={requestMode} pending={pendingMode} />
      </section>

      <main className="glass-layout">
        {refusedHold && (
          <p className="held-refusal" role="alert">
            A hold was refused by the local core and is not retained: {refusedHold.error} The coin
            stays listed below so it is not lost, but nothing has committed it.
          </p>
        )}
        <HeldCoins
          entries={operatorJournal.entries}
          candidates={candidates}
          retained={heldObservations}
          {...(venueLookup ? { venueReadout: venueLookup } : {})}
          onSelect={selectCandidate}
          onAppendNote={appendHoldNote}
        />
        <AttentionFeed candidates={visibleCandidates} selectedId={selected.id} onSelect={selectCandidate} onFocusCandidate={setSelectedId} board={board} onBoardChange={setBoard} density={density} focusRequest={focusRequest} onViewportChange={updateViewport}
          orderUpdatePending={stableOrder.pending} pendingNewCount={stableOrder.pendingNewCount} onAcceptOrderUpdate={stableOrder.acceptPendingOrder} />
        <div id="selected-coin" tabIndex={-1}>
          <CoinWorkbench candidate={selected} episode={episode} socialEvents={snapshot.view.payload.socialEvents} onAnnotate={annotateChart} />
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

      <CommandPalette open={commandsOpen} commands={shellCommands} candidates={candidates} onClose={closeCommands} onSelectCandidate={selectCandidate} />
      <OperatorCaptureDialog
        preset={capturePreset}
        candidate={selected}
        mode={mode}
        choiceSets={choiceSets}
        onClose={() => setCapturePreset(null)}
        onRecord={operatorJournal.record}
      />
      <SceneInspector open={sceneInspectorOpen} onOpenChange={setSceneInspectorOpen} snapshot={snapshot} choiceSets={choiceSets} sceneEntries={operatorJournal.sceneEntries} presentationScene={presentationWitness.scene} presentationReceipt={presentationWitness.receipt} presentationEventReceipts={presentationWitness.eventReceipts} presentationGap={presentationWitness.error ?? presentationWitness.eventGap} />
    </div>
  );
}

export default GlassApp;
