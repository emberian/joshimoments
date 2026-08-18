import {
  BRIDGE_PROTOCOL,
  MAX_SOURCE_BODY_BYTES,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import {
  type CaptureConfig,
  DEFAULT_CAPTURE_CONFIG,
  type PageGapObservation,
  type PageResponseAcquisition,
  pageConfigMessageSchema,
} from "../src/contracts";
import { bytesToBase64, sha256Id, sha256Utf8 } from "../src/hash";
import {
  matchCaptureRoute,
  projectRequestForFingerprint,
  projectRequestForParity,
} from "../src/policy";

interface MainWorldState {
  config: CaptureConfig;
  leaseUntilEpochMs: number;
  sequence: bigint;
  pageInstanceId: string;
}

interface BoundedBody {
  bytes: Uint8Array | null;
  observedBytes: number | null;
  tooLarge: boolean;
}

interface InstalledWindow extends Window {
  __joshiPumpCompanionInstalledV1?: boolean;
}

async function readBoundedBody(response: Response): Promise<BoundedBody> {
  const declaredLength = Number(response.headers.get("Content-Length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_SOURCE_BODY_BYTES) {
    return { bytes: null, observedBytes: declaredLength, tooLarge: true };
  }
  if (response.body === null) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      bytes: bytes.byteLength <= MAX_SOURCE_BODY_BYTES ? bytes : null,
      observedBytes: bytes.byteLength,
      tooLarge: bytes.byteLength > MAX_SOURCE_BODY_BYTES,
    };
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let observedBytes = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    observedBytes += result.value.byteLength;
    if (observedBytes > MAX_SOURCE_BODY_BYTES) {
      await reader.cancel("Joshi Pump Companion source-body limit reached");
      return { bytes: null, observedBytes, tooLarge: true };
    }
    chunks.push(result.value);
  }
  const bytes = new Uint8Array(observedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { bytes, observedBytes, tooLarge: false };
}

function requestMethod(input: RequestInfo | URL, init: RequestInit | undefined): string {
  if (typeof init?.method === "string") return init.method.toUpperCase();
  return input instanceof Request ? input.method.toUpperCase() : "GET";
}

function requestUrl(input: RequestInfo | URL): URL | null {
  try {
    return new URL(input instanceof Request ? input.url : String(input), location.href);
  } catch {
    return null;
  }
}

function isJsonResponse(response: Response): boolean {
  const contentType = response.headers.get("Content-Type")?.toLowerCase() ?? "";
  return contentType.includes("application/json") || contentType.includes("+json");
}

export default defineUnlistedScript(() => {
  const installedWindow = window as InstalledWindow;
  if (installedWindow.__joshiPumpCompanionInstalledV1 === true) return;
  Object.defineProperty(installedWindow, "__joshiPumpCompanionInstalledV1", {
    configurable: false,
    enumerable: false,
    value: true,
    writable: false,
  });

  const state: MainWorldState = {
    config: DEFAULT_CAPTURE_CONFIG,
    leaseUntilEpochMs: 0,
    sequence: 0n,
    pageInstanceId: crypto.randomUUID(),
  };

  window.addEventListener("message", (event: MessageEvent<unknown>) => {
    if (event.source !== window || event.origin !== location.origin) return;
    const parsed = pageConfigMessageSchema.safeParse(event.data);
    if (parsed.success) {
      state.config = parsed.data.config;
      state.leaseUntilEpochMs = parsed.data.leaseUntilEpochMs;
    }
  });

  const originalFetch = window.fetch;
  window.fetch = new Proxy(originalFetch, {
    apply(target, thisArg, argumentsList: Parameters<typeof fetch>) {
      const [input, init] = argumentsList;
      const candidateUrl = requestUrl(input);
      const method = requestMethod(input, init);
      const route =
        candidateUrl !== null && method === "GET"
          ? matchCaptureRoute(candidateUrl, state.config)
          : null;
      const captureAllowed =
        route !== null && state.config.captureEnabled && Date.now() <= state.leaseUntilEpochMs;
      const requestedAt = new Date().toISOString();
      const acquisitionId = captureAllowed ? crypto.randomUUID() : null;
      const sequence = state.sequence.toString();
      if (captureAllowed) state.sequence += 1n;
      const pending = Reflect.apply(target, thisArg, argumentsList) as Promise<Response>;

      return pending.then((response) => {
        const capture = async (): Promise<void> => {
          if (!captureAllowed || acquisitionId === null || route === null) return;
          if (!response.ok || !isJsonResponse(response)) return;
          const responseUrl = response.url ? new URL(response.url) : candidateUrl;
          if (responseUrl === null) return;
          const responseRoute = matchCaptureRoute(responseUrl, state.config);
          if (responseRoute === null || responseRoute.id !== route.id) return;

          const projection = projectRequestForFingerprint(
            candidateUrl ?? responseUrl,
            responseRoute,
          );
          const parityProjection = await projectRequestForParity(
            candidateUrl ?? responseUrl,
            responseRoute,
          );
          const requestFingerprint = await sha256Utf8(projection.canonical);
          const common = {
            protocol: BRIDGE_PROTOCOL,
            acquisitionId,
            pageInstanceId: state.pageInstanceId,
            routeId: responseRoute.id,
            sourceOrigin: responseUrl.origin,
            sourcePath: responseUrl.pathname,
            pagePath: location.pathname,
            capturedAt: new Date().toISOString(),
            requestedAt,
            sourceClockContract: SOURCE_CLOCK_CONTRACT,
            sequence,
            requestFingerprint,
            requestFingerprintContract: REQUEST_FINGERPRINT_CONTRACT,
            requestProjectionCompleteness: projection.completeness,
            parityRequestFingerprint: parityProjection.requestFingerprint,
            parityRequestFingerprintContract: parityProjection.requestFingerprintContract,
            parityProjectionCompleteness: parityProjection.completeness,
            visibleFilterFingerprint: parityProjection.visibleFilterFingerprint,
            cursorInFingerprint: parityProjection.cursorInFingerprint,
            paginationKind: parityProjection.paginationKind,
            pageOrdinal: parityProjection.pageOrdinal,
          } as const;

          let body: BoundedBody;
          try {
            body = await readBoundedBody(response.clone());
          } catch {
            const gap: PageGapObservation = {
              ...common,
              kind: "capture-gap",
              reason: "source-body-read-failed",
              responseBytes: null,
            };
            window.postMessage(gap, location.origin);
            return;
          }
          if (body.tooLarge || body.bytes === null) {
            const gap: PageGapObservation = {
              ...common,
              kind: "capture-gap",
              reason: "source-body-too-large",
              responseBytes: body.observedBytes === null ? null : String(body.observedBytes),
            };
            window.postMessage(gap, location.origin);
            return;
          }

          const observation: PageResponseAcquisition = {
            ...common,
            kind: "response-acquisition",
            responseBlobId: await sha256Id(body.bytes),
            responseBytes: String(body.bytes.byteLength),
            responseStatus: response.status,
            bodyReadAt: new Date().toISOString(),
            responseBoundary: "fetch-response-decoded-body-bytes",
            mediaType: "application/json",
            bodyBase64: bytesToBase64(body.bytes),
          };
          window.postMessage(observation, location.origin);
        };
        void capture();
        return response;
      });
    },
  });
});
