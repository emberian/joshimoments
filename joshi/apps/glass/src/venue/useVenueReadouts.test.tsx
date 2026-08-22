import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VenueReadoutSource } from "./client";
import type { VenueReadoutAnswer } from "./contract";
import { useVenueReadouts } from "./useVenueReadouts";

function source(load: (mint: string) => Promise<VenueReadoutAnswer>): VenueReadoutSource {
  return { kind: "loopback", load: vi.fn(load) as VenueReadoutSource["load"] };
}

const measured = (mint: string): VenueReadoutAnswer => ({
  state: "absent",
  absence: `answered for ${mint}`,
});

describe("asking the local core about held coins", () => {
  it("asks once per mint, and not again when the same set re-renders", async () => {
    const load = vi.fn(async (mint: string) => Promise.resolve(measured(mint)));
    const stub: VenueReadoutSource = { kind: "loopback", load };
    const { result, rerender } = renderHook(
      ({ mints }: { mints: string[] }) => useVenueReadouts(stub, mints),
      { initialProps: { mints: ["mintA", "mintB"] } },
    );
    await waitFor(() => expect(result.current["mintA"]?.state).toBe("absent"));
    expect(load).toHaveBeenCalledTimes(2);

    rerender({ mints: ["mintA", "mintB"] });
    await waitFor(() => expect(result.current["mintB"]).toBeDefined());
    // One retained capture at one slot: re-asking would return the same bytes with a longer age,
    // so a second request would be a refresh that did not happen.
    expect(load).toHaveBeenCalledTimes(2);

    rerender({ mints: ["mintA", "mintB", "mintC"] });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load).toHaveBeenLastCalledWith("mintC", expect.anything());
  });

  it("says a coin is being asked about rather than leaving it looking unmeasured", async () => {
    let release: ((answer: VenueReadoutAnswer) => void) | undefined;
    const stub = source(
      () => new Promise<VenueReadoutAnswer>((resolve) => {
        release = resolve;
      }),
    );
    const { result } = renderHook(() => useVenueReadouts(stub, ["mintA"]));
    await waitFor(() => expect(result.current["mintA"]).toBeDefined());
    expect(result.current["mintA"]).toEqual({
      state: "absent",
      absence: "Asking the local core what this venue costs. No number is stated yet.",
    });
    await act(async () => {
      release?.({ state: "absent", absence: "done" });
    });
    await waitFor(() => expect(result.current["mintA"]?.state).toBe("absent"));
  });

  it("turns a failed request into an absence in its own words, never into a number", async () => {
    const stub = source(() => Promise.reject(new Error("core refused the connection")));
    const { result } = renderHook(() => useVenueReadouts(stub, ["mintA"]));
    await waitFor(() =>
      expect(result.current["mintA"]).toEqual({
        state: "absent",
        absence:
          "The readout request failed: core refused the connection. Nothing here is a claim about the coin.",
      }),
    );
  });

  it("asks nothing at all when this cockpit has no venue source", () => {
    const { result } = renderHook(() => useVenueReadouts(null, ["mintA", "mintB"]));
    // Not an empty measurement: an empty map means the caller renders "nothing has asked", which
    // is a different sentence from "nothing was measured".
    expect(result.current).toEqual({});
  });
});
