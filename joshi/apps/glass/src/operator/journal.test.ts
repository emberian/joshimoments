import { describe, expect, it } from "vitest";

import { operatorCommandSchema } from "./contract";
import {
  JOURNAL_UI_LABEL,
  JOURNAL_UI_LABEL_VERSION,
  MAX_JOURNAL_ENTRY_LENGTH,
  journalEntryIntent,
  verbatimWords,
} from "./journal";

const WORDS = "SOLVE likely rips 0-60%; DREGG probably stays 300-500K because Dragon's Clutch is in release prep.";

describe("journal entry intent", () => {
  it("binds the words verbatim to the scene subject under the frozen label", () => {
    const intent = journalEntryIntent("scene-journal-test", `  ${WORDS}  `);
    expect(intent.commandKind).toBe("record_focus");
    expect(intent.subject).toEqual({ kind: "scene", key: "scene-journal-test" });
    expect(intent.label).toBe(JOURNAL_UI_LABEL);
    const payload = intent.payload as { context: { uiLabel: string; uiLabelVersion: string; note: string } };
    expect(payload.context.uiLabel).toBe(JOURNAL_UI_LABEL);
    expect(payload.context.uiLabelVersion).toBe(JOURNAL_UI_LABEL_VERSION);
    expect(payload.context.note).toBe(WORDS);
  });

  it("produces a command the frozen operator contract admits", () => {
    const intent = journalEntryIntent("scene-journal-test", WORDS);
    const command = operatorCommandSchema.parse({
      contract: "joshi.operator.command",
      schemaVersion: 1,
      commandId: "command-journal-test",
      idempotencyKey: "retry-journal-test",
      clientSessionId: "session-journal-test",
      clientCommandSeq: "1",
      scene: { sceneId: "scene-journal-test", viewDigest: `sha256:${"a".repeat(64)}` },
      issuedAt: "2026-08-22T04:05:06.000000Z",
      clientClock: { clockId: "clock-journal-test", monotonicNs: "1" },
      commandKind: intent.commandKind,
      subject: intent.subject,
      payload: intent.payload,
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    expect(command.commandKind).toBe("record_focus");
  });

  it("refuses blank words instead of storing a blank where words belong", () => {
    expect(() => journalEntryIntent("scene-journal-test", "   ")).toThrow(/no words/i);
  });

  it("refuses words beyond the frozen context bound", () => {
    expect(() => journalEntryIntent("scene-journal-test", "y".repeat(MAX_JOURNAL_ENTRY_LENGTH + 1)))
      .toThrow(/4000/);
  });
});

describe("verbatim words of an act", () => {
  const context = {
    uiLabel: "Capture",
    uiLabelVersion: "1",
    confidencePpm: null,
    urgency: null,
    whyNow: null,
    note: null,
  };

  it("returns note and whyNow exactly as stated, in stated order", () => {
    const stated = verbatimWords("record_focus", {
      context: { ...context, whyNow: "band is compressing", note: WORDS },
      dwellMilliseconds: null,
    });
    expect(stated).toEqual([
      { label: "Why now", words: "band is compressing" },
      { label: "Note", words: WORDS },
    ]);
  });

  it("surfaces kind-specific stated fields without summarizing them", () => {
    expect(verbatimWords("record_disposition", {
      context,
      disposition: "hold through release prep",
      provisional: true,
    })).toEqual([{ label: "Disposition (provisional)", words: "hold through release prep" }]);
    expect(verbatimWords("compensate_command", {
      context,
      compensatesCommandId: "command-prior",
      reason: "wrong coin was marked",
    })).toEqual([{ label: "Correction reason", words: "wrong coin was marked" }]);
  });

  it("returns nothing for an act that carried no words, so the surface can say so", () => {
    expect(verbatimWords("record_focus", { context, dwellMilliseconds: null })).toEqual([]);
  });
});
