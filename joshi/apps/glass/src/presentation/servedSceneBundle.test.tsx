import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GlassApp } from "../App";
import type { GlassSnapshotV1 } from "../contract/v1";
import { LoopbackDataSource, type GlassDataSource, type SnapshotRequest } from "../data/client";
import { mockSnapshots } from "../data/mockSnapshot";
import { OfflineFixturePresentationSink } from "./client";
import { explorationBundleFor } from "./fixtures";
import { explorationBundleForServedScene } from "./servedSceneBundle";

/**
 * Values that exist only in the offline fixture bundle. None of them is derivable from a served
 * Glass view, so any one of them appearing on a loopback-sourced screen means authored numbers
 * reached a surface that reads as live. This list is the regression, not the wording around it.
 */
const AUTHORED_SENTINELS = [
  "384000000",
  "900000000",
  "150000000",
  "42000000",
  "84000000",
  "620000",
  "ORBITFAN",
  "orbitfan",
  "7kQ",
  "2mP",
  "Observed gross in",
  "Observed arriving accounts",
  "Observed displacement recovery",
  "Effective support",
  "Actor-edge churn",
];

/**
 * Exactly the production `LoopbackDataSource` in every respect `GlassApp` observes -- its `kind`
 * and its real `presentationMaterials` -- but answering from memory so no core is needed.
 */
class LoopbackLikeSource implements GlassDataSource {
  readonly kind = "loopback" as const;
  private readonly real = new LoopbackDataSource("http://127.0.0.1:43119", "scene-launch");

  async loadSnapshot(_request: SnapshotRequest): Promise<GlassSnapshotV1> {
    return mockSnapshots.witnessed;
  }

  presentationMaterials(snapshot: GlassSnapshotV1) {
    return this.real.presentationMaterials(snapshot);
  }
}

describe("exploration bundle for a served scene", () => {
  const snapshot = mockSnapshots.witnessed;

  it("keeps the eight-panel frame the contract requires and leaves every panel empty", () => {
    const bundle = explorationBundleForServedScene(snapshot);
    expect(bundle.panels).toHaveLength(8);
    expect(new Set(bundle.panels.map((panel) => panel.viewKind)).size).toBe(8);
    for (const panel of bundle.panels) {
      expect(panel.signals).toEqual([]);
      expect(panel.relations).toEqual([]);
      expect(panel.marks).toEqual([]);
      expect(panel.question.length).toBeGreaterThan(0);
      expect(panel.claimBoundary.length).toBeGreaterThan(0);
    }
    expect(bundle.claim).toBe("descriptive_noncausal");
  });

  it("carries no value the served snapshot does not carry", () => {
    const serialized = JSON.stringify(explorationBundleForServedScene(snapshot));
    for (const sentinel of AUTHORED_SENTINELS) expect(serialized).not.toContain(sentinel);
  });

  it("binds its sole source artifact to the exact verified view digest", () => {
    const bundle = explorationBundleForServedScene(snapshot);
    expect(bundle.sourceArtifacts).toHaveLength(1);
    expect(bundle.sourceArtifacts[0]?.artifactDigest).toBe(snapshot.snapshotDigest);
    expect(bundle.sourceArtifacts[0]?.admissionStatus).toBe("observed_unaccepted");
    expect(bundle.scene.viewDigest).toBe(snapshot.snapshotDigest);
  });

  it("is a deterministic function of the snapshot", () => {
    expect(JSON.stringify(explorationBundleForServedScene(snapshot)))
      .toBe(JSON.stringify(explorationBundleForServedScene(snapshot)));
  });

  it("is not the offline fixture bundle, which does carry authored numbers", () => {
    // Guards the sentinel list itself: if the fixture bundle ever stops containing these, the
    // test above would pass vacuously and stop protecting the live path.
    const fixtureSerialized = JSON.stringify(explorationBundleFor(snapshot));
    for (const sentinel of AUTHORED_SENTINELS) expect(fixtureSerialized).toContain(sentinel);
  });
});

describe("a loopback-sourced cockpit", () => {
  it("renders no authored exploration number and states each empty view as an absence", async () => {
    render(
      <GlassApp
        dataSource={new LoopbackLikeSource()}
        presentationSink={new OfflineFixturePresentationSink()}
      />,
    );
    expect(await screen.findByRole("heading", { name: /field lab/i })).toBeInTheDocument();
    for (const sentinel of AUTHORED_SENTINELS) {
      expect(screen.queryByText(new RegExp(sentinel))).not.toBeInTheDocument();
    }
    expect(await screen.findByText(/No rows in this evidence cut/i)).toBeInTheDocument();
  });
});
