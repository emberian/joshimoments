import { describe, expect, it } from "vitest";

import { mockSnapshots } from "./mockSnapshot";

const LATER_SENTINELS = [
  "249999.00",
  "later-cluster",
  "LATER_SOCIAL_CLUSTER",
  "LATER_REENTRY",
  "LATER_SOURCE_RECOVERY",
  "LATER_POST",
  "LATER_CLAIM",
];

describe("single-mode replay fixtures", () => {
  it.each(["witnessed", "knowledge_cutoff"] as const)("contains no retrospective fields in %s bytes", (mode) => {
    const serialized = JSON.stringify(mockSnapshots[mode].view);
    for (const sentinel of LATER_SENTINELS) expect(serialized).not.toContain(sentinel);
  });

  it("places later metrics, tags, episodes, source recovery, and events only in the retrospective DTO", () => {
    const serialized = JSON.stringify(mockSnapshots.retrospective.view);
    for (const sentinel of LATER_SENTINELS) expect(serialized).toContain(sentinel);
    expect(mockSnapshots.retrospective.view.basisSceneId).toBe(mockSnapshots.witnessed.view.sceneId);
    expect(mockSnapshots.retrospective.snapshotDigest).not.toBe(mockSnapshots.witnessed.snapshotDigest);
  });

  it("does not carry dual ranks or a mixed replay bundle in any served candidate", () => {
    for (const snapshot of Object.values(mockSnapshots)) {
      expect(snapshot).not.toHaveProperty("replay");
      for (const candidate of snapshot.view.payload.candidates) {
        expect(typeof candidate.rank).toBe("string");
        expect(candidate.rank).not.toHaveProperty("witnessed");
        expect(candidate.rank).not.toHaveProperty("retrospective");
      }
    }
  });

  it("retains independent census and hot-lane cursors without selecting a source-wide latest", () => {
    const pumpBoard = mockSnapshots.witnessed.view.asOf.sources.find((source) => source.sourceId === "pump-board");
    expect(pumpBoard?.cursors).toEqual([
      expect.objectContaining({ family: "attention", subject: null, cursorKind: "epoch" }),
      expect.objectContaining({ family: "attention", subject: "hot:radon", cursorKind: "sequence" }),
    ]);
    expect(pumpBoard).not.toHaveProperty("sourceCursor");
  });
});
