import { parse as parseLossless } from "lossless-json";
import { describe, expect, it } from "vitest";

import { DEFAULT_CAPTURE_CONFIG } from "../src/contracts";
import { normalizeResponse } from "../src/normalize";
import { matchCaptureRoute } from "../src/policy";

describe("field-allowlisted lossless normalization", () => {
  it("retains numeric lexemes exactly and excludes future outcomes and secrets", () => {
    const route = matchCaptureRoute("https://frontend-api-v3.pump.fun/callout/recent", {
      ...DEFAULT_CAPTURE_CONFIG,
      captureEnabled: true,
    });
    expect(route).not.toBeNull();
    if (route === null) return;
    const body = parseLossless(
      '{"callouts":[{"id":900719925474099312345,"calloutPrice":0.0001000,"marketCap":1.2300e+19,"multiple":8.2,"authorization":"Bearer forbidden"}]}',
    );
    const [record] = normalizeResponse(route, "/callout/recent", body).records;
    expect(record?.fields.id).toEqual({
      encoding: "json-number-lexeme",
      value: "900719925474099312345",
    });
    expect(record?.fields.calloutPrice).toEqual({
      encoding: "json-number-lexeme",
      value: "0.0001000",
    });
    expect(record?.fields.marketCap).toEqual({
      encoding: "json-number-lexeme",
      value: "1.2300e+19",
    });
    expect(record?.fields).not.toHaveProperty("multiple");
    expect(record?.fields).not.toHaveProperty("authorization");
  });

  it("does not promote unknown response fields", () => {
    const url =
      "https://api.coin-communities.xyz/api/v1/communities/MintAlpha11111111111111111111111111111111/messages/public";
    const route = matchCaptureRoute(url, {
      ...DEFAULT_CAPTURE_CONFIG,
      captureEnabled: true,
    });
    expect(route).not.toBeNull();
    if (route === null) return;
    const body = parseLossless(
      '{"messages":[{"id":"m1","username":"u","content":"hello","internalSession":"nope"}]}',
    );
    const [record] = normalizeResponse(route, new URL(url).pathname, body).records;
    expect(record?.fields.content).toEqual({ encoding: "utf8", value: "hello" });
    expect(record?.fields).not.toHaveProperty("internalSession");
  });

  it("rejects already-coerced JavaScript numbers at the normalization boundary", () => {
    const route = matchCaptureRoute("https://frontend-api-v3.pump.fun/callout/recent", {
      ...DEFAULT_CAPTURE_CONFIG,
      captureEnabled: true,
    });
    expect(route).not.toBeNull();
    if (route === null) return;
    expect(() =>
      normalizeResponse(route, "/callout/recent", { callouts: [{ id: 9007199254740992 }] }),
    ).toThrow(/lossless JSON parser/);
  });
});
