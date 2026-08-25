import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MemoryOnlyPairingSession,
  OPERATIONAL_SESSION_SCOPES,
  canonicalPairingSessionId,
} from "../security/pairing";
import { LoopbackSceneFeedSource, parseSceneFeedV1 } from "./sceneFeed";

const FEED = {
  contract: "joshi.core.scene_feed",
  schemaVersion: 1,
  authority: "read_only_no_execution",
  sourceId: "source.other.fixture",
  scenes: [
    {
      sceneId: "scene-live-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      derivedAt: "2026-08-22T18:00:00.000000Z",
      cutoffCommitSeq: "3",
      subjectCount: "1",
      observationCount: "3",
      viewDigest: `sha256:${"a".repeat(64)}`,
      derivationVersion: "live_surface.v5",
      sceneRetention: "served_not_yet_durable",
      retiredReason: null,
    },
  ],
  catalog: {
    outcome: "advanced",
    lastContactAt: "2026-08-22T18:00:00.000000Z",
    detail: null,
    basisCommitSeq: "3",
  },
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

describe("scene feed client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("parses a well-formed feed and refuses an unknown extra field", () => {
    expect(parseSceneFeedV1(FEED).scenes[0]?.cutoffCommitSeq).toBe("3");
    expect(() => parseSceneFeedV1({ ...FEED, currentSceneId: "nope" })).toThrow();
  });

  /**
   * Regression: the core's `SceneFeedEntryWire` grew `derivationVersion` and `retiredReason`
   * and a third retention state, and this strict schema rejected every live feed — the poll
   * ran forever and never once succeeded, so the shell could only say "unreachable" and no
   * advance pill ever appeared. The cockpit sat on its launch scene like a photograph. This
   * pins the exact wire shape the core serves, including a retired historical row and a null
   * derivation version on a pre-versioning scene.
   */
  it("parses the current core wire: versioned rows, null versions, and retired history", () => {
    const wire = {
      ...FEED,
      scenes: [
        FEED.scenes[0],
        {
          sceneId: "scene-live-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          derivedAt: "2026-08-22T17:00:00.000000Z",
          cutoffCommitSeq: "2",
          subjectCount: "1",
          observationCount: "2",
          viewDigest: `sha256:${"b".repeat(64)}`,
          derivationVersion: null,
          sceneRetention: "retired",
          retiredReason: "derived by an older derivation whose bytes were not retained",
        },
      ],
    };
    const parsed = parseSceneFeedV1(wire);
    expect(parsed.scenes[1]?.sceneRetention).toBe("retired");
    expect(parsed.scenes[1]?.derivationVersion).toBeNull();
    expect(parsed.scenes[0]?.derivationVersion).toBe("live_surface.v5");
  });

  it("carries the pairing capability and returns the parsed feed", async () => {
    let token: string | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
      token = new Headers(init?.headers ?? {}).get("X-Joshi-Pairing-Token");
      expect(new URL(String(input)).pathname).toBe("/api/v1/glass/scenes");
      return new Response(JSON.stringify(FEED), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));
    const source = new LoopbackSceneFeedSource(window.location.origin, pairedSession());
    const loaded = await source.load();
    expect("absent" in loaded).toBe(false);
    if (!("absent" in loaded)) expect(loaded.catalog.outcome).toBe("advanced");
    expect(token).toMatch(/^jpc1_/);
  });

  it("reads a 404 as an absent feed, which is a stated fact and not an error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ contract: "joshi.core.problem", schemaVersion: 1, code: "scene_feed_not_mounted", detail: "" }),
      { status: 404, headers: { "content-type": "application/json" } },
    )));
    const source = new LoopbackSceneFeedSource(window.location.origin, pairedSession());
    expect(await source.load()).toEqual({ absent: true });
  });

  it("refuses duplicate keys before the platform parser can collapse them", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      '{"contract":"joshi.core.scene_feed","contract":"joshi.core.scene_feed"}',
      { status: 200, headers: { "content-type": "application/json" } },
    )));
    const source = new LoopbackSceneFeedSource(window.location.origin, pairedSession());
    await expect(source.load()).rejects.toThrow(/invalid scene feed JSON/);
  });
});
