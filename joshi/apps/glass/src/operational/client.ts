import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import type { GlassSnapshotV1 } from "../contract/v1";
import type { GlassDataSource, SnapshotRequest } from "../data/client";
import type { ExplorationBundleV1, PresentationPolicyV1 } from "../presentation/contract";
import {
  MemoryOnlyPairingSession,
  PairingSessionRejectedError,
  canonicalPairingCode,
  isLoopbackHostname,
  type OperationalSessionScope,
} from "../security/pairing";
import {
  cockpitPublicationIndexV1Schema,
  assertExplicitAbstentionReceipt,
  assertProspectiveNominationReceipt,
  canonicalExplicitAbstention,
  canonicalProspectiveNomination,
  explicitAbstentionCommandV1Schema,
  explicitAbstentionReceiptV1Schema,
  prospectiveNominationCommandV1Schema,
  prospectiveNominationReceiptV1Schema,
  pairingExchangeV1Schema,
  pairingSessionV1Schema,
  parseCockpitLaunchEnvelope,
  sessionLaunchV1Schema,
  type CockpitLaunchEnvelopeV1,
  type CockpitPublicationIndexV1,
  type PairingSessionV1,
  type ExplicitAbstentionCommandV1,
  type ExplicitAbstentionReceiptV1,
  type ProspectiveNominationCommandV1,
  type ProspectiveNominationReceiptV1,
  type SessionLaunchV1,
} from "./contract";

export const MAX_PAIRING_BYTES = 4 * 1024;
export const MAX_PUBLICATION_INDEX_BYTES = 256 * 1024;
export const MAX_PUBLICATION_BYTES = 8 * 1024 * 1024;
export const MAX_OPERATIONAL_COMMAND_BYTES = 64 * 1024;
export const MAX_OPERATIONAL_RECEIPT_BYTES = 64 * 1024;

type StrictParser<T> = { parse(input: unknown): T };

function exactSameOriginBase(origin: string): URL {
  const parsed = new URL(origin);
  const current = new URL(window.location.origin);
  if (parsed.origin !== current.origin) throw new Error("operational Glass requires the exact page origin");
  if (parsed.protocol !== "http:" || !isLoopbackHostname(parsed.hostname)) {
    throw new Error("operational Glass must be served from an HTTP loopback origin");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("operational Glass origin cannot contain credentials, query state, or fragments");
  }
  return parsed;
}

async function readBoundedUtf8(response: Response, maximum: number, label: string): Promise<string> {
  const declared = response.headers.get("Content-Length");
  if (declared !== null && Number(declared) > maximum) throw new Error(`${label} exceeds the browser response bound`);
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > maximum) throw new Error(`${label} exceeds the browser response bound`);
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maximum) {
      await reader.cancel(`${label} response bound exceeded`);
      throw new Error(`${label} exceeds the browser response bound`);
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

function parseUntrusted<T>(body: string, parser: StrictParser<T>, label: string): T {
  const wireError = validateJsonWithoutDuplicateKeys(body, false);
  if (wireError !== undefined) throw new Error(`invalid ${label} JSON: ${wireError}`);
  const decoded = JSON.parse(body, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") throw new Error(`forbidden ${label} JSON key: ${key}`);
    return value;
  }) as unknown;
  return parser.parse(decoded);
}

export class SameOriginOperationalClient {
  readonly kind = "loopback" as const;
  private readonly base: URL;
  private readonly session: MemoryOnlyPairingSession;

  constructor(session: MemoryOnlyPairingSession, origin: string = window.location.origin) {
    this.base = exactSameOriginBase(origin);
    this.session = session;
  }

