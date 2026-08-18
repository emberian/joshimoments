import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import {
  BRIDGE_PROTOCOL,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import { DEFAULT_CAPTURE_CONFIG, type PageResponseAcquisition } from "../src/contracts";
import { bytesToBase64, sha256Id, sha256Utf8 } from "../src/hash";
import { acquisitionFromPageResponse, approximateEnvelopeBytes } from "../src/pipeline";
import {
  matchCaptureRoute,
  projectRequestForFingerprint,
  projectRequestForParity,
} from "../src/policy";
import { BoundedQueue } from "../src/queue";
import type { QueuedAcquisition } from "../src/sink";

interface MockCapture {
  url: string;
  pagePath: string;
  capturedAt: string;
  body: unknown;
}
interface MockFixture {
  captures: MockCapture[];
  expected: { records: number; digest: string; kinds: Record<string, number> };
}

const fixtureUrl = new URL("../fixtures/mock-pump-responses.json", import.meta.url);
const fixture = JSON.parse(await readFile(fixtureUrl, "utf8")) as MockFixture;
const config = { ...DEFAULT_CAPTURE_CONFIG, captureEnabled: true };
const queue = new BoundedQueue<QueuedAcquisition>(512, 2 * 1024 * 1024);

for (const [sequence, capture] of fixture.captures.entries()) {
  const url = new URL(capture.url);
  const route = matchCaptureRoute(url, config);
  if (route === null) throw new Error(`fixture URL has no allowed route: ${capture.url}`);
  const bodyBytes = new TextEncoder().encode(JSON.stringify(capture.body));
  const projection = projectRequestForFingerprint(url, route);
  const parityProjection = await projectRequestForParity(url, route);
  const observation: PageResponseAcquisition = {
    protocol: BRIDGE_PROTOCOL,
    kind: "response-acquisition",
    acquisitionId: `10000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    pageInstanceId: "20000000-0000-4000-8000-000000000001",
    routeId: route.id,
    sourceOrigin: url.origin,
    sourcePath: url.pathname,
    pagePath: capture.pagePath,
    requestedAt: capture.capturedAt,
    capturedAt: capture.capturedAt,
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    sequence: String(sequence),
    requestFingerprint: await sha256Utf8(projection.canonical),
    requestFingerprintContract: REQUEST_FINGERPRINT_CONTRACT,
    requestProjectionCompleteness: projection.completeness,
    parityRequestFingerprint: parityProjection.requestFingerprint,
    parityRequestFingerprintContract: parityProjection.requestFingerprintContract,
    parityProjectionCompleteness: parityProjection.completeness,
    visibleFilterFingerprint: parityProjection.visibleFilterFingerprint,
    cursorInFingerprint: parityProjection.cursorInFingerprint,
    paginationKind: parityProjection.paginationKind,
    pageOrdinal: parityProjection.pageOrdinal,
    responseBlobId: await sha256Id(bodyBytes),
    responseBytes: String(bodyBytes.byteLength),
    responseStatus: 200,
    bodyReadAt: capture.capturedAt,
    responseBoundary: "fetch-response-decoded-body-bytes",
    mediaType: "application/json",
    bodyBase64: bytesToBase64(bodyBytes),
  };
  const envelope = await acquisitionFromPageResponse(observation, config, {
    allowRaw: false,
    receivedAt: new Date("2026-08-16T12:01:00.000Z"),
  });
  if (envelope === null) throw new Error("offline mock acquisition was rejected");
  const queued = { envelope, approxBytes: approximateEnvelopeBytes(envelope) };
  if (!queue.enqueue(queued).accepted) {
    throw new Error("offline mock unexpectedly exceeded its queue budget");
  }
}

const kinds: Record<string, number> = {};
let records = 0;
for (const item of queue.snapshot()) {
  for (const record of item.envelope.records) {
    kinds[record.kind] = (kinds[record.kind] ?? 0) + 1;
    records += 1;
  }
}
const digest = createHash("sha256")
  .update(JSON.stringify(queue.snapshot().map((item) => item.envelope)))
  .digest("hex");
const result = { acquisitions: queue.length, records, queueBytes: queue.bytes, kinds, digest };
const kindsMatch = Object.entries(fixture.expected.kinds).every(
  ([kind, count]) => kinds[kind] === count,
);
if (
  result.records !== fixture.expected.records ||
  result.digest !== fixture.expected.digest ||
  Object.keys(kinds).length !== Object.keys(fixture.expected.kinds).length ||
  !kindsMatch
) {
  throw new Error(`offline mock mismatch: ${JSON.stringify(result)}`);
}
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
