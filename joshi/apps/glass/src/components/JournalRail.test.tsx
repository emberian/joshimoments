import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import { operatorCommandSchema } from "../operator/contract";
import { journalEntryIntent } from "../operator/journal";
import type { DurableOperatorCommand } from "../operator/readback";
import type { DurableJournalReadback } from "../operator/useDurableSceneCommands";
import type { JournalEntry, OperatorIntent } from "../operator/useOperatorJournal";
import { JournalRail } from "./JournalRail";

const SCENE_ID = "scene-journal-rail-test";
const WORDS = "SOLVE likely rips 0-60%; DREGG probably stays 300-500K because Dragon's Clutch is in release prep.";

function durableEntry(overrides: Partial<DurableOperatorCommand> = {}): DurableOperatorCommand {
  return {
    commandId: "command-journal-entry-1",
    commitSeq: "7",
    scene: { sceneId: SCENE_ID, viewDigest: `sha256:${"a".repeat(64)}` },
    clientSessionId: "session-agent-morning",
    clientCommandSeq: "2",
    idempotencyKey: "retry-journal-1",
    commandKind: "record_focus",
    subject: { kind: "scene", key: SCENE_ID },
    issuedAt: "2026-08-22T04:05:06.000000Z",
    receivedAt: "2026-08-22T04:05:07.000000Z",
    clientClockId: "clock-journal-1",
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
    payload: {
      context: {
        uiLabel: "Journal entry",
        uiLabelVersion: "1",
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: WORDS,
      },
      dwellMilliseconds: null,
    },
    ...overrides,
  };
}

function sessionEntry(intent: OperatorIntent, ordinal: number): JournalEntry {
  return {
    command: operatorCommandSchema.parse({
      contract: "joshi.operator.command",
      schemaVersion: 1,
      commandId: `command-session-${ordinal}`,
      idempotencyKey: `retry-session-${ordinal}`,
      clientSessionId: "glass-session-test",
      clientCommandSeq: String(ordinal),
      scene: { sceneId: SCENE_ID, viewDigest: `sha256:${"b".repeat(64)}` },
      issuedAt: "2026-08-22T05:00:00.000000Z",
      clientClock: { clockId: "browser-clock-test", monotonicNs: String(ordinal) },
      commandKind: intent.commandKind,
      subject: intent.subject,
      payload: intent.payload,
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    }),
    label: intent.label,
    status: "retaining_local",
    receipt: null,
    error: null,
    pendingEnqueuedAt: "2026-08-22T05:00:00.000000Z",
    pendingRepairRequiredAt: "2026-08-29T05:00:00.000000Z",
  };
}

function renderRail(readback: DurableJournalReadback, sessionEntries: JournalEntry[] = []) {
  const onAppendEntry = vi.fn((words: string) => {
    journalEntryIntent(SCENE_ID, words);
  });
  const onReread = vi.fn();
  render(
    <JournalRail
      sceneId={SCENE_ID}
      candidates={[]}
      readback={readback}
      sessionEntries={sessionEntries}
      onReread={onReread}
      onAppendEntry={onAppendEntry}
    />,
  );
  return { onAppendEntry, onReread };
}

describe("journal rail", () => {
  it("renders a durable act's words verbatim with its commit, session, and scene binding", () => {
    renderRail({
      state: "read",
      answer: { sceneId: SCENE_ID, sceneRetention: "durable", commands: [durableEntry()] },
      readAt: "2026-08-22T06:00:00.000000Z",
    });
    expect(screen.getByText(WORDS)).toBeInTheDocument();
    expect(screen.getByText(/Note, verbatim/)).toBeInTheDocument();
    expect(screen.getByText(/Commit 7/)).toBeInTheDocument();
    expect(screen.getByText("session-agent-morning")).toBeInTheDocument();
    expect(screen.getByText(/Bound to the exact served bytes/)).toBeInTheDocument();
    expect(screen.getByText(/1 durable act bound to this scene/)).toBeInTheDocument();
  });

  it("states the served-not-yet-durable empty answer instead of a blank", () => {
    renderRail({
      state: "read",
      answer: { sceneId: SCENE_ID, sceneRetention: "served_not_yet_durable", commands: [] },
      readAt: "2026-08-22T06:00:00.000000Z",
    });
    expect(screen.getByText(/no act has made it durable yet/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been said over this scene yet/)).toBeInTheDocument();
  });

  it("states the offline-fixture absence as an absence, not an empty catalog", () => {
    renderRail({ state: "no_catalog", absence: "This cockpit is running on the offline fixture." });
    expect(screen.getByText(/offline fixture/)).toBeInTheDocument();
    expect(screen.queryByText(/durable act/)).not.toBeInTheDocument();
  });

  it("keeps session acts visible and alerts when the catalog read fails", () => {
    renderRail(
      { state: "failed", reason: "operator readback request failed (503)." },
      [sessionEntry(journalEntryIntent(SCENE_ID, "still only in this browser"), 1)],
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be read/);
    expect(screen.getByText("still only in this browser")).toBeInTheDocument();
    expect(screen.getByText(/Retained in this browser only/)).toBeInTheDocument();
  });

  it("never renders one act twice: the catalog's record wins over the session copy", () => {
    const durable = durableEntry();
    const session = sessionEntry(journalEntryIntent(SCENE_ID, WORDS), 2);
    session.command.commandId = durable.commandId;
    renderRail(
      {
        state: "read",
        answer: { sceneId: SCENE_ID, sceneRetention: "durable", commands: [durable] },
        readAt: "2026-08-22T06:00:00.000000Z",
      },
      [session],
    );
    const list = screen.getByRole("list", { name: /Acts bound to this scene/ });
    expect(within(list).getAllByText(WORDS)).toHaveLength(1);
    expect(screen.getByText(/1 act\b/)).toBeInTheDocument();
  });

  it("refuses a blank journal entry with a spoken reason and records nothing", async () => {
    const user = userEvent.setup();
    const { onAppendEntry } = renderRail({
      state: "read",
      answer: { sceneId: SCENE_ID, sceneRetention: "durable", commands: [] },
      readAt: "2026-08-22T06:00:00.000000Z",
    });
    await user.click(screen.getByRole("button", { name: /Append journal entry/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no words/i);
    expect(onAppendEntry).toHaveBeenCalledTimes(1);
  });

  it("re-reads the catalog only on explicit request", async () => {
    const user = userEvent.setup();
    const { onReread } = renderRail({
      state: "read",
      answer: { sceneId: SCENE_ID, sceneRetention: "durable", commands: [durableEntry()] },
      readAt: "2026-08-22T06:00:00.000000Z",
    });
    await user.click(screen.getByRole("button", { name: /Read the catalog again/ }));
    expect(onReread).toHaveBeenCalledTimes(1);
  });

  it("has no detectable accessibility violations in its richest state", async () => {
    renderRail(
      {
        state: "read",
        answer: { sceneId: SCENE_ID, sceneRetention: "durable", commands: [durableEntry()] },
        readAt: "2026-08-22T06:00:00.000000Z",
      },
      [sessionEntry(journalEntryIntent(SCENE_ID, "session words"), 3)],
    );
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  });
});