  async exchange(oneTimeCode: string, signal?: AbortSignal): Promise<Omit<PairingSessionV1, "capability">> {
    const request = pairingExchangeV1Schema.parse({
      contract: "joshi.pairing.exchange",
      schemaVersion: 1,
      oneTimeCode: canonicalPairingCode(oneTimeCode),
    });
    const body = JSON.stringify(request);
    if (new TextEncoder().encode(body).byteLength > MAX_PAIRING_BYTES) throw new Error("pairing exchange exceeds the browser request bound");
    const response = await fetch(new URL("/api/v1/pairing/exchange", this.base), {
      method: "POST",
      ...(signal ? { signal } : {}),
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body,
    });
    if (!response.ok) throw new Error(response.status === 401 || response.status === 410 ? "Pairing code is invalid, expired, or already consumed." : `pairing exchange failed (${response.status})`);
    const paired = parseUntrusted(await readBoundedUtf8(response, MAX_PAIRING_BYTES, "pairing response"), pairingSessionV1Schema, "pairing response");
    this.session.establish(paired.capability, paired);
    const { capability: _capability, ...publicDescriptor } = paired;
    return publicDescriptor;
  }

  async listPublications(signal?: AbortSignal): Promise<CockpitPublicationIndexV1> {
    const body = await this.get("/api/v1/cockpit/publications", "cockpit_read", MAX_PUBLICATION_INDEX_BYTES, signal);
    return parseUntrusted(body, cockpitPublicationIndexV1Schema, "cockpit publication index");
  }

  async openPublication(cockpitPublicationId: string, signal?: AbortSignal): Promise<CockpitLaunchEnvelopeV1> {
    const safeId = encodeURIComponent(cockpitPublicationId);
    const body = await this.get(`/api/v1/cockpit/publications/${safeId}`, "cockpit_read", MAX_PUBLICATION_BYTES, signal);
    const envelope = parseCockpitLaunchEnvelope(parseUntrusted(body, { parse: (value) => value }, "cockpit launch"));
    if (envelope.launch.snapshot.transport !== "loopback") throw new Error("production cockpit launch must carry a loopback snapshot");
    return envelope;
  }

  async loadSessionLaunch(signal?: AbortSignal): Promise<SessionLaunchV1> {
    const body = await this.get("/api/v1/session/launch", "cockpit_read", MAX_OPERATIONAL_RECEIPT_BYTES, signal);
    const launch = parseUntrusted(body, sessionLaunchV1Schema, "bound prospective session launch");
    if (JSON.stringify(launch) !== body) {
      throw new Error("bound prospective session launch is not the exact canonical V1 envelope");
    }
    return launch;
  }

