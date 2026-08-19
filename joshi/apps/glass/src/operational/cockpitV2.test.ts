import { describe, expect, it } from "vitest";

import {
  buildCockpitV2BrowserPresentationClaim,
  cockpitV2HeadSchema,
  cockpitV2ManifestSchema,
  digestCockpitV2BrowserPresentationClaim,
  parseCockpitV2BrowserPresentationClaim,
  parseCockpitV2Index,
  parseCockpitV2Open,
} from "./cockpitV2";
import { fixture, fixtureText, sealCockpitV2 as seal } from "./cockpitV2TestSupport";

describe("Cockpit V2 exact browser contract", () => {
  it("matches the frozen Rust manifest/publication/head digest domains", () => {
    const { opened, index } = seal(fixture("cockpit_v2_manifest_v1.json"));
    const rustHead = cockpitV2HeadSchema.parse(fixture("cockpit_v2_head_v1.json"));
    expect(opened.publication.publicationDigest).toBe("sha256:8c79941372588b2001608267ce562288488d3c0dd519595674cc6c0721af0f0f");
    expect(opened.head).toEqual(rustHead);
    expect(parseCockpitV2Index(index)).toEqual(index);
    expect(parseCockpitV2Open(opened, index.items[0])).toEqual(opened);
  });

  it("refuses self-consistent private facts, denominator narrowing, and future knowledge", () => {
    const manifest = cockpitV2ManifestSchema.parse(fixture("cockpit_v2_manifest_v1.json"));
    const privateManifest = structuredClone(manifest);
    privateManifest.sourceFacts[0]!.protection = "authenticated";
    const privateArtifact = seal(privateManifest);
    expect(() => parseCockpitV2Open(privateArtifact.opened, privateArtifact.index.items[0])).toThrow(/nonpublic fact/i);

    const narrowed = structuredClone(manifest);
    narrowed.coverage.pop();
    const narrowedArtifact = seal(narrowed);
    expect(() => parseCockpitV2Open(narrowedArtifact.opened, narrowedArtifact.index.items[0])).toThrow(/coverage does not close/i);

    const future = structuredClone(manifest);
    future.sourceFacts[0]!.knownAt = "2026-08-19T00:00:00.000000Z";
    const futureArtifact = seal(future);
    expect(() => parseCockpitV2Open(futureArtifact.opened, futureArtifact.index.items[0])).toThrow(/knowledge cutoff/i);
  });

  it("refuses index substitution, byte substitution, unknown fields, and unstable order", () => {
    const { opened, index } = seal(fixture("cockpit_v2_manifest_v1.json"));
    const wrongEntry = { ...index.items[0]!, publicationDigest: `sha256:${"f".repeat(64)}` };
    expect(() => parseCockpitV2Open(opened, wrongEntry)).toThrow(/selected index/i);
    expect(() => parseCockpitV2Open({ ...opened, headBytesDigest: `sha256:${"e".repeat(64)}` }, index.items[0])).toThrow(/exact byte digest/i);
    expect(() => parseCockpitV2Open({ ...opened, extra: true }, index.items[0])).toThrow();

    const second = { ...index.items[0]!, publicationId: "cockpit-v2-a", headCommitSeq: "12" };
    const reversed = { ...index, items: [index.items[0]!, second] };
    expect(() => parseCockpitV2Index(reversed)).toThrow(/durable head order/i);
  });

  it("binds a browser-reported mount to the exact headed publication without claiming pixels", () => {
    const { opened } = seal(fixture("cockpit_v2_manifest_v1.json"));
    const claim = buildCockpitV2BrowserPresentationClaim(opened, {
      clientPresentationId: "browser-presentation-1",
      browserPageId: "browser-page-1",
      presentationSeq: "1",
      mountedAt: "2026-08-18T12:01:00.000000Z",
      clientClockId: "browser-page-1-performance",
      monotonicNs: "1234567000",
      viewport: {
        widthCssPx: "1280",
        heightCssPx: "800",
        devicePixelRatioMilli: "2000",
      },
      documentVisibility: "visible",
      documentHasFocus: true,
    });
    expect(claim.ceiling).toBe("browser_reported_not_pixel_verified");
    expect(claim.renderedSubjects).toEqual(opened.publication.manifest.renderedSubjects);
    expect(parseCockpitV2BrowserPresentationClaim(claim, opened)).toEqual(claim);
    const frozenText = fixtureText("cockpit_v2_browser_presentation_claim_v1.json");
    expect(frozenText.endsWith("\n")).toBe(true);
    expect(JSON.stringify(claim)).toBe(frozenText.slice(0, -1));
    expect(parseCockpitV2BrowserPresentationClaim(JSON.parse(frozenText), opened)).toEqual(claim);
    expect(claim.claimDigest).toBe("sha256:b3be9ee0b5097d2fb15d1718aca21d3d76b8d6e09860d887e0241bbf2de50a26");

    expect(() => parseCockpitV2BrowserPresentationClaim({
      ...claim,
      head: { ...claim.head, headCommitSeq: "13" },
    }, opened)).toThrow(/digest mismatch/i);
    expect(() => parseCockpitV2BrowserPresentationClaim({
      ...claim,
      renderedSubjects: ["mint-2"],
      renderedSubjectCount: "1",
    }, opened)).toThrow(/digest mismatch/i);
    expect(() => parseCockpitV2BrowserPresentationClaim({
      ...claim,
      viewport: { ...claim.viewport, widthCssPx: "32769" },
    }, opened)).toThrow(/bounded contract/i);
    const nonmonotonic = {
      ...claim,
      head: { ...claim.head, headCommitSeq: claim.publication.publicationCommitSeq },
    };
    nonmonotonic.claimDigest = digestCockpitV2BrowserPresentationClaim(nonmonotonic);
    expect(() => parseCockpitV2BrowserPresentationClaim(nonmonotonic)).toThrow(/head commit/i);
    const wrongKey = {
      ...claim,
      idempotencyKey: "browser-presentation:other-page:1",
    };
    wrongKey.claimDigest = digestCockpitV2BrowserPresentationClaim(wrongKey);
    expect(() => parseCockpitV2BrowserPresentationClaim(wrongKey)).toThrow(/idempotency key/i);
    expect(() => parseCockpitV2BrowserPresentationClaim({ ...claim, extra: true }, opened)).toThrow();
  });
});
