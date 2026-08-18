import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

import { exactUtcInstantSchema } from "../contract/instant";

const pairingTokenPattern = /^[0-9a-f]{64}$/;
export const ordinaryPairingCodePattern = /^JOSHI-(?:[0-9A-HJKMNP-TV-Z]{4}-){7}[0-9A-HJKMNP-TV-Z]{4}$/;
const ordinaryCapabilityPattern = /^jpc1_[0-9a-f]{64}$/;
const canonicalEpochPattern = /^[1-9][0-9]*$/;
const canonicalOrdinalPattern = /^[1-9][0-9]*$/;
const originTagDomain = "joshi.pairing.origin.v1\0";

export const OPERATIONAL_SESSION_SCOPES = [
  "cockpit_read",
  "operator_evidence_write",
  "presentation_evidence_write",
  "replay_read",
] as const;

export type OperationalSessionScope = typeof OPERATIONAL_SESSION_SCOPES[number];

export type PairingSessionDescriptor = {
  sessionId: string;
  origin: string;
  epoch: string;
  expiresAt: string;
  scopes: readonly OperationalSessionScope[];
  authority: "read_only_no_execution";
};

export function canonicalPairingCode(value: string): string {
  const canonical = value.trim().toUpperCase();
  if (!ordinaryPairingCodePattern.test(canonical)) {
    throw new Error("pairing code must be the canonical 160-bit JOSHI grouped code");
  }
  return canonical;
}

export function isLoopbackHostname(value: string): boolean {
  if (value === "localhost" || value === "[::1]") return true;
  return /^127(?:\.[0-9]{1,3}){3}$/.test(value)
    && value.split(".").every((part) => Number(part) <= 255);
}

export function pairingOriginTag(origin: string): string {
  return bytesToHex(sha256(new TextEncoder().encode(originTagDomain + origin)));
}

export function canonicalPairingSessionId(origin: string, epoch: string, ordinal: string): string {
  if (!canonicalEpochPattern.test(epoch) || !canonicalOrdinalPattern.test(ordinal)) {
    throw new Error("pairing session identity coordinates must be canonical positive decimals");
  }
  return `pair-session-${pairingOriginTag(origin)}-${epoch}-${ordinal}`;
}

export function isCanonicalPairingSessionId(sessionId: string, origin: string, epoch: string): boolean {
  const prefix = `pair-session-${pairingOriginTag(origin)}-${epoch}-`;
  return sessionId.startsWith(prefix) && canonicalOrdinalPattern.test(sessionId.slice(prefix.length));
}

function exactLoopbackOrigin(value: string): string {
  const parsed = new URL(value);
  if (parsed.origin !== value || parsed.protocol !== "http:" || !isLoopbackHostname(parsed.hostname)) {
    throw new Error("pairing session origin must be the exact HTTP loopback page origin");
  }
  return parsed.origin;
}

export class PairingRequiredError extends Error {
  constructor(message = "Joshi client is not paired; no request was sent") {
    super(message);
  }
}

export class PairingSessionRejectedError extends Error {}

/**
 * A short-lived local capability holder. It intentionally has no serialization API and never
 * consults URL state, cookies, Web Storage, build-time environment, or ambient credentials.
 * A future explicit native/manual handoff may call `pair`; page reload clears the capability.
 */
export class MemoryOnlyPairingSession {
  #token: string | null = null;
  #descriptor: PairingSessionDescriptor | null = null;
  #listeners = new Set<() => void>();

  /** Legacy/manual handoff used by offline contract tests and the current core token seam. */
  pair(token: string): void {
    if (!pairingTokenPattern.test(token)) {
      throw new Error("pairing capability must be exactly 32 lowercase-hex bytes");
    }
    this.#token = token;
    this.#descriptor = {
      sessionId: "legacy-manual-handoff",
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "9999-12-31T23:59:59.999999Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    };
    this.#emit();
  }

  establish(capability: string, descriptor: PairingSessionDescriptor): void {
    if (!ordinaryCapabilityPattern.test(capability)) {
      throw new Error("ordinary pairing capability must use the exact domain-separated V1 form");
    }
    const origin = exactLoopbackOrigin(descriptor.origin);
    if (origin !== window.location.origin) throw new Error("pairing session origin does not match this exact page origin");
    if (!canonicalEpochPattern.test(descriptor.epoch)) throw new Error("pairing epoch must be a canonical positive decimal string");
    const parsedExpiry = exactUtcInstantSchema.parse(descriptor.expiresAt);
    if (Date.parse(parsedExpiry) <= Date.now()) throw new Error("pairing session is already expired");
    if (!isCanonicalPairingSessionId(descriptor.sessionId, origin, descriptor.epoch)) {
      throw new Error("pairing session ID must bind the exact origin and epoch");
    }
    if (descriptor.authority !== "read_only_no_execution") throw new Error("pairing session authority exceeds the Glass ceiling");
    if (descriptor.scopes.length === 0
      || descriptor.scopes.some((scope) => !OPERATIONAL_SESSION_SCOPES.includes(scope))
      || descriptor.scopes.some((scope, index) => index > 0 && descriptor.scopes[index - 1]! >= scope)) {
      throw new Error("pairing session scopes must be a nonempty sorted subset of the evidence-only V1 scope set");
    }
    this.#token = capability;
    this.#descriptor = { ...descriptor, origin, expiresAt: parsedExpiry, scopes: [...descriptor.scopes] };
    this.#emit();
  }

  clear(): void {
    this.#token = null;
    this.#descriptor = null;
    this.#emit();
  }

  paired(): boolean {
    if (this.#token === null || this.#descriptor === null) return false;
    if (Date.parse(this.#descriptor.expiresAt) <= Date.now()) {
      this.clear();
      return false;
    }
    return true;
  }

  descriptor(): PairingSessionDescriptor | null {
    return this.paired() && this.#descriptor ? structuredClone(this.#descriptor) : null;
  }

  requireScope(scope: OperationalSessionScope): void {
    if (!this.paired()) throw new PairingRequiredError();
    if (!this.#descriptor?.scopes.includes(scope)) {
      throw new PairingRequiredError(`Joshi session lacks ${scope}; no request was sent`);
    }
  }

  authorizationHeader(scope?: OperationalSessionScope): string {
    if (scope) this.requireScope(scope);
    else if (!this.paired()) throw new PairingRequiredError();
    if (this.#token === null) throw new PairingRequiredError();
    return this.#token;
  }

  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  #emit(): void {
    for (const listener of this.#listeners) listener();
  }
}

export const glassPairingSession = new MemoryOnlyPairingSession();
