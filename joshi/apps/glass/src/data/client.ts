import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import type { GlassSnapshotV1, ReplayMode } from "../contract/v1";
import { parseGlassSnapshotV1 } from "../contract/v1";
import { loadCandidateSlice, type CandidateSliceAnswer } from "./candidateSlice";
import type { ExplorationBundleV1, PresentationPolicyV1 } from "../presentation/contract";
import { defaultPresentationPolicy } from "../presentation/policies";
import { explorationBundleForServedScene } from "../presentation/servedSceneBundle";
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
  /**
   * One candidate sliced verbatim from an immutable scene, when this source's core serves the
   * slice route (`data/candidateSlice.ts`). Optional and feature-detected: a source without it
   * (fixtures, older cores) simply leaves the caller on the full snapshot, which stays the
   * authority either way.
   */
  candidateSlice?(sceneId: string, candidateId: string, signal?: AbortSignal): Promise<CandidateSliceAnswer>;
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
   * Materials for the hypothesis lab over a scene a local core served.
   *
   * Read this before changing it. Until 2026-08-21 this method returned the offline *fixture*
   * bundle, so a live session rendered roughly fifteen authored numbers about a coin the operator
   * had not selected -- "Observed gross in 384000000 lamports", wallet arrival intensities,
   * liquidity recovery percentages -- each behind a green `Observed` badge and stamped with the
   * live scene's own render clock. The docstring that used to sit here asserted the bundle "adds
   * no field, no number and no subject that the snapshot did not already carry", which was false
   * and is the reason the defect survived review. Do not restate an invariant here; state what the
   * code does and let the code be checkable.
   *
   * What it does: `explorationBundleForServedScene` copies the scene identity, the verified view
   * digest, and the render clock out of `snapshot`, and emits the eight panels the bundle contract
   * demands with every signal, relation, and mark array empty. JOSHI has no derivation from a
   * served Glass view to wallet flow, response kernels, liquidity geometry, or cluster topology,
   * so the lab shows those views as explicitly empty rather than filled.
   *
   * The `policy` is an authored presentation plan -- panel order, salience, and a stated
   * hypothesis -- not an evidence claim, and it is labelled as a hypothesis where it renders.
   * `publication` is null because a loopback scene is not a durable cockpit publication; the
   * publication-backed path is `CockpitPublicationDataSource`, which reads its bundle from the
   * publication and must keep doing so.
   */
  presentationMaterials(snapshot: GlassSnapshotV1) {
    return {
      policy: defaultPresentationPolicy,
      bundle: explorationBundleForServedScene(snapshot),
      publication: null,
    };
  }

  async candidateSlice(sceneId: string, candidateId: string, signal?: AbortSignal): Promise<CandidateSliceAnswer> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.pairingSession.paired()) {
      headers["X-Joshi-Pairing-Token"] = this.pairingSession.authorizationHeader("cockpit_read");
    }
    return loadCandidateSlice(this.baseUrl, sceneId, candidateId, headers, signal);
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
