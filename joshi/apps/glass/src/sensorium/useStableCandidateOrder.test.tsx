import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockSnapshots } from "../data/mockSnapshot";
import { useStableCandidateOrder } from "./useStableCandidateOrder";

describe("stable attention order", () => {
  it("buffers rank and membership changes until explicit acceptance", () => {
    const initial = structuredClone(mockSnapshots.witnessed.view.payload.candidates.slice(0, 2));
    initial[0]!.rank = "1";
    initial[1]!.rank = "2";
    const { result, rerender } = renderHook(
      ({ candidates }) => useStableCandidateOrder(candidates, "scene-fixture"),
      { initialProps: { candidates: initial } },
    );
    const firstOrder = result.current.orderedCandidates.map((candidate) => candidate.id);

    const updated = structuredClone(initial);
    updated[0]!.rank = "2";
    updated[1]!.rank = "1";
    rerender({ candidates: updated });
    expect(result.current.pending).toBe(true);
    expect(result.current.orderedCandidates.map((candidate) => candidate.id)).toEqual(firstOrder);

    act(() => result.current.acceptPendingOrder());
    expect(result.current.pending).toBe(false);
    expect(result.current.orderedCandidates.map((candidate) => candidate.id)).toEqual([...firstOrder].reverse());
  });

  it("compares wire-u64 ranks exactly beyond JavaScript's safe integer range", () => {
    const candidates = structuredClone(mockSnapshots.witnessed.view.payload.candidates.slice(0, 2));
    candidates[0]!.rank = "9007199254740993";
    candidates[1]!.rank = "9007199254740992";
    const { result } = renderHook(() => useStableCandidateOrder(candidates, "wide-rank-scene"));
    expect(result.current.orderedCandidates.map((candidate) => candidate.id)).toEqual([
      candidates[1]!.id,
      candidates[0]!.id,
    ]);
  });
});
