import { exactUtcInstantSchema } from "../contract/instant";

const pairingTokenPattern = /^[0-9a-f]{64}$/;
const opaqueCapabilityPattern = /^[A-Za-z0-9._~-]{32,512}$/;

export const OPERATIONAL_SESSION_SCOPES = [
  "cockpit_read",
  "operator_evidence_write",
  "presentation_evidence_write",
  "replay_read",
] as const;

export type OperationalSessionScope = typeof OPERATIONAL_SESSION_SCOPES[number];

export type PairingSessionDescriptor = {
  sessionId: string;
  expiresAt: string;
  scopes: readonly OperationalSessionScope[];
  authority: "read_only_no_execution";
};

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
      expiresAt: "9999-12-31T23:59:59.999999Z",
      scopes: OPERATIONAL_SESSION_SCOPES,
      authority: "read_only_no_execution",
    };
    this.#emit();
  }

  establish(capability: string, descriptor: PairingSessionDescriptor): void {
    if (!opaqueCapabilityPattern.test(capability)) {
      throw new Error("pairing capability must be bounded opaque ASCII without whitespace");
    }
    const parsedExpiry = exactUtcInstantSchema.parse(descriptor.expiresAt);
    if (Date.parse(parsedExpiry) <= Date.now()) throw new Error("pairing session is already expired");
    if (descriptor.sessionId.length < 1 || descriptor.sessionId.length > 512 || !/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/.test(descriptor.sessionId)) {
      throw new Error("pairing session ID must be a canonical ASCII identity");
    }
    if (descriptor.authority !== "read_only_no_execution") throw new Error("pairing session authority exceeds the Glass ceiling");
    if (descriptor.scopes.length !== OPERATIONAL_SESSION_SCOPES.length || descriptor.scopes.some((scope, index) => scope !== OPERATIONAL_SESSION_SCOPES[index])) {
      throw new Error("pairing session scopes do not match the fixed evidence-only V1 scope set");
    }
    this.#token = capability;
    this.#descriptor = { ...descriptor, expiresAt: parsedExpiry, scopes: OPERATIONAL_SESSION_SCOPES };
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
