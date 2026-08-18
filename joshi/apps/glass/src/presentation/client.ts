import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import {
  assertEventReceipt,
  assertSceneReceipt,
  canonicalPresentationEvent,
  canonicalPresentationSceneAdmission,
  digestExplorationBundle,
  digestPresentationEvent,
  digestPresentationPolicy,
  digestPresentationScene,
  presentationEventReceiptV1Schema,
  presentationEventV1Schema,
  presentationSceneReceiptV1Schema,
  presentationSceneV1Schema,
  type ExplorationBundleV1,
  type PresentationEventReceiptV1,
  type PresentationEventV1,
  type PresentationPolicyV1,
  type PresentationSceneReceiptV1,
  type PresentationSceneV1,
} from "./contract";
import { glassPairingSession, PairingSessionRejectedError, type MemoryOnlyPairingSession } from "../security/pairing";

export const MAX_PRESENTATION_REQUEST_BYTES = 128 * 1024;
export const MAX_PRESENTATION_RECEIPT_BYTES = 64 * 1024;

export class RetryablePresentationError extends Error {
  readonly retryable = true;
}

export interface PresentationSink {
  readonly kind: "offline_fixture" | "loopback";
  appendScene(
    scene: PresentationSceneV1,
    policy: PresentationPolicyV1,
    bundle: ExplorationBundleV1,
    signal?: AbortSignal,
  ): Promise<PresentationSceneReceiptV1>;
  appendEvent(event: PresentationEventV1, signal?: AbortSignal): Promise<PresentationEventReceiptV1>;
}

function bounded(body: string): void {
  if (new TextEncoder().encode(body).byteLength > MAX_PRESENTATION_REQUEST_BYTES) {
    throw new Error("presentation request exceeds the browser request bound");
  }
}

async function readBoundedUtf8(response: Response): Promise<string> {
  const declaredLength = response.headers.get("Content-Length");
  if (declaredLength !== null && Number(declaredLength) > MAX_PRESENTATION_RECEIPT_BYTES) {
    throw new Error("presentation receipt exceeds the browser response bound");
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_PRESENTATION_RECEIPT_BYTES) throw new Error("presentation receipt exceeds the browser response bound");
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_PRESENTATION_RECEIPT_BYTES) {
      await reader.cancel("presentation receipt response bound exceeded");
      throw new Error("presentation receipt exceeds the browser response bound");
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

function parseUntrusted<T>(body: string, parser: { parse(input: unknown): T }): T {
  const wireError = validateJsonWithoutDuplicateKeys(body, false);
  if (wireError !== undefined) throw new Error(`invalid presentation receipt JSON: ${wireError}`);
  const decoded = JSON.parse(body, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") {
      throw new Error(`forbidden presentation receipt JSON key: ${key}`);
    }
    return value;
  }) as unknown;
  return parser.parse(decoded);
}

export class OfflineFixturePresentationSink implements PresentationSink {
  readonly kind = "offline_fixture" as const;
  readonly sceneAttemptBodies: string[] = [];
  readonly eventAttemptBodies: string[] = [];
  private nextCommit = 8_001n;
  private readonly scenesByIdempotency = new Map<string, { digest: string; receipt: PresentationSceneReceiptV1 }>();
  private readonly sceneDigests = new Map<string, string>();
  private readonly eventsByIdempotency = new Map<string, { digest: string; receipt: PresentationEventReceiptV1 }>();
  private readonly eventDigests = new Map<string, string>();

