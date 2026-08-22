import { useEffect, useRef, useState } from "react";

import type { VenueReadoutAnswer } from "./contract";
import type { VenueReadoutSource } from "./client";

/**
 * Asks the local core what each held coin's venue costs, once per mint.
 *
 * Held coins are the whole point: they are the few she chose out of a feed that will not stop
 * moving, and they are bounded by how many she can hold in mind. So this asks per held mint and
 * never per feed row -- the feed carries hundreds and none of them have been chosen yet.
 *
 * It asks once per mint. The core serves one retained capture at one slot, so re-asking would
 * return the same bytes with a longer age, and a second request that produced the same numbers
 * would read as a refresh that did not happen. What changes on screen is the age, and the age is
 * computed from the receipt the core already sent.
 */
export function useVenueReadouts(
  source: VenueReadoutSource | null,
  mints: readonly string[],
): Record<string, VenueReadoutAnswer> {
  const [answers, setAnswers] = useState<Record<string, VenueReadoutAnswer>>({});
  // Asked-for mints live in a ref rather than in the answer map so a double-invoked effect cannot
  // send a second request for a coin already in flight.
  const asked = useRef<Set<string>>(new Set());
  // Joined rather than compared as an array so a re-render with an equal set does no work. Mints
  // are base58 and carry no separator, so the join is unambiguous.
  const key = mints.join(" ");

  useEffect(() => {
    if (!source) return;
    const wanted = key.length === 0 ? [] : key.split(" ");
    const controller = new AbortController();
    const fresh = wanted.filter((mint) => !asked.current.has(mint));
    if (fresh.length === 0) return () => controller.abort();
    for (const mint of fresh) asked.current.add(mint);
    // A coin mid-request says so in its own words. It never reads as a coin nobody measured, and
    // it never reads as a zero.
    setAnswers((current) => {
      const pending: Record<string, VenueReadoutAnswer> = { ...current };
      for (const mint of fresh) {
        pending[mint] = {
          state: "absent",
          absence: "Asking the local core what this venue costs. No number is stated yet.",
        };
      }
      return pending;
    });
    for (const mint of fresh) {
      void source
        .load(mint, controller.signal)
        .then((answer) => {
          if (!controller.signal.aborted) {
            setAnswers((existing) => ({ ...existing, [mint]: answer }));
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            // The request was dropped, so this mint was never answered and must be askable again.
            asked.current.delete(mint);
            return;
          }
          setAnswers((existing) => ({
            ...existing,
            [mint]: {
              state: "absent",
              absence: `The readout request failed: ${
                error instanceof Error ? error.message : "unknown failure"
              }. Nothing here is a claim about the coin.`,
            },
          }));
        });
    }
    return () => controller.abort();
  }, [key, source]);

  return answers;
}
