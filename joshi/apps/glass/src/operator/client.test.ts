import { afterEach, describe, expect, it, vi } from "vitest";

import { operatorCommandV1Schema, type OperatorCommandV1 } from "./contract";
import { LoopbackOperatorSink, MAX_OPERATOR_RECEIPT_BYTES, OfflineFixtureOperatorSink } from "./client";
import { MemoryOnlyPairingSession } from "../security/pairing";

function pairedSession(): MemoryOnlyPairingSession {
  const session = new MemoryOnlyPairingSession();
  session.pair("a".repeat(64));
  return session;
}

function commandFixture(): OperatorCommandV1 {
  return operatorCommandV1Schema.parse({
    contract: "joshi.operator.command",
    schemaVersion: 1,
    commandId: "command-client-test",
    idempotencyKey: "retry-client-test",
    clientSessionId: "session-client-test",
    clientCommandSeq: "1",
    scene: { sceneId: "scene-client-test", viewDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
    issuedAt: "2026-08-16T18:42:18.123456Z",
    clientClock: { clockId: "clock-client-test", monotonicNs: "91" },
    commandKind: "record_focus",
    payload: {
      context: {
        uiLabel: "Record focus",
        uiLabelVersion: "1",
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      dwellMilliseconds: null,
    },
    subject: { kind: "candidate", key: "radon" },
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("operator append boundary", () => {
  it("returns one commit for an exact idempotent retry and rejects a changed retry body", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const command = commandFixture();
    const accepted = await sink.appendCommand(command);
    const retried = await sink.appendCommand(structuredClone(command));
    expect(accepted.status).toBe("accepted");
    expect(retried.status).toBe("idempotent");
    expect(retried.commitSeq).toBe(accepted.commitSeq);
    expect(retried.commandDigest).toBe(accepted.commandDigest);

    const changed = structuredClone(command);
    if (changed.commandKind !== "record_focus") throw new Error("fixture kind changed");
    changed.payload.context.note = "changed after ambiguous response";
    await expect(sink.appendCommand(changed)).rejects.toThrow(/idempotency conflict/i);
  });

  it("retains byte-identical retry envelopes across an offline reconnect", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const command = commandFixture();
    sink.setOnline(false);
    await expect(sink.appendCommand(command)).rejects.toMatchObject({ retryable: true });
    sink.setOnline(true);
    const receipt = await sink.appendCommand(command);
    expect(receipt.status).toBe("accepted");
    expect(sink.attemptBodies).toHaveLength(2);
    expect(sink.attemptBodies[1]).toBe(sink.attemptBodies[0]);
  });

  it("posts exact evidence-only JSON to loopback without ambient credentials", async () => {
    const command = commandFixture();
    const receipt = await new OfflineFixtureOperatorSink().appendCommand(command);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await new LoopbackOperatorSink("http://127.0.0.1:8787", pairedSession()).appendCommand(command);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://127.0.0.1:8787/api/v1/operator/commands"),
      expect.objectContaining({ method: "POST", credentials: "omit", body: sinkBody(command), headers: expect.objectContaining({ "X-Joshi-Pairing-Token": "a".repeat(64) }) }),
    );
  });

  it("rejects wrong-scene and wrong-digest acknowledgements", async () => {
    const command = commandFixture();
    const receipt = await new OfflineFixtureOperatorSink().appendCommand(command);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ...receipt,
      scene: { ...receipt.scene, sceneId: "scene-other" },
    }), { status: 200 })));
    await expect(new LoopbackOperatorSink("http://localhost:8787", pairedSession()).appendCommand(command)).rejects.toThrow(/scene/i);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ...receipt,
      commandPayloadDigest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    }), { status: 200 })));
    await expect(new LoopbackOperatorSink("http://localhost:8787", pairedSession()).appendCommand(command)).rejects.toThrow(/payload digest/i);
  });

  it("rejects duplicate and dangerous receipt keys before trust", async () => {
    const command = commandFixture();
    const receipt = await new OfflineFixtureOperatorSink().appendCommand(command);
    const duplicate = JSON.stringify(receipt).replace('"status":"accepted"', '"status":"accepted","status":"accepted"');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(duplicate, { status: 200 })));
    await expect(new LoopbackOperatorSink("http://localhost:8787", pairedSession()).appendCommand(command)).rejects.toThrow(/duplicated keys/i);

    const dangerous = JSON.stringify(receipt).replace('"status":"accepted"', '"__proto__":{"polluted":true},"status":"accepted"');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(dangerous, { status: 200 })));
    await expect(new LoopbackOperatorSink("http://localhost:8787", pairedSession()).appendCommand(command)).rejects.toThrow(/forbidden/i);
    expect(Object.prototype).not.toHaveProperty("polluted");
  });

  it("rejects an oversized receipt before parsing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
      status: 200,
      headers: { "Content-Length": String(MAX_OPERATOR_RECEIPT_BYTES + 1) },
    })));
    await expect(new LoopbackOperatorSink("http://localhost:8787", pairedSession()).appendCommand(commandFixture())).rejects.toThrow(/response bound/i);
  });

  it("fails before fetch while unpaired", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(new LoopbackOperatorSink("http://localhost:8787", new MemoryOnlyPairingSession()).appendCommand(commandFixture())).rejects.toThrow(/not paired/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function sinkBody(command: OperatorCommandV1): string {
  return JSON.stringify(operatorCommandV1Schema.parse(command));
}
