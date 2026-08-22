import { useCallback, useEffect, useMemo, useState } from "react";

import type { Candidate } from "../contract/v1";

function byIdentity(left: Candidate, right: Candidate): number {
  return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
}

function rankedIds(candidates: Candidate[]): string[] {
  return [...candidates]
    .sort((left, right) => {
      // A candidate the view states no rank for sorts after every ranked one, by identity. It is
      // not silently treated as rank 0, which would promote an unranked row to the top of the
      // feed, and it is not dropped, which would hide a served candidate.
      if (left.rank === null || right.rank === null) {
        if (left.rank === right.rank) return byIdentity(left, right);
        return left.rank === null ? 1 : -1;
      }
      const leftRank = BigInt(left.rank);
      const rightRank = BigInt(right.rank);
      return leftRank < rightRank ? -1 : leftRank > rightRank ? 1 : byIdentity(left, right);
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
