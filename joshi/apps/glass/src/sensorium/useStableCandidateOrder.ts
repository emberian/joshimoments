import { useCallback, useEffect, useMemo, useState } from "react";

import type { Candidate } from "../contract/v1";

function rankedIds(candidates: Candidate[]): string[] {
  return [...candidates]
    .sort((left, right) => {
      const leftRank = BigInt(left.rank);
      const rightRank = BigInt(right.rank);
      return leftRank < rightRank ? -1 : leftRank > rightRank ? 1 : left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
    })
    .map((candidate) => candidate.id);
}

function equal(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export function useStableCandidateOrder(candidates: Candidate[], sceneId: string) {
  const targetIds = useMemo(() => rankedIds(candidates), [candidates]);
  const [accepted, setAccepted] = useState(() => ({ sceneId, ids: targetIds }));

  useEffect(() => {
    if (accepted.sceneId !== sceneId) setAccepted({ sceneId, ids: targetIds });
  }, [accepted.sceneId, sceneId, targetIds]);

  const effectiveIds = accepted.sceneId === sceneId ? accepted.ids : targetIds;
  const byId = useMemo(() => new Map(candidates.map((candidate) => [candidate.id, candidate])), [candidates]);
  const orderedCandidates = effectiveIds.map((id) => byId.get(id)).filter((candidate): candidate is Candidate => candidate !== undefined);
  const pending = !equal(effectiveIds, targetIds);
  const pendingNewCount = targetIds.filter((id) => !effectiveIds.includes(id)).length;

  const acceptPendingOrder = useCallback(() => {
    setAccepted({ sceneId, ids: targetIds });
  }, [sceneId, targetIds]);

  return { orderedCandidates, pending, pendingNewCount, acceptPendingOrder };
}
