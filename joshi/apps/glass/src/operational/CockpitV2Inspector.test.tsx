import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MemoryOnlyPairingSession, canonicalPairingSessionId } from "../security/pairing";
import { CockpitV2InspectorShell } from "./CockpitV2Inspector";
import type { CockpitV2InspectorTransport } from "./cockpitV2Client";
import {
  digestCanonicalJson,
  type CockpitV2BrowserPresentationClaim,
  type CockpitV2Index,
  type CockpitV2IndexEntry,
  type CockpitV2Open,
} from "./cockpitV2";
import { fixture, sealCockpitV2 } from "./cockpitV2TestSupport";

const d = `sha256:${"1".repeat(64)}`;
const entry: CockpitV2IndexEntry = {
  publicationId: "cockpit-v2-fixture-1",
  publicationDigest: d,
  publicationBytesDigest: d,
  publicationCommitSeq: "11",
  headDigest: d,
  headBytesDigest: d,
  headCommitSeq: "12",
  sourceOccurrenceId: "source-fixture-1",
  supersedesPublicationId: null,
  eligibleCount: "1",
  factCount: "1",
  gapCount: "0",
  ceiling: "unverified_semantic",
};
const index: CockpitV2Index = {
  contract: "joshi.core.cockpit_v2_index",
  schemaVersion: 1,
  authority: "read_only_no_execution",
  items: [entry],
};
const opened: CockpitV2Open = {
  authority: "read_only_no_execution",
  contract: "joshi.core.cockpit_v2_open",
  head: {
    contract: "joshi.cockpit.v2.head",
    schemaVersion: 2,
    publicationId: entry.publicationId,
    publicationDigest: d,
    commitSeq: "11",
    headDigest: d,
    authority: "read_only_no_execution",
  },
  headBytesDigest: d,
  headCommitSeq: "12",
  publication: {
    contract: "joshi.cockpit.v2.publication",
    schemaVersion: 2,
    publicationId: entry.publicationId,
    manifest: {
      contract: "joshi.cockpit.v2.manifest",
      schemaVersion: 2,
      surfaceProfile: { profileId: "profile-1", profileDigest: d, fieldCells: [{ surfaceId: "surface-1", sourceId: "source-1", field: "mint" }] },
      observedUniverse: { universeId: "universe-1", universeDigest: d, eligibleCount: "1", eligibleSubjects: ["MintA"] },
      cutoff: { knowledgeAt: "2026-08-18T12:00:00.000000Z", commitThrough: "10", chainSlot: null },
      sourceFacts: [{
        factId: "fact-1",
        factDigest: d,
        surfaceId: "surface-1",
        sourceId: "source-1",
        subject: "MintA",
        field: "mint",
        protection: "public",
        observedAt: "2026-08-18T11:00:00.000000Z",
        knownAt: "2026-08-18T11:00:00.000000Z",
        commitSeq: "9",
      }],
      memberships: [{ subject: "MintA", membership: "hot", observedAt: "2026-08-18T11:00:00.000000Z", evidenceDigest: d }],
      coverage: [{ surfaceId: "surface-1", sourceId: "source-1", subject: "MintA", field: "mint", factIds: ["fact-1"], state: "complete", coverageDigest: d }],
      gaps: [],
      renderedSubjects: ["MintA"],
      omissions: [],
      orderingPolicy: "subject",
      paginationPolicy: "complete",
      authority: "read_only_no_execution",
      ceiling: "unverified_semantic",
      semanticDigest: d,
      containerDigest: d,
    },
    checkpoint: {
      contract: "joshi.cockpit.v2.checkpoint",
      schemaVersion: 2,
      profileDigest: d,
      universeDigest: d,
      cutoff: { knowledgeAt: "2026-08-18T12:00:00.000000Z", commitThrough: "10", chainSlot: null },
      semanticDigest: d,
      containerDigest: d,
      checkpointDigest: d,
      authority: "read_only_no_execution",
    },
    commitSeq: "11",
    supersedesPublicationId: null,
    publicationDigest: d,
    authority: "read_only_no_execution",
  },
  publicationBytesDigest: d,
  publicationCommitSeq: "11",
  schemaVersion: 1,
  sourceOccurrenceId: "source-fixture-1",
};

