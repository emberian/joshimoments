import {
  type PageResponseAcquisition,
  type ParityCandidate,
  parityCandidateSchema,
} from "./contracts";
import { base64ToBytes, sha256Id } from "./hash";
import { matchCaptureRoute } from "./policy";

export interface ParityHandoffContext {
  pairId: string;
  catalogVersion: string;
  sessionClass: "public" | "ordinary_authenticated" | "unknown";
  /** Non-secret digest of the ephemeral ordinary-session occurrence, never a token or cookie. */
  sessionOccurrenceId: string;
  authDisposition:
    | "not_required_public"
    | "ordinary_session_accepted"
    | "session_rejected"
    | "challenge_or_signature_required"
    | "unknown";
  renderedOrderDigest?: string;
  rawCaptureEnabled: boolean;
}

/**
 * Build the exact companion half of a later offline pair. The result is intentionally not queued
 * as continuous companion capture. Ember must explicitly enable raw capture and supply only
 * non-secret, ephemeral run labels during the bounded parity handoff.
 */
export async function parityCandidateFromPageResponse(
  observation: PageResponseAcquisition,
  context: ParityHandoffContext,
): Promise<ParityCandidate> {
  if (!context.rawCaptureEnabled) {
    throw new Error("parity requires explicit raw-on capture");
  }
  if (observation.parityProjectionCompleteness !== "complete") {
    throw new Error("parity request projection is incomplete");
  }
  const route = matchCaptureRoute(`${observation.sourceOrigin}${observation.sourcePath}`, {
    captureEnabled: true,
    rawCaptureEnabled: true,
    origins: {
      "pump-frontend": true,
      "coin-communities": true,
      "pump-profile": true,
    },
  });
  if (route === null || route.id !== observation.routeId) {
    throw new Error("parity route does not match the capture catalog");
  }
  const requestedAt = Date.parse(observation.requestedAt);
  const capturedAt = Date.parse(observation.capturedAt);
  const bodyReadAt = Date.parse(observation.bodyReadAt);
  if (requestedAt > capturedAt || capturedAt > bodyReadAt) {
    throw new Error("parity source clocks are not causal");
  }
  const bytes = base64ToBytes(observation.bodyBase64);
  if (
    String(bytes.byteLength) !== observation.responseBytes ||
    (await sha256Id(bytes)) !== observation.responseBlobId
  ) {
    throw new Error("parity response byte closure mismatch");
  }
  return parityCandidateSchema.parse({
    contract: "joshi.pump_api.parity_input.v2",
    pairId: context.pairId,
    sourceAcquisitionId: observation.acquisitionId,
    source: "pump_companion",
    routeId: route.parityRouteId,
    catalogVersion: context.catalogVersion,
    requestFingerprint: observation.parityRequestFingerprint,
    requestFingerprintContract: observation.parityRequestFingerprintContract,
    requestProjectionCompleteness: observation.parityProjectionCompleteness,
    visibleFilterFingerprint: observation.visibleFilterFingerprint,
    cursorInFingerprint: observation.cursorInFingerprint,
    paginationKind: observation.paginationKind,
    pageOrdinal: observation.pageOrdinal,
    sessionClass: context.sessionClass,
    sessionOccurrenceId: context.sessionOccurrenceId,
    authDisposition: context.authDisposition,
    comparisonBoundary: "fetch_response_decoded_body_bytes",
    startedAt: micros(observation.requestedAt),
    receivedAt: micros(observation.bodyReadAt),
    httpStatus: observation.responseStatus,
    bodyBase64: observation.bodyBase64,
    byteLength: observation.responseBytes,
    blobId: observation.responseBlobId,
    renderedOrderDigest: context.renderedOrderDigest ?? null,
  });
}

function micros(value: string): string {
  return value.replace(/\.(\d{3})Z$/, ".$1000Z");
}
