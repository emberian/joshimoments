import { act, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  digestProspectiveNomination,
  prospectiveNominationReceiptV1Schema,
  type ProspectiveNominationCommandV1,
} from "./contract";
import { fixtureSessionLaunch } from "./fixtures";
import { ProspectiveNomination, type ProspectiveNominationSink } from "./ProspectiveNomination";

function receiptFor(command: ProspectiveNominationCommandV1) {
  return prospectiveNominationReceiptV1Schema.parse({
    contract: "joshi.store.prospective_nomination_receipt",
    schemaVersion: 1,
    catalogId: "catalog-test",
    catalogSchema: "joshi.sqlite.v7",
    batchId: "nomination-batch-test",
    nominationId: command.nominationId,
    episodeLaunchId: command.episodeLaunchId,
    subject: command.subject,
    scene: command.scene,
    presentation: command.presentation,
    choiceUniverseDigest: command.choiceUniverseDigest,
    nominationDigest: digestProspectiveNomination(command),
    commitSeq: "8101",
    status: "accepted",
  });
}

afterEach(() => vi.useRealTimers());

describe("prospective nomination", () => {
  it("echoes only a server-issued membership and commits only after the exact receipt", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T18:10:00.000Z"));
    let attempted: ProspectiveNominationCommandV1 | null = null;
    let release: (() => void) | null = null;
    const sink: ProspectiveNominationSink = {
      appendProspectiveNomination(command) {
        attempted = command;
        return new Promise((resolve) => { release = () => resolve(receiptFor(command)); });
      },
    };
    render(<ProspectiveNomination
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
    fireEvent.change(screen.getByLabelText(/preregistered subject/i), { target: { value: "radon" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /one prospective nomination/i }));
    fireEvent.click(screen.getByRole("button", { name: /record qualifying nomination/i }));
    expect(screen.getByRole("button", { name: /awaiting durable receipt/i })).toBeDisabled();
    expect(screen.queryByText(/durable nomination receipt/i)).not.toBeInTheDocument();
    await act(async () => {
      release?.();
      await Promise.resolve();
    });
    expect(screen.getByText(/durable nomination receipt · commit 8101/i)).toBeInTheDocument();
    const expectedMember = fixtureSessionLaunch.registration.choiceMembers.find((member) => member.subjectId === "radon");
    expect(attempted).toMatchObject({
      nominationId: fixtureSessionLaunch.registration.reservedCommandId,
      idempotencyKey: fixtureSessionLaunch.registration.reservedCommandIdempotencyKey,
      subject: expectedMember,
      choiceUniverseDigest: fixtureSessionLaunch.registration.choiceUniverseDigest,
      decisionDeadline: "2026-08-17T18:18:00.000000Z",
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    expect(JSON.stringify(attempted)).not.toMatch(/trade|signer|transaction|quantity|slippage/i);
  });

  it("cannot nominate an unregistered subject and disables after the other branch is prepared", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T18:10:00.000Z"));
    render(<ProspectiveNomination
      launch={fixtureSessionLaunch}
      protocol={fixtureSessionLaunch.protocol}
      presentation={{
        presentationId: fixtureSessionLaunch.registration.reservedPresentationId,
        presentationDigest: `sha256:${"f".repeat(64)}`,
        assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      }}
      clientSessionId="paired-session-test"
      sink={{ appendProspectiveNomination: async (command) => receiptFor(command) }}
      lockedBranch="abstention"
    />);
    const subject = screen.getByLabelText(/preregistered subject/i);
    expect(subject).toBeDisabled();
    expect(Array.from((subject as HTMLSelectElement).options).map((option) => option.value)).toEqual(["", "crashius", "earthcoin", "radon"]);
    expect(screen.getByText(/abstention branch already owns/i)).toBeInTheDocument();
  });

  it("has no automatically detectable accessibility violations", async () => {
    render(<ProspectiveNomination
      launch={fixtureSessionLaunch}
      protocol={fixtureSessionLaunch.protocol}
      presentation={{
        presentationId: fixtureSessionLaunch.registration.reservedPresentationId,
        presentationDigest: `sha256:${"f".repeat(64)}`,
        assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      }}
      clientSessionId="paired-session-test"
      sink={{ appendProspectiveNomination: async (command) => receiptFor(command) }}
    />);
    expect((await axe.run(screen.getByRole("complementary"), { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
  });
});
