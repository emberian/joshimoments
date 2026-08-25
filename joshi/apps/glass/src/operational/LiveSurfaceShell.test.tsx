import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { digestGlassView, type GlassSnapshotV1, type GlassViewV1 } from "../contract/v1";
import { canonicalOperatorCommand, digestOperatorPayload, digestOperatorCommand, operatorCommandSchema } from "../operator/contract";
import {
  MemoryOnlyPairingSession,
  OPERATIONAL_SESSION_SCOPES,
  canonicalPairingSessionId,
} from "../security/pairing";
import { MemoryPendingOperatorCommandQueue } from "../operator/pendingQueue";
import { LiveSurfaceShell } from "./LiveSurfaceShell";

const SCENE_ID = "scene-live-fbb74550298579109d9d9b96d373a571";
const MINT = "14m1ketwD6ikdjxtYnm3jtxVzPD9wXhnu5wYGMTWpump";
/** How a candidate with no observed ticker renders: the mint's leading characters, never a `$`. */
const MINT_LABEL = /14m1ke…/;

/**
 * The shape a live chain-only cut actually has: a real mint, real clocks, real observation
 * identities, no ticker (null, never a placeholder string), no price, and an empty price
 * series. Nothing here is a market claim.
 */
const liveView: GlassViewV1 = {
  contract: "joshi.glass.view",
  schemaVersion: 1,
  mode: "witnessed",
  sceneId: SCENE_ID,
  basisSceneId: null,
  asOf: {
    catalogCommit: "3",
    sources: [{
      sourceId: "helius.http.solana.v1",
      deliveredThrough: "3",
      cursors: [],
      receivedThrough: "2026-08-19T21:48:41.182000Z",
    }],
    chain: { cluster: "solana", slot: "440345975", finality: "unstated" },
    projections: [],
    renderedAt: "2026-08-19T21:48:41.185131Z",
  },
  payload: {
    sources: [{
      id: "helius.http.solana.v1",
      label: "helius.http.solana.v1",
      status: "degraded",
      lastObservedAt: "2026-08-19T21:48:26.000000Z",
      lastIngestedAt: "2026-08-19T21:48:41.182000Z",
      coverage: "13 retained observations across commits 1 through 3.",
      note: "No assertion layer beneath the retained bytes; no price is claimed.",
    }],
    candidates: [{
      id: MINT,
      mint: MINT,
      symbol: null,
      name: null,
      board: "watch",
      lifecycle: "unknown",
      firstKnownAt: "2026-08-19T21:48:26.000000Z",
      lastObservedAt: "2026-08-19T21:48:26.000000Z",
      rank: "1",
      metrics: {
        priceSol: null,
        marketCapUsd: null,
        change5mBps: null,
        ageSeconds: "15",
        activity: "unknown",
        quoteSizeSol: null,
        executableExitSol: null,
      },
      attentionReason: "Named by 3 retained provider observations at slot 440345975.",
      socialSummary: "No social source was acquired in this cut.",
      tags: ["chain_observed", "no_price_observed", "ticker_unobserved"],
      watched: false,
      episodeId: null,
      evidence: [{
        id: "obs:helius.http.solana.v1:collector-ingest-live-1787176119317-74131:0:3",
        sourceId: "helius.http.solana.v1",
        field: "mint",
        evidenceClass: "observed",
        observedAt: "2026-08-19T21:48:26.000000Z",
        ingestedAt: "2026-08-19T21:48:40.663000Z",
        knownAt: "2026-08-19T21:48:41.183518Z",
        status: "available",
        note: "Named by retained getTransaction bytes; the transaction failed and set no price.",
      }],
      candles: [],
    }],
    episodes: [],
    socialEvents: [],
  },
};

const liveSnapshot: GlassSnapshotV1 = {
  contract: "joshi.glass.snapshot",
  schemaVersion: 1,
  snapshotDigest: digestGlassView(liveView),
  transport: "loopback",
  recordingAuthority: "read_record_replay_only",
  view: liveView,
};

