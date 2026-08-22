import { useCallback, useEffect, useRef, useState } from "react";

import { exactUtcNow } from "./contract";
import type { DurableSceneCommands, OperatorCommandReader } from "./readback";

/**
 * What the durable read-back actually is right now, at the resolution the surface may claim.
 *
 * Every state is explicit and renders as itself: `no_catalog` is a stated absence (offline
 * fixture), `failed` keeps the reason, and only `read` carries catalog content — stamped with
 * when it was read, because a journal that silently ages is a journal that lies about "now".
 */
export type DurableJournalReadback =
  | { state: "no_scene" }
  | { state: "reading" }
  | { state: "no_catalog"; absence: string }
  | { state: "read"; answer: DurableSceneCommands; readAt: string }
  | { state: "failed"; reason: string };

/**
 * Reads the durable operator commands bound to one scene, once per scene and on demand.
 *
 * On-demand re-reading is the loop that makes the journal shared: the primary agent appends an
 * entry through the same core route mid-session, and "Read the catalog again" makes it visible
 * without a reload.
 */
export function useDurableSceneCommands(
  reader: OperatorCommandReader,
  sceneId: string | null,
): { readback: DurableJournalReadback; reread: () => void } {
  const [readback, setReadback] = useState<DurableJournalReadback>({ state: "no_scene" });
  const generation = useRef(0);

  const read = useCallback((requestedSceneId: string) => {
    generation.current += 1;
    const requested = generation.current;
    setReadback({ state: "reading" });
    reader
      .listSceneCommands(requestedSceneId)
      .then((answer) => {
        if (generation.current !== requested) return;
        setReadback(answer.state === "no_catalog"
          ? { state: "no_catalog", absence: answer.absence }
          : { state: "read", answer: answer.answer, readAt: exactUtcNow() });
      })
      .catch((error: unknown) => {
        if (generation.current !== requested) return;
        setReadback({
          state: "failed",
          reason: error instanceof Error ? error.message : "Operator readback failed.",
        });
      });
  }, [reader]);

  useEffect(() => {
    if (sceneId === null) {
      generation.current += 1;
      setReadback({ state: "no_scene" });
      return;
    }
    read(sceneId);
  }, [read, sceneId]);

  const reread = useCallback(() => {
    if (sceneId !== null) read(sceneId);
  }, [read, sceneId]);

  return { readback, reread };
}
