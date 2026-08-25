import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GlassApp } from "./App";
import type { CandidateSliceAnswer } from "./data/candidateSlice";
import { OfflineFixtureDataSource, type GlassDataSource, type SnapshotRequest } from "./data/client";
import { mockSnapshots } from "./data/mockSnapshot";

/**
 * The coin page's slice consultation: when its data source serves candidate slices, opening
 * the page asks for exactly the (scene, candidate) on it, verifies the slice against the
 * loaded view's digest, and adopts the sliced bytes ONLY when they verify and differ — a
 * digest that does not match the view on screen must never put bytes on the page, however
 * fresh they claim to be.
 */
function slicingSource(answer: (sceneId: string, candidateId: string) => CandidateSliceAnswer) {
  const delegate = new OfflineFixtureDataSource();
  const calls: string[] = [];
  const source: GlassDataSource = {
    kind: delegate.kind,
    loadSnapshot: (request: SnapshotRequest) => delegate.loadSnapshot(request),
    candidateSlice: async (sceneId: string, candidateId: string) => {
      calls.push(`${sceneId}/${candidateId}`);
      return answer(sceneId, candidateId);
    },
  };
  return { source, calls };
}

function sliceFor(candidateId: string, viewDigest: string, tags: string[]): CandidateSliceAnswer {
  const witnessed = mockSnapshots.witnessed;
  const candidate = witnessed.view.payload.candidates.find((item) => item.id === candidateId);
  if (!candidate) throw new Error(`fixture carries no candidate ${candidateId}`);
  return {
    state: "sliced",
    slice: {
      contract: "joshi.glass.candidate_slice",
      schemaVersion: 1,
      sceneId: witnessed.view.sceneId,
      viewDigest,
      mode: "witnessed",
      catalogCommit: witnessed.view.asOf.catalogCommit,
      renderedAt: witnessed.view.asOf.renderedAt,
      renderedCandidateCount: String(witnessed.view.payload.candidates.length),
      renderedOrdinal: "0",
      candidate: { ...candidate, tags },
    },
  };
}

describe("coin page candidate slice", () => {
  it("asks for the inspected coin's slice and adopts verified differing bytes", async () => {
    const digest = mockSnapshots.witnessed.snapshotDigest;
    const { source, calls } = slicingSource((_sceneId, candidateId) =>
      sliceFor(candidateId, digest, ["sliced-adopted"]));
    render(<GlassApp dataSource={source} initialSurface="inspect" />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await waitFor(() => expect(calls).toContain(`${mockSnapshots.witnessed.view.sceneId}/radon`));
    // The slice differs from the loaded candidate (its tags), verifies against the view
    // digest, and is adopted: the differing tag renders in the coin header.
    expect(await screen.findByText("sliced-adopted")).toBeInTheDocument();
  });

  it("refuses a slice whose view digest is not the view on screen", async () => {
    const { source, calls } = slicingSource((_sceneId, candidateId) =>
      sliceFor(candidateId, `sha256:${"e".repeat(64)}`, ["sliced-adopted"]));
    render(<GlassApp dataSource={source} initialSurface="inspect" />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(screen.queryByText("sliced-adopted")).not.toBeInTheDocument();
  });
});
