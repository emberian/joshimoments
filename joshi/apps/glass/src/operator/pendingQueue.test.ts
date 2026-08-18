import { describe, expect, it } from "vitest";

import { operatorCommandV1Schema } from "./contract";
import {
  commandFromPending,
  MAX_PENDING_OPERATOR_COMMANDS,
  MemoryPendingOperatorCommandQueue,
  pendingOperatorCommand,
} from "./pendingQueue";

function command(index: number) {
  return operatorCommandV1Schema.parse({
    contract: "joshi.operator.command",
    schemaVersion: 1,
    commandId: `command-fixture-${index}`,
    idempotencyKey: `retry-fixture-${index}`,
    clientSessionId: "glass-session-fixture",
    clientCommandSeq: String(index + 1),
    scene: { sceneId: "scene-fixture", viewDigest: `sha256:${"a".repeat(64)}` },
    issuedAt: "2026-08-18T04:00:00.000000Z",
    clientClock: { clockId: "clock-fixture", monotonicNs: String((index + 1) * 1000) },
    commandKind: "record_focus",
    subject: { kind: "candidate", key: `candidate-${index}` },
    payload: {
      context: {
        uiLabel: "Immediate notice",
        uiLabelVersion: "1",
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      dwellMilliseconds: null,
    },
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}

describe("bounded pending operator-command transport cache", () => {
  it("retains exact canonical authority bytes and removes them only for the matching durable ACK digest", async () => {
    const queue = new MemoryPendingOperatorCommandQueue();
    const pending = pendingOperatorCommand(command(1));
    await queue.append(pending);
    expect(commandFromPending((await queue.list())[0]!)).toEqual(command(1));
    await expect(queue.acknowledge(pending.commandId, `sha256:${"b".repeat(64)}`)).rejects.toThrow(/ACK digest/i);
    expect(await queue.list()).toHaveLength(1);
    await queue.acknowledge(pending.commandId, pending.commandDigest);
    expect(await queue.list()).toEqual([]);
  });

  it("does not retain pairing capability material and refuses overflow rather than evicting unadmitted commands", async () => {
    const queue = new MemoryPendingOperatorCommandQueue();
    for (let index = 0; index < MAX_PENDING_OPERATOR_COMMANDS; index += 1) {
      await queue.append(pendingOperatorCommand(command(index)));
    }
    expect(await queue.list()).toHaveLength(MAX_PENDING_OPERATOR_COMMANDS);
    await expect(queue.append(pendingOperatorCommand(command(MAX_PENDING_OPERATOR_COMMANDS)))).rejects.toThrow(/count limit/i);
    expect(JSON.stringify(await queue.list())).not.toMatch(/pairing.?token|capability|authorization/i);

    const first = (await queue.list())[0]!;
    await queue.acknowledge(first.commandId, first.commandDigest);
    await queue.append(pendingOperatorCommand(command(MAX_PENDING_OPERATOR_COMMANDS)));
    expect(await queue.list()).toHaveLength(MAX_PENDING_OPERATOR_COMMANDS);
  });

  it("marks age for explicit repair without letting one overdue command deadlock unrelated capture", async () => {
    const queue = new MemoryPendingOperatorCommandQueue();
    const overdue = pendingOperatorCommand(command(1), new Date("2020-01-01T00:00:00.000Z"));
    expect(Date.parse(overdue.expiresAt)).toBeLessThan(Date.now());
    await queue.append(overdue);
    await queue.append(pendingOperatorCommand(command(2)));
    expect(await queue.list()).toHaveLength(2);
  });
});
