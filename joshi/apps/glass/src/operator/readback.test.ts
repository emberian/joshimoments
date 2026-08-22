import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryOnlyPairingSession } from "../security/pairing";
import {
  LoopbackOperatorReader,
  MAX_OPERATOR_READBACK_BYTES,
  OfflineFixtureOperatorReader,
} from "./readback";

const SCENE_ID = "scene-live-readback-test";
const WORDS = "SOLVE likely rips 0-60%; DREGG probably stays 300-500K.";

function readbackBody(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    contract: "joshi.core.operator_command_readback",
    schemaVersion: 1,
    authority: "read_only_no_execution",
    sceneId: SCENE_ID,
    sceneRetention: "durable",
    commands: [{
      commandId: "command-journal-entry-1",
      commitSeq: "7",
      scene: { sceneId: SCENE_ID, viewDigest: `sha256:${"a".repeat(64)}` },
      clientSessionId: "session-journal-1",
      clientCommandSeq: "2",
      idempotencyKey: "retry-journal-1",
      commandKind: "record_focus",
      subject: { kind: "scene", key: SCENE_ID },
      issuedAt: "2026-08-22T04:05:06.000000Z",
      receivedAt: "2026-08-22T04:05:07.000000Z",
      clientClockId: "clock-journal-1",
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
      payload: {
        context: {
          uiLabel: "Journal entry",
          uiLabelVersion: "1",
          confidencePpm: null,
          urgency: null,
          whyNow: null,
          note: WORDS,
        },
        dwellMilliseconds: null,
      },
    }],
    ...overrides,
  });
}

function pairedSession(): MemoryOnlyPairingSession {
  const session = new MemoryOnlyPairingSession();
  session.pair("a".repeat(64));
  return session;
}

afterEach(() => vi.unstubAllGlobals());

describe("offline fixture readback", () => {
  it("states that no durable catalog stands behind it instead of answering empty", async () => {
    const answer = await new OfflineFixtureOperatorReader().listSceneCommands();
    expect(answer.state).toBe("no_catalog");
    if (answer.state === "no_catalog") expect(answer.absence).toMatch(/offline fixture/i);
  });
});

describe("loopback operator readback", () => {
  it("reads durable acts back with the payload validated by the frozen write-path schema", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(readbackBody(), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const answer = await new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL(`http://127.0.0.1:8787/api/v1/operator/commands?sceneId=${SCENE_ID}`),
      expect.objectContaining({
        credentials: "omit",
        cache: "no-store",
        headers: expect.objectContaining({ "X-Joshi-Pairing-Token": "a".repeat(64) }),
      }),
    );
    expect(answer.state).toBe("read");
    if (answer.state !== "read") throw new Error("expected a read answer");
    expect(answer.answer.sceneRetention).toBe("durable");
    const command = answer.answer.commands[0];
    expect(command?.commitSeq).toBe("7");
    expect(command?.subject).toEqual({ kind: "scene", key: SCENE_ID });
    if (command?.commandKind !== "record_focus") throw new Error("expected the journal act");
    expect(command.payload.context.note).toBe(WORDS);
  });

  it("attaches no capability while unpaired, matching the snapshot read posture", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(readbackBody(), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await new LoopbackOperatorReader("http://127.0.0.1:8787", new MemoryOnlyPairingSession())
      .listSceneCommands(SCENE_ID);
    const headers = (fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> }).headers;
    expect(headers).not.toHaveProperty("X-Joshi-Pairing-Token");
  });

  it("refuses an answer for a different scene than was requested", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(readbackBody({ sceneId: "scene-other" }), { status: 200 }),
    ));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow(/different scene/i);
  });

  it("refuses a payload the frozen kind schema rejects", async () => {
    const body = readbackBody().replace('"dwellMilliseconds":null', '"dwellMilliseconds":null,"invented":true');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow();
  });

  it("rejects duplicate and dangerous JSON keys before trust", async () => {
    const duplicated = readbackBody().replace('"sceneRetention":"durable"', '"sceneRetention":"durable","sceneRetention":"durable"');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(duplicated, { status: 200 })));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow(/duplicated keys/i);

    const dangerous = readbackBody().replace('"sceneRetention":"durable"', '"__proto__":{"polluted":true},"sceneRetention":"durable"');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(dangerous, { status: 200 })));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow(/forbidden/i);
    expect(Object.prototype).not.toHaveProperty("polluted");
  });

  it("rejects an oversized response before parsing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
      status: 200,
      headers: { "Content-Length": String(MAX_OPERATOR_READBACK_BYTES + 1) },
    })));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow(/response bound/i);
  });

  it("surfaces a refused route status as a thrown failure, never as an empty answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 404 })));
    await expect(new LoopbackOperatorReader("http://127.0.0.1:8787", pairedSession())
      .listSceneCommands(SCENE_ID)).rejects.toThrow(/404/);
  });
});