  async appendScene(
    sceneInput: PresentationSceneV1,
    policy: PresentationPolicyV1,
    bundle: ExplorationBundleV1,
    signal?: AbortSignal,
  ): Promise<PresentationSceneReceiptV1> {
    if (signal?.aborted) throw new DOMException("Presentation scene append aborted", "AbortError");
    const scene = presentationSceneV1Schema.parse(sceneInput);
    const body = canonicalPresentationSceneAdmission({
      contract: "joshi.presentation.scene_admission",
      schemaVersion: 1,
      policy,
      explorationBundle: bundle,
      scene,
    });
    bounded(body);
    this.sceneAttemptBodies.push(body);
    if (scene.policy.policyId !== policy.policyId || scene.policy.policyVersion !== policy.policyVersion || scene.policy.policyDigest !== digestPresentationPolicy(policy)) {
      throw new Error("presentation scene policy reference is not closed by exact policy bytes");
    }
    const bundleReference = scene.artifacts.find((artifact) => artifact.contract === bundle.contract && artifact.artifactId === bundle.bundleId);
    if (!bundleReference || bundleReference.artifactDigest !== digestExplorationBundle(bundle)) {
      throw new Error("presentation scene exploration reference is not closed by exact bundle bytes");
    }
    if (bundle.scene.sceneId !== scene.scene.sceneId || bundle.scene.viewDigest !== scene.scene.viewDigest) {
      throw new Error("presentation exploration bundle evidence cut mismatch");
    }

    const presentationDigest = digestPresentationScene(scene);
    const existingIdempotency = this.scenesByIdempotency.get(scene.idempotencyKey);
    if (existingIdempotency) {
      if (existingIdempotency.digest !== presentationDigest) throw new Error("presentation scene idempotency conflict: body changed");
      const receipt = { ...existingIdempotency.receipt, status: "idempotent" as const };
      assertSceneReceipt(receipt, scene);
      return structuredClone(receipt);
    }
    const existingDigest = this.sceneDigests.get(scene.presentationId);
    if (existingDigest && existingDigest !== presentationDigest) throw new Error("presentation scene identity conflict: body changed");

    const receipt = presentationSceneReceiptV1Schema.parse({
      contract: "joshi.store.presentation_scene_receipt",
      schemaVersion: 1,
      catalogId: "offline-fixture-catalog",
      catalogSchema: "joshi.catalog.v1",
      batchId: `presentation-batch:${scene.presentationId}`,
      presentationId: scene.presentationId,
      idempotencyKey: scene.idempotencyKey,
      assignmentId: scene.policy.assignmentId,
      scene: scene.scene,
      policyDigest: scene.policy.policyDigest,
      presentationDigest,
      commitSeq: this.nextCommit.toString(),
      status: "accepted",
    });
    this.nextCommit += 1n;
    this.scenesByIdempotency.set(scene.idempotencyKey, { digest: presentationDigest, receipt });
    this.sceneDigests.set(scene.presentationId, presentationDigest);
    assertSceneReceipt(receipt, scene);
    return structuredClone(receipt);
  }

  async appendEvent(eventInput: PresentationEventV1, signal?: AbortSignal): Promise<PresentationEventReceiptV1> {
    if (signal?.aborted) throw new DOMException("Presentation event append aborted", "AbortError");
    const event = presentationEventV1Schema.parse(eventInput);
    const body = canonicalPresentationEvent(event);
    bounded(body);
    this.eventAttemptBodies.push(body);
    if (this.sceneDigests.get(event.presentation.presentationId) !== event.presentation.presentationDigest) {
      throw new Error("presentation event references an uncommitted or mismatched presentation scene");
    }
    const eventDigest = digestPresentationEvent(event);
    const existingIdempotency = this.eventsByIdempotency.get(event.idempotencyKey);
    if (existingIdempotency) {
      if (existingIdempotency.digest !== eventDigest) throw new Error("presentation event idempotency conflict: body changed");
      const receipt = { ...existingIdempotency.receipt, status: "idempotent" as const };
      assertEventReceipt(receipt, event);
      return structuredClone(receipt);
    }
    const existingDigest = this.eventDigests.get(event.eventId);
    if (existingDigest && existingDigest !== eventDigest) throw new Error("presentation event identity conflict: body changed");

    const receipt = presentationEventReceiptV1Schema.parse({
      contract: "joshi.store.presentation_event_receipt",
      schemaVersion: 1,
      catalogId: "offline-fixture-catalog",
      catalogSchema: "joshi.catalog.v1",
      batchId: `presentation-event-batch:${event.eventId}`,
      eventId: event.eventId,
      presentation: event.presentation,
      scene: event.scene,
      eventDigest,
      commitSeq: this.nextCommit.toString(),
      status: "accepted",
    });
    this.nextCommit += 1n;
    this.eventsByIdempotency.set(event.idempotencyKey, { digest: eventDigest, receipt });
    this.eventDigests.set(event.eventId, eventDigest);
    assertEventReceipt(receipt, event);
    return structuredClone(receipt);
  }
}

