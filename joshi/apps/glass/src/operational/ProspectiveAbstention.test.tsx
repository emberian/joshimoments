import { act, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  digestExplicitAbstention,
  explicitAbstentionReceiptV1Schema,
  type ExplicitAbstentionCommandV1,
} from "./contract";
import { fixtureSessionLaunch } from "./fixtures";
import { ProspectiveAbstention, type AbstentionSink } from "./ProspectiveAbstention";

function receiptFor(command: ExplicitAbstentionCommandV1) {
  return explicitAbstentionReceiptV1Schema.parse({
    contract: "joshi.store.explicit_abstention_receipt",
    schemaVersion: 1,
    catalogId: "catalog-test",
    catalogSchema: "joshi.sqlite.v7",
    batchId: "abstention-batch-test",
    abstentionId: command.abstentionId,
    episodeLaunchId: command.episodeLaunchId,
    scene: command.scene,
    presentation: command.presentation,
    choiceUniverseDigest: command.choiceUniverseDigest,
    abstentionDigest: digestExplicitAbstention(command),
    commitSeq: "8100",
    status: "accepted",
  });
}

afterEach(() => vi.useRealTimers());

describe("prospective explicit abstention", () => {
  it("is warmup/deadline gated, accessible, and becomes committed only after its exact receipt", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T18:10:00.000Z"));
    let attempted: ExplicitAbstentionCommandV1 | null = null;
    let release: (() => void) | null = null;
    const sink: AbstentionSink = {
      appendAbstention(command) {
        attempted = command;
        return new Promise((resolve) => { release = () => resolve(receiptFor(command)); });
      },
    };
    render(<ProspectiveAbstention
      launch={fixtureSessionLaunch}
      protocol={fixtureSessionLaunch.protocol}
      presentation={{
        presentationId: fixtureSessionLaunch.registration.reservedPresentationId,
        presentationDigest: `sha256:${"f".repeat(64)}`,
        assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      }}
      clientSessionId="paired-session-test"
      sink={sink}
    />);
    expect(screen.getByText(/choice window open/i)).toHaveTextContent("2026-08-17T18:18:00.000000Z");
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "insufficient_evidence" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /record an explicit abstention/i }));
    fireEvent.click(screen.getByRole("button", { name: /record explicit abstention/i }));
    expect(screen.getByRole("button", { name: /awaiting durable receipt/i })).toBeDisabled();
    expect(screen.queryByText(/durable abstention receipt/i)).not.toBeInTheDocument();
    await act(async () => {
      release?.();
      await Promise.resolve();
    });
    expect(screen.getByText(/durable abstention receipt · commit 8100/i)).toBeInTheDocument();
    expect(attempted).toMatchObject({
      abstentionId: fixtureSessionLaunch.registration.reservedCommandId,
      idempotencyKey: fixtureSessionLaunch.registration.reservedCommandIdempotencyKey,
      decisionDeadline: "2026-08-17T18:18:00.000000Z",
      reason: "insufficient_evidence",
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    expect(JSON.stringify(attempted)).not.toMatch(/trade|signer|transaction|quantity|slippage/i);
  });

  it("retries byte-identical reserved command identity after an ambiguous failure", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T18:10:00.000Z"));
    const attempts: string[] = [];
    const sink: AbstentionSink = {
      async appendAbstention(command) {
        attempts.push(JSON.stringify(command));
        if (attempts.length === 1) throw new Error("ambiguous local disconnect");
        return receiptFor(command);
      },
    };
    render(<ProspectiveAbstention
      launch={fixtureSessionLaunch}
      protocol={fixtureSessionLaunch.protocol}
      presentation={{
        presentationId: fixtureSessionLaunch.registration.reservedPresentationId,
        presentationDigest: `sha256:${"f".repeat(64)}`,
        assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      }}
      clientSessionId="paired-session-test"
      sink={sink}
    />);
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "attention_limit" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /record an explicit abstention/i }));
    fireEvent.click(screen.getByRole("button", { name: /record explicit abstention/i }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole("alert")).toHaveTextContent(/ambiguous local disconnect/i);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /retry exact bytes/i }));
      await Promise.resolve();
    });
    expect(attempts).toHaveLength(2);
    expect(attempts[1]).toBe(attempts[0]);
    expect(screen.getByText(/durable abstention receipt/i)).toBeInTheDocument();
  });

  it("has no automatically detectable accessibility violations", async () => {
    render(<ProspectiveAbstention
      launch={fixtureSessionLaunch}
      protocol={fixtureSessionLaunch.protocol}
      presentation={{
        presentationId: fixtureSessionLaunch.registration.reservedPresentationId,
        presentationDigest: `sha256:${"f".repeat(64)}`,
        assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      }}
      clientSessionId="paired-session-test"
      sink={{ appendAbstention: async (command) => receiptFor(command) }}
    />);
    expect((await axe.run(screen.getByRole("complementary"), { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
  });
});
