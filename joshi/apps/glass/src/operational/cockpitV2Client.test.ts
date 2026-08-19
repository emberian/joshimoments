import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MemoryOnlyPairingSession,
  canonicalPairingSessionId,
  type PairingSessionDescriptor,
} from "../security/pairing";
import {
  digestCanonicalJson,
  parseCockpitV2BrowserPresentationClaim,
} from "./cockpitV2";
import { SameOriginCockpitV2InspectorClient } from "./cockpitV2Client";

function paired(scopes: PairingSessionDescriptor["scopes"] = ["cockpit_read"]): MemoryOnlyPairingSession {
  const session = new MemoryOnlyPairingSession();
  session.establish(`jpc1_${"a".repeat(64)}`, {
    sessionId: canonicalPairingSessionId(window.location.origin, "1", "1"),
    origin: window.location.origin,
    epoch: "1",
    expiresAt: "2099-08-18T00:00:00.000000Z",
    scopes,
    authority: "read_only_no_execution",
  });
  return session;
}

function frozenPresentationClaim() {
  return parseCockpitV2BrowserPresentationClaim(JSON.parse(readFileSync(
    resolve(process.cwd(), "../../fixtures/publication/cockpit_v2_browser_presentation_claim_v1.json"),
    "utf8",
  )));
}

afterEach(() => vi.unstubAllGlobals());

describe("same-origin Cockpit V2 inspector client", () => {
  it("loads the exact bounded index with the memory-only scoped capability", async () => {
    const session = paired();
    const index = {
      contract: "joshi.core.cockpit_v2_index",
      schemaVersion: 1,
      authority: "read_only_no_execution",
      items: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(index), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(new SameOriginCockpitV2InspectorClient(session).list()).resolves.toEqual(index);
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/cockpit-v2/publications");
    expect(init).toMatchObject({ credentials: "omit", cache: "no-store" });
    expect(init.headers).toMatchObject({ "X-Joshi-Pairing-Token": `jpc1_${"a".repeat(64)}` });
  });

  it("clears a rejected session and refuses duplicate-key or cross-origin input", async () => {
    const rejected = paired();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    await expect(new SameOriginCockpitV2InspectorClient(rejected).list()).rejects.toThrow(/pair again/i);
    expect(rejected.paired()).toBe(false);

    const duplicate = paired();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"contract":"joshi.core.cockpit_v2_index","contract":"joshi.core.cockpit_v2_index"}', { status: 200 })));
    await expect(new SameOriginCockpitV2InspectorClient(duplicate).list()).rejects.toThrow(/duplicate/i);
    expect(() => new SameOriginCockpitV2InspectorClient(duplicate, "http://127.0.0.1:6553")).toThrow(/exact HTTP loopback page origin/i);
  });

  it("posts exact claim bytes and independently closes the bounded paired receipt", async () => {
    const session = paired(["cockpit_read", "presentation_evidence_write"]);
    const descriptor = session.descriptor()!;
    const claim = frozenPresentationClaim();
    const receipt = {
      contract: "joshi.core.cockpit_v2_browser_presentation_receipt",
      schemaVersion: 1,
      catalogId: "glass-presentation-test",
      catalogSchema: "joshi.sqlite.v21",
      clientPresentationId: claim.clientPresentationId,
      claimDigest: claim.claimDigest,
      claimBytesDigest: digestCanonicalJson(claim),
      pairingSessionId: descriptor.sessionId,
      publicationId: claim.publication.publicationId,
      storeCommitSeq: "13",
      status: "accepted",
      authority: "read_only_no_execution",
      ceiling: "durable_browser_report_only_not_pixel_verified",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(new SameOriginCockpitV2InspectorClient(session).present(claim)).resolves.toEqual(receipt);
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/cockpit-v2/presentations");
    expect(init).toMatchObject({ method: "POST", credentials: "omit", cache: "no-store" });
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Joshi-Pairing-Token": `jpc1_${"a".repeat(64)}`,
    });
    expect(init.body).toBe(JSON.stringify(claim));

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ...receipt,
      pairingSessionId: canonicalPairingSessionId(window.location.origin, "1", "2"),
    }), { status: 200 })));
    await expect(new SameOriginCockpitV2InspectorClient(session).present(claim)).rejects.toThrow(/exact paired claim/i);
  });
});