  async appendAbstention(commandInput: ExplicitAbstentionCommandV1, signal?: AbortSignal): Promise<ExplicitAbstentionReceiptV1> {
    const command = explicitAbstentionCommandV1Schema.parse(commandInput);
    const body = canonicalExplicitAbstention(command);
    if (new TextEncoder().encode(body).byteLength > MAX_OPERATIONAL_COMMAND_BYTES) throw new Error("explicit abstention exceeds the browser request bound");
    let response: Response;
    try {
      response = await fetch(new URL("/api/v1/operator/abstentions", this.base), {
        method: "POST",
        ...(signal ? { signal } : {}),
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Joshi-Pairing-Token": this.session.authorizationHeader("operator_evidence_write"),
        },
        body,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new Error(error instanceof Error ? error.message : "explicit abstention transport failed");
    }
    if (response.status === 401 || response.status === 403) {
      this.session.clear();
      throw new PairingSessionRejectedError("Local session expired or was revoked; pair again.");
    }
    if (!response.ok) throw new Error(`explicit abstention append failed (${response.status})`);
    const receipt = parseUntrusted(
      await readBoundedUtf8(response, MAX_OPERATIONAL_RECEIPT_BYTES, "explicit abstention receipt"),
      explicitAbstentionReceiptV1Schema,
      "explicit abstention receipt",
    );
    assertExplicitAbstentionReceipt(command, receipt);
    return receipt;
  }

  async appendProspectiveNomination(commandInput: ProspectiveNominationCommandV1, signal?: AbortSignal): Promise<ProspectiveNominationReceiptV1> {
    const command = prospectiveNominationCommandV1Schema.parse(commandInput);
    const body = canonicalProspectiveNomination(command);
    if (new TextEncoder().encode(body).byteLength > MAX_OPERATIONAL_COMMAND_BYTES) throw new Error("prospective nomination exceeds the browser request bound");
    let response: Response;
    try {
      response = await fetch(new URL("/api/v1/operator/prospective-nominations", this.base), {
        method: "POST",
        ...(signal ? { signal } : {}),
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Joshi-Pairing-Token": this.session.authorizationHeader("operator_evidence_write"),
        },
        body,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new Error(error instanceof Error ? error.message : "prospective nomination transport failed");
    }
    if (response.status === 401 || response.status === 403) {
      this.session.clear();
      throw new PairingSessionRejectedError("Local session expired or was revoked; pair again.");
    }
    if (!response.ok) throw new Error(`prospective nomination append failed (${response.status})`);
    const receipt = parseUntrusted(
      await readBoundedUtf8(response, MAX_OPERATIONAL_RECEIPT_BYTES, "prospective nomination receipt"),
      prospectiveNominationReceiptV1Schema,
      "prospective nomination receipt",
    );
    assertProspectiveNominationReceipt(command, receipt);
    return receipt;
  }

  private async get(path: string, scope: OperationalSessionScope, maximum: number, signal?: AbortSignal): Promise<string> {
    let response: Response;
    try {
      response = await fetch(new URL(path, this.base), {
        ...(signal ? { signal } : {}),
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "X-Joshi-Pairing-Token": this.session.authorizationHeader(scope),
        },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new Error(error instanceof Error ? error.message : "same-origin operational read failed");
    }
    if (response.status === 401 || response.status === 403) {
      this.session.clear();
      throw new PairingSessionRejectedError("Local session expired or was revoked; pair again.");
    }
    if (!response.ok) throw new Error(`operational read failed (${response.status})`);
    return readBoundedUtf8(response, maximum, "operational response");
  }
}

export type OperationalPresentationMaterials = {
  policy: PresentationPolicyV1;
  bundle: ExplorationBundleV1;
  publication: { cockpitPublicationId: string; cockpitPublicationDigest: string };
};

export interface CockpitPublicationOpener {
  openPublication(cockpitPublicationId: string, signal?: AbortSignal): Promise<CockpitLaunchEnvelopeV1>;
}

export class CockpitPublicationDataSource implements GlassDataSource {
  readonly kind = "loopback" as const;
  private current: CockpitLaunchEnvelopeV1;
  private readonly client: CockpitPublicationOpener;
  private readonly bySnapshotDigest = new Map<string, CockpitLaunchEnvelopeV1>();

  constructor(client: CockpitPublicationOpener, publication: CockpitLaunchEnvelopeV1) {
    this.client = client;
    this.current = publication;
    this.bySnapshotDigest.set(publication.launch.snapshot.snapshotDigest, publication);
  }

  async loadSnapshot(request: SnapshotRequest): Promise<GlassSnapshotV1> {
    if (this.current.launch.snapshot.view.mode === request.mode) return this.current.launch.snapshot;
    const reference = this.current.launch.replayCockpitPublications.find((candidate) => candidate.mode === request.mode);
    if (!reference) throw new Error(`This immutable publication has no admitted ${request.mode.replaceAll("_", " ")} replay publication.`);
    const opened = await this.client.openPublication(reference.cockpitPublicationId, request.signal);
    if (opened.launch.cockpitPublication.cockpitPublicationDigest !== reference.cockpitPublicationDigest
      || opened.launch.snapshot.view.sceneId !== reference.scene.sceneId
      || opened.launch.snapshot.snapshotDigest !== reference.scene.viewDigest
      || opened.launch.snapshot.view.mode !== reference.mode) {
      throw new Error("Replay publication does not close to the selected immutable reference.");
    }
    this.current = opened;
    this.bySnapshotDigest.set(opened.launch.snapshot.snapshotDigest, opened);
    return opened.launch.snapshot;
  }

  presentationMaterials(snapshot: GlassSnapshotV1): OperationalPresentationMaterials | null {
    const envelope = this.bySnapshotDigest.get(snapshot.snapshotDigest);
    if (!envelope) return null;
    return {
      policy: envelope.launch.presentationPolicy,
      bundle: envelope.launch.explorationBundle,
      publication: {
        cockpitPublicationId: envelope.launch.cockpitPublication.cockpitPublicationId,
        cockpitPublicationDigest: envelope.launch.cockpitPublication.cockpitPublicationDigest,
      },
    };
  }
}
