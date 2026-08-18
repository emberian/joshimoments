import { describe, expect, it, vi } from "vitest";

import {
  MemoryOnlyPairingSession,
  OPERATIONAL_SESSION_SCOPES,
  canonicalPairingSessionId,
  pairingOriginTag,
} from "./pairing";

const sessionId = (origin = window.location.origin, epoch = "1") => canonicalPairingSessionId(origin, epoch, "1");

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
    expect(JSON.stringify(session)).not.toContain("b".repeat(64));
    expect(new MemoryOnlyPairingSession().paired()).toBe(false);
  });

  it("keeps a fixed evidence-only scope set and clears an expired opaque session", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-17T12:00:00.000Z"));
    const session = new MemoryOnlyPairingSession();
    session.establish("jpc1_" + "a".repeat(64), {
      sessionId: sessionId(),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2026-08-17T12:01:00.000000Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    });
    expect(session.descriptor()?.scopes).toEqual(OPERATIONAL_SESSION_SCOPES);
    expect(session.authorizationHeader("presentation_evidence_write")).toMatch(/^jpc1_/);
    vi.setSystemTime(new Date("2026-08-17T12:01:01.000Z"));
    expect(session.paired()).toBe(false);
    expect(() => session.authorizationHeader()).toThrow(/not paired/i);
    vi.useRealTimers();
  });

  it("rejects caller-expanded scopes and capability whitespace", () => {
    const session = new MemoryOnlyPairingSession();
    expect(() => session.establish("opaque capability with whitespace", {
      sessionId: sessionId(),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    })).toThrow(/domain-separated V1/i);
    expect(() => session.establish("jpc1_" + "a".repeat(64), {
      sessionId: sessionId(),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["cockpit_read"] as never,
      authority: "read_only_no_execution",
    })).not.toThrow();
    expect(() => session.establish("jpc1_" + "b".repeat(64), {
      sessionId: sessionId(),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["replay_read", "cockpit_read"],
      authority: "read_only_no_execution",
    })).toThrow(/sorted subset/i);
  });

  it("binds the capability to the exact loopback origin and canonical epoch", () => {
    const session = new MemoryOnlyPairingSession();
    expect(() => session.establish("jpc1_" + "c".repeat(64), {
      sessionId: sessionId("http://127.0.0.1:8787"),
      origin: "http://127.0.0.1:8787",
      epoch: "1",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["cockpit_read"],
      authority: "read_only_no_execution",
    })).toThrow(/exact page origin/i);
    expect(() => session.establish("jpc1_" + "c".repeat(64), {
      sessionId: sessionId(),
      origin: window.location.origin,
      epoch: "01",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["cockpit_read"],
      authority: "read_only_no_execution",
    })).toThrow(/epoch/i);
  });

  it("matches the exact Rust origin-tag vector and rejects session identity substitution", () => {
    expect(pairingOriginTag("http://127.0.0.1:8787")).toBe(
      "57d735b9c189b41426a4e6c40b217edda92f19d354a230542126af9e8182f9da",
    );
    const session = new MemoryOnlyPairingSession();
    expect(() => session.establish("jpc1_" + "d".repeat(64), {
      sessionId: canonicalPairingSessionId(window.location.origin, "2", "1"),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-17T12:01:00.000000Z",
      scopes: ["cockpit_read"],
      authority: "read_only_no_execution",
    })).toThrow(/bind the exact origin and epoch/i);
  });
});
