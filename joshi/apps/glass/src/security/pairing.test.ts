import { describe, expect, it, vi } from "vitest";

import { MemoryOnlyPairingSession, OPERATIONAL_SESSION_SCOPES } from "./pairing";

describe("memory-only local pairing capability", () => {
  it("accepts only the exact core token shape and clears on request", () => {
    const session = new MemoryOnlyPairingSession();
    expect(() => session.authorizationHeader()).toThrow(/not paired/i);
    expect(() => session.pair("A".repeat(64))).toThrow(/lowercase-hex/i);
    expect(() => session.pair("a".repeat(63))).toThrow(/32 lowercase-hex bytes/i);
    session.pair("0123456789abcdef".repeat(4));
    expect(session.paired()).toBe(true);
    expect(session.authorizationHeader()).toBe("0123456789abcdef".repeat(4));
    session.clear();
    expect(session.paired()).toBe(false);
  });

  it("never reads or writes browser persistence", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem");
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const session = new MemoryOnlyPairingSession();
    session.pair("b".repeat(64));
    expect(session.authorizationHeader()).toBe("b".repeat(64));
    session.clear();
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });

  it("keeps a fixed evidence-only scope set and clears an expired opaque session", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T12:00:00.000Z"));
    const session = new MemoryOnlyPairingSession();
    session.establish("opaque_" + "a".repeat(58), {
      sessionId: "session-expiring-1",
      expiresAt: "2026-08-17T12:01:00.000000Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    });
    expect(session.descriptor()?.scopes).toEqual(OPERATIONAL_SESSION_SCOPES);
    expect(session.authorizationHeader("presentation_evidence_write")).toMatch(/^opaque_/);
    vi.setSystemTime(new Date("2026-08-17T12:01:01.000Z"));
    expect(session.paired()).toBe(false);
    expect(() => session.authorizationHeader()).toThrow(/not paired/i);
    vi.useRealTimers();
  });

  it("rejects caller-expanded scopes and capability whitespace", () => {
    const session = new MemoryOnlyPairingSession();
    expect(() => session.establish("opaque capability with whitespace", {
      sessionId: "session-invalid",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    })).toThrow(/opaque ASCII/i);
    expect(() => session.establish("a".repeat(64), {
      sessionId: "session-invalid",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["cockpit_read"] as never,
      authority: "read_only_no_execution",
    })).toThrow(/fixed evidence-only/i);
  });
});
