import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Candidate } from "../contract/v1";
import { mockSnapshots } from "../data/mockSnapshot";
import { useStableCandidateOrder } from "../sensorium/useStableCandidateOrder";
import { AttentionFeed } from "./AttentionFeed";

function Harness({ candidates }: { candidates: Candidate[] }) {
  const order = useStableCandidateOrder(candidates, "stable-order-scene");
  return <AttentionFeed
    candidates={order.orderedCandidates}
    selectedId={order.orderedCandidates[0]?.id ?? "none"}
    onSelect={() => {}}
    board="all"
    onBoardChange={() => {}}
    density="comfortable"
    focusRequest={0}
    onViewportChange={() => {}}
    orderUpdatePending={order.pending}
    pendingNewCount={order.pendingNewCount}
    onAcceptOrderUpdate={order.acceptPendingOrder}
  />;
}

function renderedCandidateIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll<HTMLElement>("[data-candidate-id]")]
    .map((element) => element.dataset.candidateId)
    .filter((value): value is string => value !== undefined);
}

describe("attention-feed order acceptance", () => {
  it("keeps DOM order and focus stable until the operator accepts the new order", async () => {
    const initial = structuredClone(mockSnapshots.witnessed.view.payload.candidates.slice(0, 2));
    initial[0]!.rank = "1";
    initial[1]!.rank = "2";
    const user = userEvent.setup();
    const { container, rerender } = render(<Harness candidates={initial} />);
    await waitFor(() => expect(renderedCandidateIds(container)).toHaveLength(2));
    const originalOrder = renderedCandidateIds(container);
    const focused = container.querySelector<HTMLButtonElement>(`[data-candidate-id='${originalOrder[0]}']`);
    expect(focused).not.toBeNull();
    if (!focused) throw new Error("candidate button did not render");
    focused.focus();

    const updated = structuredClone(initial);
    updated[0]!.rank = "2";
    updated[1]!.rank = "1";
    rerender(<Harness candidates={updated} />);

    expect(renderedCandidateIds(container)).toEqual(originalOrder);
    expect(focused).toHaveFocus();
    const positionsBefore = [...container.querySelectorAll(".virtual-row")].map((row) => row.getAttribute("aria-posinset"));
    expect(positionsBefore).toEqual(["1", "2"]);
    await user.click(screen.getByRole("button", { name: /accept updated order/i }));
    expect(renderedCandidateIds(container)).toEqual([...originalOrder].reverse());
  });
});