describe("Cockpit V2 inspector shell", () => {
  it("labels the normal-server opt-in as local-store inspection without enabling evidence controls", () => {
    render(<CockpitV2InspectorShell
      sourceKind="local_store"
      session={new MemoryOnlyPairingSession()}
      client={{
        exchange: async () => { throw new Error("not exercised"); },
        list: async () => index,
        open: async () => opened,
        present: async () => { throw new Error("not exercised"); },
      }}
    />);
    expect(screen.getByText("Local store inspection", { selector: ".eyebrow" })).toBeInTheDocument();
    expect(screen.getByText(/opt-in local core server/i)).toBeInTheDocument();
    expect(screen.getByText(/browser-report receipt may record an exact mount/i)).toBeInTheDocument();
    expect(screen.getByText(/no signer, wallet, transaction builder/i)).toBeInTheDocument();
  });

  it("pairs explicitly, selects one exact head, and renders only descriptive fixture evidence", async () => {
    const session = new MemoryOnlyPairingSession();
    const descriptor = {
      sessionId: canonicalPairingSessionId(window.location.origin, "1", "1"),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-18T00:00:00.000000Z",
      scopes: ["cockpit_read" as const],
      authority: "read_only_no_execution" as const,
    };
    const client: CockpitV2InspectorTransport = {
      exchange: async () => {
        session.establish(`jpc1_${"a".repeat(64)}`, descriptor);
        return descriptor;
      },
      list: async () => index,
      open: async () => opened,
      present: async () => { throw new Error("presentation scope is absent"); },
    };
    const user = userEvent.setup();
    render(<CockpitV2InspectorShell session={session} client={client} />);
    expect(screen.getByRole("heading", { name: /pair this read-only inspector/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/one-time pairing code/i), "JOSHI-040G-7080-XPTK-366S-YS65-1JRN-4N5D-NJ7N");
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    expect(await screen.findByRole("heading", { name: /choose an exact cockpit v2 head/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /inspect exact bytes/i }));
    expect(await screen.findByRole("heading", { name: entry.publicationId })).toBeInTheDocument();
    expect(screen.getByText(/unverified semantic ceiling/i)).toBeInTheDocument();
    expect(screen.getByText(/no presentation-evidence scope/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /store-resolved public facts/i })).toBeInTheDocument();
    expect(screen.queryByText(/submit|trade|execute/i)).not.toBeInTheDocument();
  });

  it("submits one exact post-mount report when the durable pairing scope is present", async () => {
    const exact = sealCockpitV2(fixture("cockpit_v2_manifest_v1.json"));
    const session = new MemoryOnlyPairingSession();
    const descriptor = {
      sessionId: canonicalPairingSessionId(window.location.origin, "1", "1"),
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2099-08-18T00:00:00.000000Z",
      scopes: ["cockpit_read" as const, "presentation_evidence_write" as const],
      authority: "read_only_no_execution" as const,
    };
    session.establish(`jpc1_${"b".repeat(64)}`, descriptor);
    const presented: CockpitV2BrowserPresentationClaim[] = [];
    const client: CockpitV2InspectorTransport = {
      exchange: async () => descriptor,
      list: async () => exact.index,
      open: async () => exact.opened,
      present: async (claim) => {
        expect(screen.getByRole("heading", { name: exact.opened.publication.publicationId })).toBeInTheDocument();
        presented.push(claim);
        if (presented.length === 1) throw new Error("synthetic presentation transport outage");
        return {
          contract: "joshi.core.cockpit_v2_browser_presentation_receipt",
          schemaVersion: 1,
          catalogId: "cockpit-v2-component-test",
          catalogSchema: "joshi.sqlite.v22",
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
      },
    };
    const user = userEvent.setup();
    render(
      <StrictMode>
        <CockpitV2InspectorShell sourceKind="local_store" session={session} client={client} />
      </StrictMode>,
    );
    await user.click(screen.getByRole("button", { name: /load exact index/i }));
    await user.click(await screen.findByRole("button", { name: /inspect exact bytes/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/synthetic presentation transport outage/i);
    await user.click(screen.getByRole("button", { name: /retry exact browser report/i }));
    expect(await screen.findByText(/durable browser report stored at commit 13/i)).toBeInTheDocument();
    expect(presented).toHaveLength(2);
    expect(JSON.stringify(presented[1])).toBe(JSON.stringify(presented[0]));
    expect(presented[1]!.publication.publicationId).toBe(exact.opened.publication.publicationId);
    expect(presented[1]!.renderedSubjects).toEqual(exact.opened.publication.manifest.renderedSubjects);
    expect(presented[1]!.ceiling).toBe("browser_reported_not_pixel_verified");
  });
});
