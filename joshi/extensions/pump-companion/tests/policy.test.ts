import { describe, expect, it } from "vitest";

import { DEFAULT_CAPTURE_CONFIG } from "../src/contracts";
import { matchCaptureRoute, projectRequestForParity } from "../src/policy";

const enabled = { ...DEFAULT_CAPTURE_CONFIG, captureEnabled: true };

describe("capture route policy", () => {
  it("admits exact allowlisted response routes and strips query semantics", () => {
    const route = matchCaptureRoute(
      "https://frontend-api-v3.pump.fun/callout/recent?limit=50&pageToken=secretish",
      enabled,
    );
    expect(route?.id).toBe("callout-recent");
  });

  it("rejects authentication, mutation, websocket, and arbitrary origins", () => {
    expect(matchCaptureRoute("https://profile-api.pump.fun/auth/login", enabled)).toBeNull();
    expect(matchCaptureRoute("https://frontend-api-v3.pump.fun/follow", enabled)).toBeNull();
    expect(matchCaptureRoute("wss://livechat.pump.fun/socket", enabled)).toBeNull();
    expect(matchCaptureRoute("https://example.com/callout/recent", enabled)).toBeNull();
  });

  it("keeps authenticated profile responses disabled until deliberately enabled", () => {
    const url =
      "https://profile-api.pump.fun/api/v1/communities/MintAlpha11111111111111111111111111111111/messages";
    expect(matchCaptureRoute(url, enabled)).toBeNull();
    expect(
      matchCaptureRoute(url, {
        ...enabled,
        origins: { ...enabled.origins, "pump-profile": true },
      })?.id,
    ).toBe("profile-community");
  });

  it("projects only digest-bound request/filter/cursor state for direct parity", async () => {
    const url = new URL(
      "https://frontend-api-v3.pump.fun/callout/recent?limit=20&pageToken=opaque",
    );
    const route = matchCaptureRoute(url, enabled);
    if (route === null) throw new Error("fixture route must be allowlisted");
    const projection = await projectRequestForParity(url, route);
    expect(projection).toMatchObject({
      requestFingerprintContract: "pump-parity-request-projection.v2",
      paginationKind: "page_token",
      pageOrdinal: "0",
      completeness: "complete",
    });
    expect(projection.requestFingerprint).toBe(
      "sha256:5b1a8618d11ea5e82db7ff655045687041d6b01288a93be29d5e2882c5e62f2f",
    );
    expect(projection.visibleFilterFingerprint).toBe(
      "sha256:6082d6edfb541889d2c990caf17ea94cb564581ac5c2c18c7493ad3e5f84b449",
    );
    expect(projection.cursorInFingerprint).toBe(
      "sha256:93439aa1dc7d4b929a45c4c2185edad219c15de28c42a4eb5642aa002254b3b1",
    );
    expect(JSON.stringify(projection)).not.toContain("opaque");
  });
});