export class LoopbackPresentationSink implements PresentationSink {
  readonly kind = "loopback" as const;
  private readonly baseUrl: URL;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(baseUrl: string, pairingSession: MemoryOnlyPairingSession = glassPairingSession, requireSameOrigin = false) {
    const parsed = new URL(baseUrl);
    if (parsed.protocol !== "http:" || !new Set(["127.0.0.1", "localhost", "[::1]"]).has(parsed.hostname)) {
      throw new Error("presentation core URL must be an explicit HTTP loopback address");
    }
    if (requireSameOrigin && parsed.origin !== window.location.origin) {
      throw new Error("operational presentation transport must use the exact page origin");
    }
    this.baseUrl = parsed;
    this.pairingSession = pairingSession;
  }

  async appendScene(
    sceneInput: PresentationSceneV1,
    policy: PresentationPolicyV1,
    bundle: ExplorationBundleV1,
    signal?: AbortSignal,
  ): Promise<PresentationSceneReceiptV1> {
    const scene = presentationSceneV1Schema.parse(sceneInput);
    if (scene.policy.policyDigest !== digestPresentationPolicy(policy)) throw new Error("presentation policy digest mismatch before send");
    const artifact = scene.artifacts.find((value) => value.artifactId === bundle.bundleId);
    if (!artifact || artifact.artifactDigest !== digestExplorationBundle(bundle)) throw new Error("presentation bundle digest mismatch before send");
    const admission = canonicalPresentationSceneAdmission({
      contract: "joshi.presentation.scene_admission",
      schemaVersion: 1,
      policy,
      explorationBundle: bundle,
      scene,
    });
    const receipt = parseUntrusted(await this.post("/api/v1/presentation/scenes", admission, signal), presentationSceneReceiptV1Schema);
    assertSceneReceipt(receipt, scene);
    return receipt;
  }

  async appendEvent(eventInput: PresentationEventV1, signal?: AbortSignal): Promise<PresentationEventReceiptV1> {
    const event = presentationEventV1Schema.parse(eventInput);
    const receipt = parseUntrusted(await this.post("/api/v1/presentation/events", canonicalPresentationEvent(event), signal), presentationEventReceiptV1Schema);
    assertEventReceipt(receipt, event);
    return receipt;
  }

  private async post(path: string, body: string, signal?: AbortSignal): Promise<string> {
    bounded(body);
    let response: Response;
    try {
      response = await fetch(new URL(path, this.baseUrl), {
        method: "POST",
        ...(signal ? { signal } : {}),
        credentials: "omit",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Joshi-Pairing-Token": this.pairingSession.authorizationHeader("presentation_evidence_write"),
        },
        body,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new RetryablePresentationError(error instanceof Error ? error.message : "presentation transport failed");
    }
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        this.pairingSession.clear();
        throw new PairingSessionRejectedError("Local session expired or was revoked; pair again.");
      }
      if (response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500) {
        throw new RetryablePresentationError(`presentation append is retryable (${response.status})`);
      }
      throw new Error(`presentation append failed (${response.status})`);
    }
    return readBoundedUtf8(response);
  }
}

export function configuredPresentationSink(): PresentationSink {
  const loopbackUrl = import.meta.env.VITE_JOSHI_CORE_URL as string | undefined;
  return loopbackUrl ? new LoopbackPresentationSink(loopbackUrl) : new OfflineFixturePresentationSink();
}
