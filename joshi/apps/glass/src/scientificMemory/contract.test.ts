import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  digestOperatorActBytes,
  parseCanonicalOperatorActBytes,
} from "./contract";
import {
  MemoryPendingScientificMemoryActQueue,
  pendingScientificMemoryAct,
} from "./pendingQueue";

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), "../../fixtures/scientific-memory/adversarial.v1.json"), "utf8")) as {
  canonicalGoldens: Array<{ name: string; canonicalOccurrence: string; digest: string }>;
};
const golden = fixture.canonicalGoldens.find((entry) => entry.name === "external_manual_execution_escape_with_presentation_gap");
if (!golden) throw new Error("scientific-memory manual escape golden is absent");

describe("scientific-memory OperatorAct browser seam", () => {
  it("pins the Rust canonical manual-escape/presentation-gap bytes and digest", () => {
    const bytes = new TextEncoder().encode(golden.canonicalOccurrence);
    const act = parseCanonicalOperatorActBytes(bytes);
    expect(new TextDecoder().decode(new TextEncoder().encode(JSON.stringify(act)))).toBe(golden.canonicalOccurrence);
    expect(digestOperatorActBytes(bytes)).toBe(golden.digest);
    expect(act.value.occurredAt).toBe("12");
    expect(act.value.scene.status === "committed" && act.value.scene.value.catalogCutoff).toBe("10");
  });

  it.each([
    golden.canonicalOccurrence.replace('"occurredAt":"12"', '"occurredAt":"012"'),
    golden.canonicalOccurrence.replace('"occurredAt":"12"', '"occurredAt":"0"'),
    golden.canonicalOccurrence.replace('"catalogCutoff":"10"', '"catalogCutoff":"10.0"'),
    golden.canonicalOccurrence.replace('"detectedAt":"11"', '"detectedAt":11'),
    golden.canonicalOccurrence.replace('"actId":"act-escape"', '"actId":"other","actId":"act-escape"'),
  ])("refuses noncanonical time/precision or duplicate-key bytes", (wire) => {
    expect(() => parseCanonicalOperatorActBytes(new TextEncoder().encode(wire))).toThrow();
  });

  it("retains exact canonical bytes immediately and only removes the matching store ACK", async () => {
    const occurrence = parseCanonicalOperatorActBytes(new TextEncoder().encode(golden.canonicalOccurrence));
    const pending = pendingScientificMemoryAct(occurrence, new Date("2026-08-18T12:00:00.000Z"));
    const queue = new MemoryPendingScientificMemoryActQueue();
    await queue.append(pending);
    await expect(queue.acknowledge(pending.actId, `sha256:${"0".repeat(64)}`)).rejects.toThrow(/ACK digest/i);
    expect((await queue.list())[0]?.canonicalOccurrence).toBe(golden.canonicalOccurrence);
    await queue.acknowledge(pending.actId, pending.occurrenceDigest);
    expect(await queue.list()).toEqual([]);
  });
});
