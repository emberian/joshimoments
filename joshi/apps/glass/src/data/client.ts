import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import type { GlassSnapshotV1, ReplayMode } from "../contract/v1";
import { parseGlassSnapshotV1 } from "../contract/v1";
import type { ExplorationBundleV1, PresentationPolicyV1 } from "../presentation/contract";
import { defaultPresentationPolicy, explorationBundleFor } from "../presentation/fixtures";
import { glassPairingSession, type MemoryOnlyPairingSession } from "../security/pairing";
import { mockSnapshots } from "./mockSnapshot";

export const MAX_GLASS_SNAPSHOT_BYTES = 4 * 1024 * 1024;

export type SnapshotRequest = {
  mode: ReplayMode;
  basisSceneId: string | null;
  signal?: AbortSignal;
};

export interface GlassDataSource {
  readonly kind: "offline_fixture" | "loopback";
  loadSnapshot(request: SnapshotRequest): Promise<GlassSnapshotV1>;
  presentationMaterials?(snapshot: GlassSnapshotV1): {
    policy: PresentationPolicyV1;
    bundle: ExplorationBundleV1;
    publication: { cockpitPublicationId: string; cockpitPublicationDigest: string } | null;
  } | null;
}

async function readBoundedUtf8(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_GLASS_SNAPSHOT_BYTES) {
      throw new Error("glass snapshot exceeds the browser response bound");
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }

  const decoder = new TextDecoder("utf-8", { fatal: true });
  let total = 0;
  let body = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_GLASS_SNAPSHOT_BYTES) {
      await reader.cancel("glass snapshot response bound exceeded");
      throw new Error("glass snapshot exceeds the browser response bound");
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

function assertRequestedView(snapshot: GlassSnapshotV1, request: SnapshotRequest): void {
  if (snapshot.view.mode !== request.mode) {
    throw new Error(`glass core returned ${snapshot.view.mode} for requested ${request.mode} mode`);
  }
  if (request.mode === "witnessed" && snapshot.view.basisSceneId !== null) {
    throw new Error("witnessed glass snapshot unexpectedly names a basis scene");
  }
  if (request.mode !== "witnessed" && snapshot.view.basisSceneId !== request.basisSceneId) {
    throw new Error("glass snapshot basis scene does not match the requested witnessed scene");
  }
}

export class OfflineFixtureDataSource implements GlassDataSource {
  readonly kind = "offline_fixture" as const;

  async loadSnapshot(request: SnapshotRequest): Promise<GlassSnapshotV1> {
    const snapshot = mockSnapshots[request.mode];
    assertRequestedView(snapshot, request);
    return Promise.resolve(snapshot);
  }
}

export class LoopbackDataSource implements GlassDataSource {
  readonly kind = "loopback" as const;
  private readonly baseUrl: URL;
  private readonly launchSceneId: string | null;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(
    baseUrl: string,
    launchSceneId: string | null = null,
    pairingSession: MemoryOnlyPairingSession = glassPairingSession,
  ) {
    const parsed = new URL(baseUrl);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    if (parsed.protocol !== "http:" || !loopbackHosts.has(parsed.hostname)) {
      throw new Error("glass core URL must be an explicit HTTP loopback address");
    }
    this.baseUrl = parsed;
    this.launchSceneId = launchSceneId;
    this.pairingSession = pairingSession;
  }

  /**
   * Ordering, salience and omission plan for exactly the items this snapshot served. It is a
   * presentation plan over served bytes, never an extra evidence claim: it adds no field, no
   * number and no subject that the snapshot did not already carry.
   */
  presentationMaterials(snapshot: GlassSnapshotV1) {
    return { policy: defaultPresentationPolicy, bundle: explorationBundleFor(snapshot), publication: null };
  }

  async loadSnapshot(request: SnapshotRequest): Promise<GlassSnapshotV1> {
    const url = new URL("/api/v1/glass/snapshot", this.baseUrl);
    url.searchParams.set("mode", request.mode);
    const selectedSceneId = request.mode === "witnessed"
      ? request.basisSceneId ?? this.launchSceneId
      : request.basisSceneId;
    if (selectedSceneId === null) {
      throw new Error("loopback witnessed launch requires an explicit immutable scene ID; latest/current selection is forbidden");
    }
    url.searchParams.set("basisSceneId", selectedSceneId);

    // The paired snapshot route is capability-gated. An unpaired source still reads an
    // unpaired core, so the header is attached only when a live session actually holds one.
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.pairingSession.paired()) {
      headers["X-Joshi-Pairing-Token"] = this.pairingSession.authorizationHeader("cockpit_read");
    }
    const response = await fetch(url, {
      ...(request.signal ? { signal: request.signal } : {}),
      credentials: "omit",
      cache: "no-store",
      headers,
    });
    if (!response.ok) throw new Error(`glass snapshot request failed (${response.status})`);

    const declaredLength = response.headers.get("Content-Length");
    if (declaredLength !== null && Number(declaredLength) > MAX_GLASS_SNAPSHOT_BYTES) {
      throw new Error("glass snapshot exceeds the browser response bound");
    }
    const body = await readBoundedUtf8(response);

    // Ordinary JSON.parse would silently collapse duplicate object keys before
    // the strict contract validator could see them. Validate the raw untrusted
    // HTTP text first, then use the platform parser so keys such as `__proto__`
    // remain ordinary own properties for the strict schema to reject.
    const wireError = validateJsonWithoutDuplicateKeys(body, false);
    if (wireError !== undefined) throw new Error(`invalid glass snapshot JSON: ${wireError}`);
    const decoded = JSON.parse(body, (key, value: unknown) => {
      if (key === "__proto__" || key === "constructor" || key === "prototype") {
        throw new Error(`forbidden glass snapshot JSON key: ${key}`);
      }
      return value;
    }) as unknown;
    const snapshot = parseGlassSnapshotV1(decoded);
    if (snapshot.transport !== "loopback") {
      throw new Error("loopback core returned an envelope with the wrong transport claim");
    }
    assertRequestedView(snapshot, request);
    return snapshot;
  }
}

export function configuredDataSource(): GlassDataSource {
  const loopbackUrl = import.meta.env.VITE_JOSHI_CORE_URL as string | undefined;
  const launchSceneId = import.meta.env.VITE_JOSHI_LAUNCH_SCENE_ID as string | undefined;
  return loopbackUrl ? new LoopbackDataSource(loopbackUrl, launchSceneId ?? null) : new OfflineFixtureDataSource();
}