/** An exact-microsecond wire instant for a millisecond clock value. */
function microInstant(unixMs: number): string {
  return new Date(unixMs).toISOString().replace(/Z$/, "000Z");
}

function pairedSession(expiresAt = "2099-08-18T00:00:00.000000Z"): MemoryOnlyPairingSession {
  const session = new MemoryOnlyPairingSession();
  session.establish("jpc1_" + "a".repeat(64), {
    sessionId: canonicalPairingSessionId(window.location.origin, "1", "1"),
    origin: window.location.origin,
    epoch: "1",
    expiresAt,
    scopes: OPERATIONAL_SESSION_SCOPES,
    authority: "read_only_no_execution",
  });
  return session;
}

type Attempt = { url: string; method: string; token: string | null; body: string | null };

type StubOverrides = {
  /** The scene feed document to serve; absent means the route 404s like a single-scene core. */
  sceneFeed?: () => unknown;
  /** Which snapshot to serve for a requested basis scene. */
  snapshotFor?: (basisSceneId: string | null) => GlassSnapshotV1;
};

function stubCore(attempts: Attempt[], overrides: StubOverrides = {}) {
  const fetchStub = vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
    const url = input instanceof URL ? input.toString() : String(input);
    const method = init?.method ?? "GET";
    const headers = new Headers(init?.headers ?? {});
    attempts.push({
      url,
      method,
      token: headers.get("X-Joshi-Pairing-Token"),
      body: typeof init?.body === "string" ? init.body : null,
    });
    if (new URL(url).pathname === "/api/v1/glass/scenes" && overrides.sceneFeed) {
      return new Response(JSON.stringify(overrides.sceneFeed()), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/api/v1/glass/snapshot")) {
      const basis = new URL(url).searchParams.get("basisSceneId");
      const snapshot = overrides.snapshotFor?.(basis) ?? liveSnapshot;
      return new Response(JSON.stringify(snapshot), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/api/v1/operator/commands") && method === "GET") {
      // The journal's readback of a scene no act has yet made durable: an explicit empty
      // answer with its retention stated, exactly as the live core serves it.
      return new Response(JSON.stringify({
        contract: "joshi.core.operator_command_readback",
        schemaVersion: 1,
        authority: "read_only_no_execution",
        sceneId: new URL(url).searchParams.get("sceneId") ?? SCENE_ID,
        sceneRetention: "served_not_yet_durable",
        commands: [],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/operator/commands")) {
      const command = operatorCommandSchema.parse(JSON.parse(String(init?.body)));
      const receipt = {
        contract: "joshi.store.command_receipt",
        schemaVersion: 1,
        catalogId: "joshi-live-surface-overlay",
        catalogSchema: "joshi.sqlite.v24",
        batchId: `operator:${command.commandId}`,
        commandId: command.commandId,
        commandPayloadDigest: digestOperatorPayload(command),
        commandDigest: digestOperatorCommand(command),
        scene: command.scene,
        commitSeq: "7",
        status: "accepted",
      };
      return new Response(JSON.stringify(receipt), {
        status: 202,
        headers: { "content-type": "application/json" },
      });
    }
    // Core mounts no presentation-scene route; the witness must degrade to an explicit gap
    // rather than block the operator from marking what is on screen.
    return new Response("{}", { status: 404, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

async function tabTo(user: ReturnType<typeof userEvent.setup>, name: RegExp): Promise<HTMLElement> {
  const target = screen.getByRole("button", { name });
  for (let step = 0; step < 20 && document.activeElement !== target; step += 1) {
    await user.tab();
  }
  expect(document.activeElement).toBe(target);
  return target;
}

describe("live surface shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("refuses to invent a launch scene when none was named", () => {
    render(<LiveSurfaceShell session={new MemoryOnlyPairingSession()} launchSceneId={null} />);
    expect(screen.getByRole("heading", { name: /no launch scene was named/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/one-time pairing code/i)).not.toBeInTheDocument();
  });

  it("asks for a one-time code before reading anything", () => {
    stubCore([]);
    render(<LiveSurfaceShell session={new MemoryOnlyPairingSession()} launchSceneId={SCENE_ID} />);
    expect(screen.getByLabelText(/one-time pairing code/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pair locally/i })).toBeInTheDocument();
  });

  it("carries a keyboard-only mark on a real mint to the operator route bound to the served scene", async () => {
    const attempts: Attempt[] = [];
    stubCore(attempts);
    const user = userEvent.setup();
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
      />,
    );

    // A live session opens on the hunt board: the mint renders as a dense board row.
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();
    const snapshotAttempt = attempts.find((attempt) => attempt.url.includes("/api/v1/glass/snapshot"));
    expect(snapshotAttempt?.url).toContain(`basisSceneId=${SCENE_ID}`);
    expect(snapshotAttempt?.token).toMatch(/^jpc1_/);
    // One gesture switches to the inspect lens; the evidence workbench remains whole there.
    await user.keyboard("'");
    expect(await screen.findByRole("heading", { name: MINT_LABEL })).toBeInTheDocument();
    // The lazy chart resolves after the feed; an empty series must read as an absence. It says
    // "not attached", not "not observed": a retained candle window that reached no candidate is
    // an absence on this screen without being an absence in the catalog.
    expect(await screen.findByText(/no price series is attached to this coin/i)).toBeInTheDocument();
    expect(screen.getByText(/no bars are knowable in this lens/i)).toBeInTheDocument();

    await user.keyboard("f");
    const submit = await screen.findByRole("button", { name: /append evidence record/i });
    expect(submit).toBeInTheDocument();
    await tabTo(user, /append evidence record/i);
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(attempts.some((attempt) => attempt.url.includes("/api/v1/operator/commands") && attempt.method === "POST")).toBe(true);
    });
    const posts = attempts.filter((attempt) => attempt.url.includes("/api/v1/operator/commands") && attempt.method === "POST");
    const commands = posts.map((attempt) => operatorCommandSchema.parse(JSON.parse(attempt.body ?? "{}")));
    // Entering the inspect lens emitted the automatic hot-scope assertion: scene-subject (so
    // the selection instrument never scores it as a pick), the coin's mint in the payload.
    const inspect = commands.find((entry) => entry.commandKind === "request_hot_scope");
    expect(inspect?.subject).toEqual({ kind: "scene", key: SCENE_ID });
    expect((inspect?.payload as { scope?: { subject?: unknown } }).scope?.subject).toEqual({ kind: "mint", key: MINT });
    const postedIndex = commands.findIndex((entry) => entry.commandKind === "record_focus");
    expect(postedIndex).toBeGreaterThanOrEqual(0);
    const posted = posts[postedIndex];
    const command = commands[postedIndex]!;
    expect(command.scene.sceneId).toBe(SCENE_ID);
    expect(command.scene.viewDigest).toBe(liveSnapshot.snapshotDigest);
    expect(command.subject).toEqual({ kind: "candidate", key: MINT });
    expect(command.commandKind).toBe("record_focus");
    expect(command.effectCeiling).toBe("observe_only");
    expect(posted?.token).toMatch(/^jpc1_/);
    expect(posted?.body).toBe(canonicalOperatorCommand(command));
    expect((await screen.findAllByText(/commit 7/i)).length).toBeGreaterThan(0);
  });

  /**
   * The gesture this cockpit exists for, on the live route.
   *
   * One key. No dialog, no confirm step, no tab to a submit button, and not one pointer event in
   * the whole path -- because the defect being fixed is that the coin is gone by the time any of
   * those have happened. What lands in the store is an ordinary evidence act bound to the exact
   * bytes the snapshot route served.
   */
  it("holds a real mint from one keystroke, bound to the served scene, with no dialog in the way", async () => {
    const attempts: Attempt[] = [];
    stubCore(attempts);
    const user = userEvent.setup();
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
      />,
    );
    // The board is where she is racing, so the gesture is proven from the board itself.
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();

    await user.keyboard(";");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /append evidence record/i })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(attempts.some((attempt) => attempt.url.includes("/api/v1/operator/commands") && attempt.method === "POST")).toBe(true);
    });
    const posted = attempts.find((attempt) => attempt.url.includes("/api/v1/operator/commands") && attempt.method === "POST");
    const command = operatorCommandSchema.parse(JSON.parse(posted?.body ?? "{}"));
    expect(posted?.body).toBe(canonicalOperatorCommand(command));
    expect(posted?.token).toMatch(/^jpc1_/);
    expect(command.commandKind).toBe("record_focus");
    expect(command.subject).toEqual({ kind: "candidate", key: MINT });
    expect(command.scene.sceneId).toBe(SCENE_ID);
    expect(command.scene.viewDigest).toBe(liveSnapshot.snapshotDigest);
    expect(command.authorityClass).toBe("evidence_only");
    expect(command.effectCeiling).toBe("observe_only");
    if (command.commandKind !== "record_focus") throw new Error("a hold is a record_focus act");
    // Exactly the bytes apps/core/src/live_gesture.rs replays and proves across a restart.
    expect(command.payload).toEqual({
      context: {
        uiLabel: "Hold coin",
        uiLabelVersion: "1",
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      dwellMilliseconds: null,
    });

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByRole("heading", { name: MINT_LABEL })).toBeInTheDocument();
    // The hunt strip states the commit at chip scale: the exact sequence, visibly, the moment
    // the store answers — the end-to-end durability fact a hold exists to make.
    expect(await within(rail).findByText(/commit 7/i)).toBeInTheDocument();
    // The strip claims nothing about the venue. The measured venue block lives on the coin
    // page (and the inspect rail); one lens switch shows it stating its non-claims plainly.
    await user.keyboard("'");
    await screen.findByRole("heading", { name: /venue & instruments/i });
    expect(screen.getAllByText(/not yet measured/i).length).toBeGreaterThanOrEqual(4);
  });

  /**
   * The living-window loop, browser side: the feed grows a newer immutable scene, the shell
   * announces it politely (no focus theft, no swap), and the operator advances through the
   * command palette. The scene changes only by that act, and the held rail — journal-derived,
   * scene-independent — carries every held coin across the advance.
   */
  it("announces a newer scene politely and advances only by the operator's act, keeping holds", async () => {
    const SCENE2 = "scene-live-1c66c9adf6bd0a58bb45ea48029b74d5";
    const secondView: GlassViewV1 = {
      ...liveView,
      sceneId: SCENE2,
      asOf: {
        ...liveView.asOf,
        catalogCommit: "4",
        sources: liveView.asOf.sources.map((source) => ({ ...source, deliveredThrough: "4" })),
      },
    };
    const secondSnapshot: GlassSnapshotV1 = {
      ...liveSnapshot,
      snapshotDigest: digestGlassView(secondView),
      view: secondView,
    };
    const feedEntry = (sceneId: string, viewDigest: string, cutoff: string, derivedAt: string) => ({
      sceneId,
      derivedAt,
      cutoffCommitSeq: cutoff,
      subjectCount: "1",
      observationCount: "3",
      viewDigest,
      derivationVersion: "live_surface.v5",
      sceneRetention: "served_not_yet_durable",
      retiredReason: null,
    });
    const feedScenes = [
      feedEntry(SCENE_ID, liveSnapshot.snapshotDigest, "3", "2026-08-22T17:55:00.000000Z"),
    ];
    const attempts: Attempt[] = [];
    stubCore(attempts, {
      sceneFeed: () => ({
        contract: "joshi.core.scene_feed",
        schemaVersion: 1,
        authority: "read_only_no_execution",
        sourceId: "helius.http.solana.v1",
        scenes: [...feedScenes],
        catalog: {
          outcome: "advanced",
          lastContactAt: "2026-08-22T18:03:00.000000Z",
          detail: null,
          basisCommitSeq: feedScenes[0]?.cutoffCommitSeq ?? "3",
        },
      }),
      snapshotFor: (basis) => (basis === SCENE2 ? secondSnapshot : liveSnapshot),
    });
    const user = userEvent.setup();
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        sceneFeedIntervalMs={25}
      />,
    );
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();
    const sessionBar = screen.getByRole("navigation", { name: /live surface session/i });
    expect(within(sessionBar).getByText(`Scene ${SCENE_ID}`)).toBeInTheDocument();

    // Hold first, so the survival of the hold across the advance is observable.
    await user.keyboard(";");
    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByRole("heading", { name: MINT_LABEL })).toBeInTheDocument();

    // The feed grows a newer scene. Nothing on screen swaps; a polite status line appears,
    // and the board grows its loud advance pill with the honest count of newer scenes.
    feedScenes.unshift(
      feedEntry(SCENE2, secondSnapshot.snapshotDigest, "4", "2026-08-22T18:03:00.000000Z"),
    );
    expect(
      await screen.findByText(/a newer scene exists, derived at 18:03 utc/i),
    ).toBeInTheDocument();
    expect(within(sessionBar).getByText(`Scene ${SCENE_ID}`)).toBeInTheDocument();
    const pill = await screen.findByRole("button", { name: /1 newer scene — advance/i });
    // The session bar keeps its own smaller affordance; both run the same explicit act.
    expect(within(sessionBar).getByRole("button", { name: /^advance to the newer scene$/i })).toBeInTheDocument();

    // Advancing is the operator's own act — here, the board's pill.
    await user.click(pill);

    await waitFor(() => {
      expect(within(sessionBar).getByText(`Scene ${SCENE2}`)).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(attempts.some((attempt) => attempt.url.includes(`basisSceneId=${SCENE2}`))).toBe(true);
    });
    // The workbench now renders the new scene's snapshot...
    await waitFor(() => {
      expect(screen.getAllByText(new RegExp(`Scene ${SCENE2}`)).length).toBeGreaterThan(0);
    });
    // ...and the held coin is still held: the rail derives from the journal, not from the scene.
    const railAfter = screen.getByRole("region", { name: /held coins/i });
    expect(within(railAfter).getByRole("heading", { name: MINT_LABEL })).toBeInTheDocument();
    // Once bound to the newest scene, no advance affordance remains to invite tail-chasing.
    expect(within(sessionBar).queryByRole("button", { name: /^advance to the newer scene$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /newer scene.*advance/i })).not.toBeInTheDocument();
  });

  it("offers the advance inside the command palette, with no single-letter shortcut", async () => {
    const SCENE2 = "scene-live-2c66c9adf6bd0a58bb45ea48029b74d5";
    const attempts: Attempt[] = [];
    stubCore(attempts, {
      sceneFeed: () => ({
        contract: "joshi.core.scene_feed",
        schemaVersion: 1,
        authority: "read_only_no_execution",
        sourceId: "helius.http.solana.v1",
        scenes: [{
          sceneId: SCENE2,
          derivedAt: "2026-08-22T18:03:00.000000Z",
          cutoffCommitSeq: "4",
          subjectCount: "1",
          observationCount: "3",
          viewDigest: liveSnapshot.snapshotDigest,
          derivationVersion: "live_surface.v5",
          sceneRetention: "served_not_yet_durable",
          retiredReason: null,
        }],
        catalog: {
          outcome: "advanced",
          lastContactAt: "2026-08-22T18:03:00.000000Z",
          detail: null,
          basisCommitSeq: "4",
        },
      }),
    });
    const user = userEvent.setup();
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        sceneFeedIntervalMs={25}
      />,
    );
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();
    await screen.findByText(/a newer scene exists/i);
    await user.click(screen.getByRole("button", { name: /commands/i }));
    const dialog = await screen.findByRole("dialog");
    const entry = within(dialog).getByRole("button", { name: /advance to the newer scene/i });
    // Deliberately no shortcut on this action: no new single-letter key exists to collide with
    // screen-reader quick-nav, so the palette entry renders no <kbd> hint.
    expect(within(entry).queryByText(/^[a-z;]$/i)).not.toBeInTheDocument();
    expect(entry.querySelector("kbd")).toBeNull();
  });

  /**
   * The advance rule is the core's own: advance on the evidence watermark (`cutoffCommitSeq`),
   * never on a new scene id — a re-derivation of the same evidence mints a new id with no new
   * observation, and a client chasing ids chases its own tail. Retired rows are listed history
   * that no route serves, so they are never an advance target; but a BOUND scene that retires
   * is the one exception, because staying bound to bytes the core will no longer re-serve is
   * worse than moving.
   */
  it("advances on the evidence watermark, never on a rederived id or a retired row", async () => {
    const REDERIVED = "scene-live-3d77dabe07ce1b69cc56fb59130c85e6";
    const entry = (sceneId: string, cutoff: string, retention: string) => ({
      sceneId,
      derivedAt: "2026-08-22T18:03:00.000000Z",
      cutoffCommitSeq: cutoff,
      subjectCount: "1",
      observationCount: "3",
      viewDigest: liveSnapshot.snapshotDigest,
      derivationVersion: retention === "retired" ? null : "live_surface.v5",
      sceneRetention: retention,
      retiredReason: retention === "retired" ? "older derivation; bytes not retained" : null,
    });
    // Newest listed row is retired history; the newest SERVABLE row is a re-derivation of the
    // bound scene's exact evidence (same watermark, different id). Neither is an advance.
    let feedScenes = [
      entry("scene-live-4e88ebcf18df2c7add67fc6a241d96f7", "5", "retired"),
      entry(REDERIVED, "3", "durable"),
      entry(SCENE_ID, "3", "durable"),
    ];
    stubCore([], {
      sceneFeed: () => ({
        contract: "joshi.core.scene_feed",
        schemaVersion: 1,
        authority: "read_only_no_execution",
        sourceId: "helius.http.solana.v1",
        scenes: [...feedScenes],
        catalog: {
          outcome: "unchanged",
          lastContactAt: "2026-08-22T18:03:00.000000Z",
          detail: null,
          basisCommitSeq: "5",
        },
      }),
    });
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        sceneFeedIntervalMs={25}
      />,
    );
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();
    // Let at least one poll land, then assert the quiet: no pill, no announcement.
    await waitFor(() => expect(screen.queryByText(/scene feed unreachable/i)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /advance/i })).not.toBeInTheDocument();

    // The bound scene retires (an upgraded remount): the newest servable scene is offered even
    // at the same watermark, and with the bound row unservable no count is claimed.
    feedScenes = [
      entry(REDERIVED, "3", "durable"),
      entry(SCENE_ID, "3", "retired"),
    ];
    expect(await screen.findByRole("button", { name: /newer scenes exist — advance/i })).toBeInTheDocument();
  });

  /**
   * The live core mounts no presentation-witness route, and that is a structural fact about
   * the deployment, not a failure of the scene on screen: it renders as a quiet stated
   * absence with the sentence on hover, never as the red alert class Ember actually saw. A
   * real append failure over a mounted route keeps the alert.
   */
  it("states an unmounted presentation witness quietly, never as a red alert", async () => {
    stubCore([]);
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
      />,
    );
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();
    const note = await screen.findByText(/witness not mounted/i);
    expect(note).not.toHaveAttribute("role", "alert");
    expect(note).toHaveAttribute("title", expect.stringMatching(/mounts no presentation-witness route/i));
    expect(screen.queryByText(/presentation gap — reveal not witnessed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  /**
   * The lens honesty rule: a live scene exists only as witnessed, so the as-known and
   * retrospective lenses are structurally unavailable — a fact about the scene, presented as
   * one. They render disabled with the reason; they are not clickable controls that fail into
   * a red 409 banner, and the R key never manufactures the request that could only fail.
   */
  it("presents as-known and later as structurally unavailable for a live scene", async () => {
    const attempts: Attempt[] = [];
    stubCore(attempts);
    const user = userEvent.setup();
    render(
      <LiveSurfaceShell
        session={pairedSession()}
        launchSceneId={SCENE_ID}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
      />,
    );
    expect(await screen.findByRole("option", { name: MINT_LABEL })).toBeInTheDocument();

    // R cycles only over lenses that exist. With none, it does nothing — from the hunt board
    // exactly as from the workbench: no request that can only answer 409 is ever sent, and no
    // failure banner appears.
    await user.keyboard("r");
    expect(
      attempts.filter(
        (attempt) =>
          attempt.url.includes("mode=knowledge_cutoff") || attempt.url.includes("mode=retrospective"),
      ),
    ).toHaveLength(0);
    expect(screen.queryByText(/replay load failed/i)).not.toBeInTheDocument();

    // The command palette offers no "next replay mode" act either: a command that can only
    // fail is not a command.
    await user.click(screen.getByRole("button", { name: /commands/i }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).queryByRole("button", { name: /load the next replay mode/i }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    // The replay switch itself lives in the inspect lens, one gesture away, where the
    // unavailable lenses render disabled with the one reason.
    await user.keyboard("'");
    const asKnown = await screen.findByRole("radio", { name: /earlier knowledge cutoff/i });
    const later = screen.getByRole("radio", { name: /retrospective replay/i });
    const witnessed = screen.getByRole("radio", { name: /witnessed replay/i });
    expect(asKnown).toBeDisabled();
    expect(later).toBeDisabled();
    expect(witnessed).toBeChecked();
    expect(witnessed).not.toBeDisabled();
    // The reason renders next to the switch and inside each disabled lens's accessible name:
    // one visible paragraph plus one screen-reader sentence per disabled lens.
    expect(screen.getAllByText(/a live scene is witnessed-only/i)).toHaveLength(3);
    expect(screen.getAllByText(/does not exist for this scene/i)).toHaveLength(2);
  });

  it("keeps the live surface free of axe-detectable violations", async () => {
    stubCore([]);
    const { container } = render(<LiveSurfaceShell session={pairedSession()} launchSceneId={SCENE_ID} />);
    await screen.findByRole("option", { name: MINT_LABEL });
    const results = await axe.run(container, {
      rules: { region: { enabled: false }, "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });

  /**
   * Session health surfaces BEFORE the lapse, not only after it. The pairing descriptor
   * carries its own `expiresAt`, so inside the final fifteen minutes the one session line
   * turns into a countdown that says what to do about it — no new banner, no second line.
   */
  it("counts down the pairing expiry in the session bar before it lapses", async () => {
    stubCore([]);
    render(
      <LiveSurfaceShell
        session={pairedSession(microInstant(Date.now() + 10 * 60_000))}
        launchSceneId={SCENE_ID}
      />,
    );
    await screen.findByRole("option", { name: MINT_LABEL });
    const sessionBar = screen.getByRole("navigation", { name: /live surface session/i });
    expect(
      within(sessionBar).getByText(/session expires in \d+m \d+s — re-pair with a fresh code before it lapses/i),
    ).toBeInTheDocument();
  });

  /**
   * A lapsed session is a known, dated fact, and it must present as one: a single clear
   * "session expired" state with re-pair instructions. It must NOT degrade into feed error
   * noise — once the capability is gone every route stops answering, and "scene feed
   * unreachable" would be the wrong diagnosis of an expiry the descriptor stated in advance.
   */
  it("states a lapsed session as expired with re-pair instructions, not as an unreachable feed", async () => {
    stubCore([]);
    render(
      <LiveSurfaceShell
        session={pairedSession(microInstant(Date.now() + 150))}
        launchSceneId={SCENE_ID}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: /session expired — pair again/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/pair with the fresh one-time code it prints/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/one-time pairing code/i)).toBeInTheDocument();
    expect(screen.queryByText(/scene feed unreachable/i)).not.toBeInTheDocument();
  });
});
