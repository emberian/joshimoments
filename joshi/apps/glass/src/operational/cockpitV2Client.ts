import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import {
  glassPairingSession,
  isLoopbackHostname,
  MemoryOnlyPairingSession,
  PairingSessionRejectedError,
  type PairingSessionDescriptor,
} from "../security/pairing";
import { SameOriginOperationalClient } from "./client";
import {
  parseCockpitV2BrowserPresentationClaim,
  parseCockpitV2BrowserPresentationReceipt,
  parseCockpitV2Index,
  parseCockpitV2Open,
  type CockpitV2BrowserPresentationClaim,
  type CockpitV2BrowserPresentationReceipt,
  type CockpitV2Index,
  type CockpitV2IndexEntry,
  type CockpitV2Open,
} from "./cockpitV2";

const MAX_INDEX_BYTES = 256 * 1024;
const MAX_OPEN_BYTES = 4 * 1024 * 1024;
const MAX_PRESENTATION_RECEIPT_BYTES = 16 * 1024;

function exactLoopbackBase(origin: string): URL {
  const parsed = new URL(origin);
  const page = new URL(window.location.origin);
  if (parsed.origin !== page.origin || parsed.protocol !== "http:" || !isLoopbackHostname(parsed.hostname)
    || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("Cockpit V2 inspector requires the exact HTTP loopback page origin");
  }
  return parsed;
}

async function readBoundedUtf8(response: Response, maximum: number): Promise<string> {
  const declared = response.headers.get("Content-Length");
  if (declared !== null && Number(declared) > maximum) throw new Error("Cockpit V2 response exceeds its browser bound");
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > maximum) throw new Error("Cockpit V2 response exceeds its browser bound");
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function parseUntrusted(body: string): unknown {
  const duplicate = validateJsonWithoutDuplicateKeys(body, false);
  if (duplicate !== undefined) throw new Error(`invalid Cockpit V2 JSON: ${duplicate}`);
  return JSON.parse(body, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") throw new Error(`forbidden Cockpit V2 JSON key: ${key}`);
    return value;
  }) as unknown;
}

export interface CockpitV2InspectorTransport {
  exchange(code: string, signal?: AbortSignal): Promise<PairingSessionDescriptor>;
  list(signal?: AbortSignal): Promise<CockpitV2Index>;
  open(entry: CockpitV2IndexEntry, signal?: AbortSignal): Promise<CockpitV2Open>;
  present(
    claim: CockpitV2BrowserPresentationClaim,
    signal?: AbortSignal,
  ): Promise<CockpitV2BrowserPresentationReceipt>;
}

export class SameOriginCockpitV2InspectorClient implements CockpitV2InspectorTransport {
  private readonly base: URL;
  private readonly session: MemoryOnlyPairingSession;
  private readonly pairing: SameOriginOperationalClient;

  constructor(session: MemoryOnlyPairingSession = glassPairingSession, origin: string = window.location.origin) {
    this.base = exactLoopbackBase(origin);
    this.session = session;
    this.pairing = new SameOriginOperationalClient(session, origin);
  }

  async exchange(code: string, signal?: AbortSignal): Promise<PairingSessionDescriptor> {
    return this.pairing.exchange(code, signal);
  }

  async list(signal?: AbortSignal): Promise<CockpitV2Index> {
    const body = await this.get("/api/v1/cockpit-v2/publications", MAX_INDEX_BYTES, signal);
    return parseCockpitV2Index(parseUntrusted(body));
  }

  async open(entry: CockpitV2IndexEntry, signal?: AbortSignal): Promise<CockpitV2Open> {
    const body = await this.get(`/api/v1/cockpit-v2/publications/${encodeURIComponent(entry.publicationId)}`, MAX_OPEN_BYTES, signal);
    return parseCockpitV2Open(parseUntrusted(body), entry);
  }

  async present(
    claimInput: CockpitV2BrowserPresentationClaim,
    signal?: AbortSignal,
  ): Promise<CockpitV2BrowserPresentationReceipt> {
    const claim = parseCockpitV2BrowserPresentationClaim(claimInput);
    const descriptor = this.session.descriptor();
    if (!descriptor) throw new PairingSessionRejectedError("Local session is absent or expired; pair again.");
    let response: Response;
    try {
      response = await fetch(new URL("/api/v1/cockpit-v2/presentations", this.base), {
        method: "POST",
        ...(signal ? { signal } : {}),
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Joshi-Pairing-Token": this.session.authorizationHeader("presentation_evidence_write"),
        },
        body: JSON.stringify(claim),
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new Error(cause instanceof Error ? cause.message : "Cockpit V2 presentation transport failed");
    }
    if (response.status === 401 || response.status === 403) {
      this.session.clear();
      throw new PairingSessionRejectedError("Local session expired, was revoked, or lacks presentation evidence scope; pair again.");
    }
    if (response.status === 409) throw new Error("Cockpit V2 presentation identity conflicts with prior exact bytes");
    if (!response.ok) throw new Error(`Cockpit V2 presentation receipt failed (${response.status})`);
    const body = await readBoundedUtf8(response, MAX_PRESENTATION_RECEIPT_BYTES);
    return parseCockpitV2BrowserPresentationReceipt(
      parseUntrusted(body),
      claim,
      descriptor.sessionId,
    );
  }

  private async get(path: string, maximum: number, signal?: AbortSignal): Promise<string> {
    let response: Response;
    try {
      response = await fetch(new URL(path, this.base), {
        ...(signal ? { signal } : {}),
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "X-Joshi-Pairing-Token": this.session.authorizationHeader("cockpit_read"),
        },
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new Error(cause instanceof Error ? cause.message : "Cockpit V2 inspection transport failed");
    }
    if (response.status === 401 || response.status === 403) {
      this.session.clear();
      throw new PairingSessionRejectedError("Local session expired, was revoked, or lacks Cockpit read scope; pair again.");
    }
    if (!response.ok) throw new Error(`Cockpit V2 inspection failed (${response.status})`);
    return readBoundedUtf8(response, maximum);
  }
}
