import { render, screen, waitFor } from "@testing-library/react";
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

/**
 * The shape a live chain-only cut actually has: a real mint, real clocks, real observation
 * identities, no ticker, no price, and an empty price series. Nothing here is a market claim.
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
      symbol: "unobserved",
      name: MINT,
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
      tags: ["chain_observed", "no_price_observed"],
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

function pairedSession(): MemoryOnlyPairingSession {
  const session = new MemoryOnlyPairingSession();
  session.establish("jpc1_" + "a".repeat(64), {
    sessionId: canonicalPairingSessionId(window.location.origin, "1", "1"),
    origin: window.location.origin,
    epoch: "1",
    expiresAt: "2099-08-18T00:00:00.000000Z",
    scopes: OPERATIONAL_SESSION_SCOPES,
    authority: "read_only_no_execution",
  });
  return session;
}

type Attempt = { url: string; token: string | null; body: string | null };

function stubCore(attempts: Attempt[]) {
  const fetchStub = vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
    const url = input instanceof URL ? input.toString() : String(input);
    const headers = new Headers(init?.headers ?? {});
    attempts.push({
      url,
      token: headers.get("X-Joshi-Pairing-Token"),
      body: typeof init?.body === "string" ? init.body : null,
    });
    if (url.includes("/api/v1/glass/snapshot")) {
      return new Response(JSON.stringify(liveSnapshot), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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

    expect(await screen.findByRole("heading", { name: new RegExp(MINT, "i") })).toBeInTheDocument();
    const snapshotAttempt = attempts.find((attempt) => attempt.url.includes("/api/v1/glass/snapshot"));
    expect(snapshotAttempt?.url).toContain(`basisSceneId=${SCENE_ID}`);
    expect(snapshotAttempt?.token).toMatch(/^jpc1_/);
    // The lazy chart resolves after the feed; an empty series must read as an absence.
    expect(await screen.findByText(/no price series was observed/i)).toBeInTheDocument();
    expect(screen.getByText(/no bars are knowable in this lens/i)).toBeInTheDocument();

    await user.keyboard("f");
    const submit = await screen.findByRole("button", { name: /append evidence record/i });
    expect(submit).toBeInTheDocument();
    await tabTo(user, /append evidence record/i);
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(attempts.some((attempt) => attempt.url.includes("/api/v1/operator/commands"))).toBe(true);
    });
    const posted = attempts.find((attempt) => attempt.url.includes("/api/v1/operator/commands"));
    const command = operatorCommandSchema.parse(JSON.parse(posted?.body ?? "{}"));
    expect(command.scene.sceneId).toBe(SCENE_ID);
    expect(command.scene.viewDigest).toBe(liveSnapshot.snapshotDigest);
    expect(command.subject).toEqual({ kind: "candidate", key: MINT });
    expect(command.commandKind).toBe("record_focus");
    expect(command.effectCeiling).toBe("observe_only");
    expect(posted?.token).toMatch(/^jpc1_/);
    expect(posted?.body).toBe(canonicalOperatorCommand(command));
    expect(await screen.findByText(/commit 7/i)).toBeInTheDocument();
  });

  it("keeps the live surface free of axe-detectable violations", async () => {
    stubCore([]);
    const { container } = render(<LiveSurfaceShell session={pairedSession()} launchSceneId={SCENE_ID} />);
    await screen.findByRole("heading", { name: new RegExp(MINT, "i") });
    const results = await axe.run(container, {
      rules: { region: { enabled: false }, "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
