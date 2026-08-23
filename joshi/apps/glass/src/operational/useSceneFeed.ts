import { useEffect, useState } from "react";

import type { LoopbackSceneFeedSource, SceneFeedV1 } from "../data/sceneFeed";

export type SceneFeedState = {
  /** The last feed the core served; kept through a failed poll so known facts stay known. */
  feed: SceneFeedV1 | null;
  /** The core stated that no feed is mounted; polling stops, nothing newer will ever exist. */
  absent: boolean;
  /** Why the last poll failed, when it did. A failed poll never erases the last good feed. */
  error: string | null;
};

/**
 * Gentle polling of the scene feed. The feed is a list of immutable facts; polling it can only
 * ever teach this cockpit that new scenes exist — it never changes what is on screen.
 */
export function useSceneFeed(
  source: LoopbackSceneFeedSource | null,
  intervalMs = 20_000,
): SceneFeedState {
  const [state, setState] = useState<SceneFeedState>({ feed: null, absent: false, error: null });

  useEffect(() => {
    if (!source) return;
    let active = true;
    let timer: number | null = null;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const loaded = await source.load(controller.signal);
        if (!active) return;
        if ("absent" in loaded) {
          setState({ feed: null, absent: true, error: null });
          return;
        }
        setState({ feed: loaded, absent: false, error: null });
      } catch (error) {
        if (!active) return;
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error.message : "Scene feed poll failed.",
        }));
      }
      if (active) timer = window.setTimeout(() => void poll(), intervalMs);
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [intervalMs, source]);

  return state;
}
