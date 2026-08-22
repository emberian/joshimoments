import { describe, expect, it } from "vitest";

import { operatorCommandSchema, type CommandReceipt, type OperatorCommand } from "./contract";
import {
  heldSubjectKeys,
  holdIntent,
  holdNoteIntent,
  holdRetention,
  isHoldCommand,
  isHoldNoteCommand,
  MAX_HOLD_NOTE_LENGTH,
} from "./holds";
import type { JournalEntry, OperatorIntent } from "./useOperatorJournal";

function command(intent: OperatorIntent, ordinal: number): OperatorCommand {
  return operatorCommandSchema.parse({
    contract: "joshi.operator.command",
    schemaVersion: 1,
    commandId: `command-${ordinal}`,
    idempotencyKey: `retry-${ordinal}`,
    clientSessionId: "glass-session-test",
    clientCommandSeq: String(ordinal),
    scene: { sceneId: "scene-hold-test", viewDigest: `sha256:${"a".repeat(64)}` },
    issuedAt: "2026-08-21T23:11:04.000000Z",
    clientClock: { clockId: "browser-clock-test", monotonicNs: String(ordinal) },
    commandKind: intent.commandKind,
    subject: intent.subject,
    payload: intent.payload,
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}

function entry(
  intent: OperatorIntent,
  ordinal: number,
  status: JournalEntry["status"] = "committed",
  receipt: CommandReceipt | null = null,
  error: string | null = null,
): JournalEntry {
  return {
    command: command(intent, ordinal),
    label: intent.label,
    status,
    receipt,
    error,
    pendingEnqueuedAt: "2026-08-21T23:11:04.000000Z",
    pendingRepairRequiredAt: "2026-08-28T23:11:04.000000Z",
  };
}

function receipt(commitSeq: string): CommandReceipt {
  return {
    contract: "joshi.store.command_receipt",
    schemaVersion: 1,
    catalogId: "joshi-live-surface-overlay",
    catalogSchema: "joshi.sqlite.v24",
    batchId: "operator:command-1",
    commandId: "command-1",
    commandPayloadDigest: `sha256:${"b".repeat(64)}`,
    commandDigest: `sha256:${"c".repeat(64)}`,
    scene: { sceneId: "scene-hold-test", viewDigest: `sha256:${"a".repeat(64)}` },
    commitSeq,
    status: "accepted",
  };
}

describe("holds", () => {
  it("keeps held coins in the order she held them, however the feed later re-ranks", () => {
    const entries = [
      entry(holdIntent("fable"), 1),
      entry(holdIntent("moss"), 2),
      entry(holdNoteIntent("fable", "same wick as yesterday"), 3),
      entry(holdIntent("fable"), 4),
      entry(holdIntent("copper"), 5),
    ];
    expect(heldSubjectKeys(entries)).toEqual(["fable", "moss", "copper"]);
  });

  it("separates a hold from a note about a hold", () => {
    const hold = command(holdIntent("fable"), 1);
    const note = command(holdNoteIntent("fable", "same wick as yesterday"), 2);
    expect(isHoldCommand(hold)).toBe(true);
    expect(isHoldNoteCommand(hold)).toBe(false);
    expect(isHoldCommand(note)).toBe(false);
    expect(isHoldNoteCommand(note)).toBe(true);
  });

  it("asks her for nothing at the moment of noticing", () => {
    const hold = command(holdIntent("fable"), 1);
    if (hold.commandKind !== "record_focus") throw new Error("a hold is a record_focus act");
    expect(hold.payload).toEqual({
      context: {
        uiLabel: "Hold coin",
        uiLabelVersion: "1",
        confidencePpm: null,
        urgency: null,
        whyNow: null,
        note: null,
      },
      dwellMilliseconds: null,
    });
  });

  it("refuses to record a note with no words in it", () => {
    expect(() => holdNoteIntent("fable", "   ")).toThrow(/no words/i);
    expect(() => holdNoteIntent("fable", "x".repeat(MAX_HOLD_NOTE_LENGTH + 1))).toThrow(/limited/i);
    expect(holdNoteIntent("fable", "  it moved  ").payload).toMatchObject({
      context: { note: "it moved" },
    });
  });

  it("calls a mark retained only when the catalog has answered with a commit", () => {
    expect(holdRetention([])).toEqual({ state: "retaining_local" });
    expect(holdRetention([entry(holdIntent("fable"), 1, "submitting")])).toEqual({ state: "submitting" });
    expect(holdRetention([entry(holdIntent("fable"), 1, "queued", null, "Offline.")]))
      .toEqual({ state: "queued", reason: "Offline." });
    expect(holdRetention([entry(holdIntent("fable"), 1, "rejected", null, "Refused.")]))
      .toEqual({ state: "rejected", reason: "Refused." });
    // A committed status with no receipt is not a commit. It never names a sequence, so it is
    // never reported as retained.
    expect(holdRetention([entry(holdIntent("fable"), 1, "committed", null)]))
      .toEqual({ state: "retaining_local" });
    expect(holdRetention([
      entry(holdIntent("fable"), 1, "committed", receipt("7")),
      entry(holdIntent("fable"), 2, "queued", null, "A later duplicate is still in flight."),
    ])).toEqual({ state: "committed", commitSeq: "7" });
  });
});
