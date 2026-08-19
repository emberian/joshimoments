import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";

const identity = z.string().min(1).max(512).regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/);
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const u64 = z.string().regex(/^(?:0|[1-9][0-9]*)$/);
const positiveU64 = u64.refine((value) => value !== "0", "must be positive");
const authority = z.literal("read_only_no_execution");
const membership = z.enum(["census", "warm", "hot", "episode", "cold_control", "denominator_only"]);
const coverageState = z.enum(["complete", "partial", "stale", "unknown", "unavailable", "refused"]);
const protection = z.enum(["public", "app_private", "authenticated", "raw_private_bytes"]);

const fieldCellSchema = z.object({ surfaceId: identity, sourceId: identity, field: identity }).strict();
const profileSchema = z.object({
  profileId: identity,
  profileDigest: digest,
  fieldCells: z.array(fieldCellSchema).min(1).max(256),
}).strict();
const universeSchema = z.object({
  universeId: identity,
  universeDigest: digest,
  eligibleCount: u64,
  eligibleSubjects: z.array(identity).max(4096),
}).strict();
const cutoffSchema = z.object({
  knowledgeAt: exactUtcInstantSchema,
  commitThrough: positiveU64.nullable(),
  chainSlot: u64.nullable(),
}).strict();
const factSchema = z.object({
  factId: identity,
  factDigest: digest,
  surfaceId: identity,
  sourceId: identity,
  subject: identity,
  field: identity,
  protection,
  observedAt: exactUtcInstantSchema,
  knownAt: exactUtcInstantSchema,
  commitSeq: positiveU64.nullable(),
}).strict();
const membershipSchema = z.object({
  subject: identity,
  membership,
  observedAt: exactUtcInstantSchema,
  evidenceDigest: digest,
}).strict();
const coverageSchema = z.object({
  surfaceId: identity,
  sourceId: identity,
  subject: identity,
  field: identity,
  factIds: z.array(identity).max(4096),
  state: coverageState,
  coverageDigest: digest,
}).strict();
const gapSchema = z.object({
  gapId: identity,
  surfaceId: identity,
  sourceId: identity,
  subject: identity,
  field: identity,
  reason: identity,
  since: exactUtcInstantSchema,
  until: exactUtcInstantSchema.nullable(),
  evidenceDigest: digest.nullable(),
}).strict();
const omissionSchema = z.object({ subject: identity, reason: identity, membership }).strict();

export const cockpitV2ManifestSchema = z.object({
  contract: z.literal("joshi.cockpit.v2.manifest"),
  schemaVersion: z.literal(2),
  surfaceProfile: profileSchema,
  observedUniverse: universeSchema,
  cutoff: cutoffSchema,
  sourceFacts: z.array(factSchema).max(4096),
  memberships: z.array(membershipSchema).max(4096),
  coverage: z.array(coverageSchema).min(1).max(65_536),
  gaps: z.array(gapSchema).max(65_536),
  renderedSubjects: z.array(identity).max(4096),
  omissions: z.array(omissionSchema).max(4096),
  orderingPolicy: identity,
  paginationPolicy: identity,
  authority,
  ceiling: z.literal("unverified_semantic"),
  semanticDigest: digest,
  containerDigest: digest,
}).strict();

const checkpointSchema = z.object({
  contract: z.literal("joshi.cockpit.v2.checkpoint"),
  schemaVersion: z.literal(2),
  profileDigest: digest,
  universeDigest: digest,
  cutoff: cutoffSchema,
  semanticDigest: digest,
  containerDigest: digest,
  checkpointDigest: digest,
  authority,
}).strict();

export const cockpitV2PublicationSchema = z.object({
  contract: z.literal("joshi.cockpit.v2.publication"),
  schemaVersion: z.literal(2),
  publicationId: identity,
  manifest: cockpitV2ManifestSchema,
  checkpoint: checkpointSchema,
  commitSeq: positiveU64,
  supersedesPublicationId: identity.nullable(),
  publicationDigest: digest,
  authority,
}).strict();

export const cockpitV2HeadSchema = z.object({
  contract: z.literal("joshi.cockpit.v2.head"),
  schemaVersion: z.literal(2),
  publicationId: identity,
  publicationDigest: digest,
  commitSeq: positiveU64,
  headDigest: digest,
  authority,
}).strict();

export const cockpitV2IndexEntrySchema = z.object({
  publicationId: identity,
  publicationDigest: digest,
  publicationBytesDigest: digest,
  publicationCommitSeq: positiveU64,
  headDigest: digest,
  headBytesDigest: digest,
  headCommitSeq: positiveU64,
  sourceOccurrenceId: identity,
  supersedesPublicationId: identity.nullable(),
  eligibleCount: u64,
  factCount: u64,
  gapCount: u64,
  ceiling: z.literal("unverified_semantic"),
}).strict();

export const cockpitV2IndexSchema = z.object({
  contract: z.literal("joshi.core.cockpit_v2_index"),
  schemaVersion: z.literal(1),
  authority,
  items: z.array(cockpitV2IndexEntrySchema).max(256),
}).strict();

export const cockpitV2OpenSchema = z.object({
  authority,
  contract: z.literal("joshi.core.cockpit_v2_open"),
  head: cockpitV2HeadSchema,
  headBytesDigest: digest,
  headCommitSeq: positiveU64,
  publication: cockpitV2PublicationSchema,
  publicationBytesDigest: digest,
  publicationCommitSeq: positiveU64,
  schemaVersion: z.literal(1),
  sourceOccurrenceId: identity,
}).strict();

const cockpitV2PresentedPublicationRefSchema = z.object({
  publicationId: identity,
  publicationDigest: digest,
  publicationBytesDigest: digest,
  publicationCommitSeq: positiveU64,
}).strict();

const cockpitV2PresentedHeadRefSchema = z.object({
  headDigest: digest,
  headBytesDigest: digest,
  headCommitSeq: positiveU64,
}).strict();

const cockpitV2BrowserViewportSchema = z.object({
  widthCssPx: positiveU64,
  heightCssPx: positiveU64,
  devicePixelRatioMilli: positiveU64,
}).strict();

export const cockpitV2BrowserPresentationClaimSchema = z.object({
  contract: z.literal("joshi.cockpit.v2.browser_presentation_claim"),
  schemaVersion: z.literal(1),
  idempotencyKey: identity,
  clientPresentationId: identity,
  browserPageId: identity,
  presentationSeq: positiveU64,
  publication: cockpitV2PresentedPublicationRefSchema,
  head: cockpitV2PresentedHeadRefSchema,
  sourceOccurrenceId: identity,
  renderedSubjects: z.array(identity).max(4096),
  renderedSubjectCount: u64,
  mountedAt: exactUtcInstantSchema,
  clientClockId: identity,
  monotonicNs: u64,
  viewport: cockpitV2BrowserViewportSchema,
  documentVisibility: z.enum(["visible", "hidden"]),
  documentHasFocus: z.boolean(),
  authority,
  ceiling: z.literal("browser_reported_not_pixel_verified"),
  claimDigest: digest,
}).strict();

export const cockpitV2BrowserPresentationReceiptSchema = z.object({
  contract: z.literal("joshi.core.cockpit_v2_browser_presentation_receipt"),
  schemaVersion: z.literal(1),
  catalogId: identity,
  catalogSchema: z.string().regex(/^joshi\.sqlite\.v[1-9][0-9]*$/),
  clientPresentationId: identity,
  claimDigest: digest,
  claimBytesDigest: digest,
  pairingSessionId: identity,
  publicationId: identity,
  storeCommitSeq: positiveU64,
  status: z.enum(["accepted", "idempotent"]),
  authority,
  ceiling: z.literal("durable_browser_report_only_not_pixel_verified"),
}).strict();

export type CockpitV2Manifest = z.infer<typeof cockpitV2ManifestSchema>;
export type CockpitV2Index = z.infer<typeof cockpitV2IndexSchema>;
export type CockpitV2IndexEntry = z.infer<typeof cockpitV2IndexEntrySchema>;
export type CockpitV2Open = z.infer<typeof cockpitV2OpenSchema>;
export type CockpitV2BrowserPresentationClaim = z.infer<typeof cockpitV2BrowserPresentationClaimSchema>;
export type CockpitV2BrowserPresentationReceipt = z.infer<typeof cockpitV2BrowserPresentationReceiptSchema>;
export type CockpitV2BrowserPresentationInput = Omit<CockpitV2BrowserPresentationClaim,
  "contract" | "schemaVersion" | "idempotencyKey" | "publication" | "head" | "sourceOccurrenceId"
  | "renderedSubjects" | "renderedSubjectCount" | "authority" | "ceiling" | "claimDigest">;

const zeroDigest = `sha256:${"0".repeat(64)}`;

export function digestCanonicalJson(value: unknown): string {
  return `sha256:${bytesToHex(sha256(new TextEncoder().encode(JSON.stringify(value))))}`;
}

function browserPresentationClaimMaterial(claim: CockpitV2BrowserPresentationClaim) {
  return {
    contract: claim.contract,
    schemaVersion: claim.schemaVersion,
    idempotencyKey: claim.idempotencyKey,
    clientPresentationId: claim.clientPresentationId,
    browserPageId: claim.browserPageId,
    presentationSeq: claim.presentationSeq,
    publication: claim.publication,
    head: claim.head,
    sourceOccurrenceId: claim.sourceOccurrenceId,
    renderedSubjects: claim.renderedSubjects,
    renderedSubjectCount: claim.renderedSubjectCount,
    mountedAt: claim.mountedAt,
    clientClockId: claim.clientClockId,
    monotonicNs: claim.monotonicNs,
    viewport: claim.viewport,
    documentVisibility: claim.documentVisibility,
    documentHasFocus: claim.documentHasFocus,
    authority: claim.authority,
    ceiling: claim.ceiling,
  };
}

export function digestCockpitV2BrowserPresentationClaim(
  claim: CockpitV2BrowserPresentationClaim,
): string {
  return digestCanonicalJson(browserPresentationClaimMaterial(claim));
}

function semanticMaterial(manifest: CockpitV2Manifest) {
  return {
    contract: manifest.contract,
    schemaVersion: manifest.schemaVersion,
    surfaceProfile: manifest.surfaceProfile,
    observedUniverse: manifest.observedUniverse,
    cutoff: manifest.cutoff,
    sourceFacts: manifest.sourceFacts,
    memberships: manifest.memberships,
    coverage: manifest.coverage,
    gaps: manifest.gaps,
    renderedSubjects: manifest.renderedSubjects,
    omissions: manifest.omissions,
    orderingPolicy: manifest.orderingPolicy,
    paginationPolicy: manifest.paginationPolicy,
    authority: manifest.authority,
    ceiling: manifest.ceiling,
  };
}

function sortedUnique(values: readonly string[], label: string): void {
  for (let index = 1; index < values.length; index += 1) {
    if (values[index - 1]! >= values[index]!) throw new Error(`${label} must be strictly sorted and unique`);
  }
}

function cellKey(surfaceId: string, sourceId: string, subject: string, field: string): string {
  return JSON.stringify([surfaceId, sourceId, subject, field]);
}

function assertManifest(manifest: CockpitV2Manifest): void {
  const semantic = semanticMaterial(manifest);
  if (digestCanonicalJson(semantic) !== manifest.semanticDigest) throw new Error("Cockpit V2 semantic digest mismatch");
  if (digestCanonicalJson({ semantic, semanticDigest: manifest.semanticDigest, containerDigest: zeroDigest }) !== manifest.containerDigest) {
    throw new Error("Cockpit V2 container digest mismatch");
  }
  const universe = manifest.observedUniverse;
  sortedUnique(universe.eligibleSubjects, "eligible subjects");
  if (BigInt(universe.eligibleCount) !== BigInt(universe.eligibleSubjects.length)) throw new Error("Cockpit V2 eligible count mismatch");
  if (digestCanonicalJson({
    domain: "joshi.cockpit.v2.observed_universe.v1",
    universeId: universe.universeId,
    eligibleCount: universe.eligibleCount,
    eligibleSubjects: universe.eligibleSubjects,
  }) !== universe.universeDigest) throw new Error("Cockpit V2 universe digest mismatch");

  sortedUnique(manifest.sourceFacts.map((fact) => fact.factId), "source facts");
  sortedUnique(manifest.memberships.map((entry) => entry.subject), "memberships");
  sortedUnique(manifest.gaps.map((gap) => gap.gapId), "gaps");
  sortedUnique(manifest.renderedSubjects, "rendered subjects");
  sortedUnique(manifest.omissions.map((entry) => JSON.stringify([entry.subject, entry.reason, entry.membership])), "omissions");
  sortedUnique(manifest.surfaceProfile.fieldCells.map((cell) => JSON.stringify([cell.surfaceId, cell.sourceId, cell.field])), "profile fields");
  sortedUnique(manifest.coverage.map((cell) => cellKey(cell.surfaceId, cell.sourceId, cell.subject, cell.field)), "coverage cells");

  const eligible = new Set(universe.eligibleSubjects);
  const membershipBySubject = new Map(manifest.memberships.map((entry) => [entry.subject, entry]));
  if (membershipBySubject.size !== eligible.size || [...eligible].some((subject) => !membershipBySubject.has(subject))) {
    throw new Error("Cockpit V2 memberships do not close the eligible universe");
  }
  const rendered = new Set(manifest.renderedSubjects);
  const omitted = new Set(manifest.omissions.map((entry) => entry.subject));
  if (rendered.size + omitted.size !== eligible.size
    || [...rendered].some((subject) => !eligible.has(subject) || omitted.has(subject))
    || [...omitted].some((subject) => !eligible.has(subject) || rendered.has(subject))) {
    throw new Error("Cockpit V2 rendered/omitted partition mismatch");
  }
  const declaredCells = new Set(manifest.surfaceProfile.fieldCells.map((cell) => JSON.stringify([cell.surfaceId, cell.sourceId, cell.field])));
  const expectedCoverage = new Set(manifest.surfaceProfile.fieldCells.flatMap((cell) => universe.eligibleSubjects.map((subject) => cellKey(cell.surfaceId, cell.sourceId, subject, cell.field))));
  const actualCoverage = new Set(manifest.coverage.map((cell) => cellKey(cell.surfaceId, cell.sourceId, cell.subject, cell.field)));
  if (expectedCoverage.size !== actualCoverage.size || [...expectedCoverage].some((cell) => !actualCoverage.has(cell))) {
    throw new Error("Cockpit V2 coverage does not close profile by eligible subject");
  }
  const cutoffCommit = manifest.cutoff.commitThrough === null ? null : BigInt(manifest.cutoff.commitThrough);
  const facts = new Map<string, typeof manifest.sourceFacts[number]>();
  for (const fact of manifest.sourceFacts) {
    if (fact.protection !== "public") throw new Error("Cockpit V2 publication contains a nonpublic fact");
    if (!eligible.has(fact.subject) || !declaredCells.has(JSON.stringify([fact.surfaceId, fact.sourceId, fact.field]))) {
      throw new Error("Cockpit V2 fact is outside the declared universe/profile");
    }
    if (fact.observedAt > fact.knownAt || fact.knownAt > manifest.cutoff.knowledgeAt) throw new Error("Cockpit V2 fact exceeds the knowledge cutoff");
    if (cutoffCommit !== null && (fact.commitSeq === null || BigInt(fact.commitSeq) > cutoffCommit)) throw new Error("Cockpit V2 fact exceeds the commit cutoff");
    facts.set(fact.factId, fact);
  }
  const referencedFacts = new Set<string>();
  for (const coverage of manifest.coverage) {
    sortedUnique(coverage.factIds, "coverage fact IDs");
    const matchingGaps = manifest.gaps.filter((gap) => cellKey(gap.surfaceId, gap.sourceId, gap.subject, gap.field) === cellKey(coverage.surfaceId, coverage.sourceId, coverage.subject, coverage.field));
    if (coverage.state === "complete" && (coverage.factIds.length === 0 || matchingGaps.length > 0)) throw new Error("Cockpit V2 complete coverage has no fact or carries a gap");
    for (const factId of coverage.factIds) {
      const fact = facts.get(factId);
      if (!fact || referencedFacts.has(factId)
        || cellKey(fact.surfaceId, fact.sourceId, fact.subject, fact.field) !== cellKey(coverage.surfaceId, coverage.sourceId, coverage.subject, coverage.field)) {
        throw new Error("Cockpit V2 fact/coverage closure mismatch");
      }
      referencedFacts.add(factId);
    }
  }
  if (referencedFacts.size !== facts.size) throw new Error("Cockpit V2 publication omits a source fact from coverage");
  for (const gap of manifest.gaps) {
    if (!actualCoverage.has(cellKey(gap.surfaceId, gap.sourceId, gap.subject, gap.field))
      || gap.since > manifest.cutoff.knowledgeAt
      || (gap.until !== null && (gap.until <= gap.since || gap.until > manifest.cutoff.knowledgeAt))) {
      throw new Error("Cockpit V2 gap exceeds its coverage/cutoff closure");
    }
  }
}

export function parseCockpitV2Index(input: unknown): CockpitV2Index {
  const index = cockpitV2IndexSchema.parse(input);
  for (let position = 0; position < index.items.length; position += 1) {
    const item = index.items[position]!;
    if (BigInt(item.publicationCommitSeq) >= BigInt(item.headCommitSeq)) throw new Error("Cockpit V2 index head does not follow its body");
    if (position > 0) {
      const previous = index.items[position - 1]!;
      if (BigInt(previous.headCommitSeq) > BigInt(item.headCommitSeq)
        || (previous.headCommitSeq === item.headCommitSeq && previous.publicationId >= item.publicationId)) {
        throw new Error("Cockpit V2 index is not in durable head order");
      }
    }
  }
  return index;
}

export function parseCockpitV2Open(input: unknown, expected?: CockpitV2IndexEntry): CockpitV2Open {
  const opened = cockpitV2OpenSchema.parse(input);
  assertManifest(opened.publication.manifest);
  const publication = opened.publication;
  const checkpoint = publication.checkpoint;
  if (checkpoint.profileDigest !== publication.manifest.surfaceProfile.profileDigest
    || checkpoint.universeDigest !== publication.manifest.observedUniverse.universeDigest
    || JSON.stringify(checkpoint.cutoff) !== JSON.stringify(publication.manifest.cutoff)
    || checkpoint.semanticDigest !== publication.manifest.semanticDigest
    || checkpoint.containerDigest !== publication.manifest.containerDigest
    || digestCanonicalJson([checkpoint.profileDigest, checkpoint.universeDigest, checkpoint.cutoff, checkpoint.semanticDigest, checkpoint.containerDigest]) !== checkpoint.checkpointDigest) {
    throw new Error("Cockpit V2 checkpoint does not close the manifest");
  }
  if (digestCanonicalJson({
    contract: publication.contract,
    schemaVersion: publication.schemaVersion,
    publicationId: publication.publicationId,
    manifest: publication.manifest,
    checkpoint: publication.checkpoint,
    commitSeq: publication.commitSeq,
    supersedesPublicationId: publication.supersedesPublicationId,
    authority: publication.authority,
  }) !== publication.publicationDigest) throw new Error("Cockpit V2 publication digest mismatch");
  if (digestCanonicalJson({
    contract: opened.head.contract,
    schemaVersion: opened.head.schemaVersion,
    publicationId: opened.head.publicationId,
    publicationDigest: opened.head.publicationDigest,
    commitSeq: opened.head.commitSeq,
    authority: opened.head.authority,
  }) !== opened.head.headDigest) throw new Error("Cockpit V2 head digest mismatch");
  if (digestCanonicalJson(publication) !== opened.publicationBytesDigest
    || digestCanonicalJson(opened.head) !== opened.headBytesDigest) throw new Error("Cockpit V2 exact byte digest mismatch");
  if (publication.publicationId !== opened.head.publicationId
    || publication.publicationDigest !== opened.head.publicationDigest
    || publication.commitSeq !== opened.head.commitSeq
    || publication.commitSeq !== opened.publicationCommitSeq
    || BigInt(opened.publicationCommitSeq) >= BigInt(opened.headCommitSeq)) {
    throw new Error("Cockpit V2 body/head/store commit lineage mismatch");
  }
  if (expected && (expected.publicationId !== publication.publicationId
    || expected.publicationDigest !== publication.publicationDigest
    || expected.publicationBytesDigest !== opened.publicationBytesDigest
    || expected.publicationCommitSeq !== opened.publicationCommitSeq
    || expected.headDigest !== opened.head.headDigest
    || expected.headBytesDigest !== opened.headBytesDigest
    || expected.headCommitSeq !== opened.headCommitSeq
    || expected.sourceOccurrenceId !== opened.sourceOccurrenceId
    || expected.supersedesPublicationId !== publication.supersedesPublicationId
    || BigInt(expected.eligibleCount) !== BigInt(publication.manifest.observedUniverse.eligibleSubjects.length)
    || BigInt(expected.factCount) !== BigInt(publication.manifest.sourceFacts.length)
    || BigInt(expected.gapCount) !== BigInt(publication.manifest.gaps.length))) {
    throw new Error("Opened Cockpit V2 publication differs from the selected index entry");
  }
  return opened;
}

function assertBrowserPresentationClaim(
  claim: CockpitV2BrowserPresentationClaim,
  opened?: CockpitV2Open,
): void {
  sortedUnique(claim.renderedSubjects, "browser presentation rendered subjects");
  if (BigInt(claim.renderedSubjectCount) !== BigInt(claim.renderedSubjects.length)) {
    throw new Error("Cockpit V2 browser presentation rendered subject count mismatch");
  }
  if (claim.idempotencyKey !== `browser-presentation:${claim.browserPageId}:${claim.presentationSeq}`) {
    throw new Error("Cockpit V2 browser presentation idempotency key mismatch");
  }
  if (BigInt(claim.publication.publicationCommitSeq) >= BigInt(claim.head.headCommitSeq)) {
    throw new Error("Cockpit V2 browser presentation head commit must follow its publication commit");
  }
  const width = BigInt(claim.viewport.widthCssPx);
  const height = BigInt(claim.viewport.heightCssPx);
  const devicePixelRatio = BigInt(claim.viewport.devicePixelRatioMilli);
  if (width > 32_768n || height > 32_768n || devicePixelRatio < 100n || devicePixelRatio > 10_000n) {
    throw new Error("Cockpit V2 browser presentation viewport is outside the bounded contract");
  }
  if (digestCockpitV2BrowserPresentationClaim(claim) !== claim.claimDigest) {
    throw new Error("Cockpit V2 browser presentation claim digest mismatch");
  }
  if (opened && (claim.publication.publicationId !== opened.publication.publicationId
    || claim.publication.publicationDigest !== opened.publication.publicationDigest
    || claim.publication.publicationBytesDigest !== opened.publicationBytesDigest
    || claim.publication.publicationCommitSeq !== opened.publicationCommitSeq
    || claim.head.headDigest !== opened.head.headDigest
    || claim.head.headBytesDigest !== opened.headBytesDigest
    || claim.head.headCommitSeq !== opened.headCommitSeq
    || claim.sourceOccurrenceId !== opened.sourceOccurrenceId
    || JSON.stringify(claim.renderedSubjects) !== JSON.stringify(opened.publication.manifest.renderedSubjects)
    || claim.mountedAt < opened.publication.manifest.cutoff.knowledgeAt)) {
    throw new Error("Cockpit V2 browser presentation claim does not match the exact opened publication");
  }
}

export function parseCockpitV2BrowserPresentationClaim(
  input: unknown,
  opened?: CockpitV2Open,
): CockpitV2BrowserPresentationClaim {
  const claim = cockpitV2BrowserPresentationClaimSchema.parse(input);
  assertBrowserPresentationClaim(claim, opened);
  return claim;
}

export function parseCockpitV2BrowserPresentationReceipt(
  input: unknown,
  claimInput: CockpitV2BrowserPresentationClaim,
  pairingSessionId: string,
): CockpitV2BrowserPresentationReceipt {
  const claim = parseCockpitV2BrowserPresentationClaim(claimInput);
  const receipt = cockpitV2BrowserPresentationReceiptSchema.parse(input);
  const catalogVersion = BigInt(receipt.catalogSchema.slice("joshi.sqlite.v".length));
  if (catalogVersion < 21n
    || receipt.clientPresentationId !== claim.clientPresentationId
    || receipt.claimDigest !== claim.claimDigest
    || receipt.claimBytesDigest !== digestCanonicalJson(claim)
    || receipt.pairingSessionId !== pairingSessionId
    || receipt.publicationId !== claim.publication.publicationId
    || BigInt(receipt.storeCommitSeq) <= BigInt(claim.head.headCommitSeq)) {
    throw new Error("Cockpit V2 browser presentation receipt does not close the exact paired claim");
  }
  return receipt;
}

export function buildCockpitV2BrowserPresentationClaim(
  openedInput: CockpitV2Open,
  input: CockpitV2BrowserPresentationInput,
): CockpitV2BrowserPresentationClaim {
  const opened = parseCockpitV2Open(openedInput);
  const unsealed = {
    contract: "joshi.cockpit.v2.browser_presentation_claim" as const,
    schemaVersion: 1 as const,
    idempotencyKey: `browser-presentation:${input.browserPageId}:${input.presentationSeq}`,
    clientPresentationId: input.clientPresentationId,
    browserPageId: input.browserPageId,
    presentationSeq: input.presentationSeq,
    publication: {
      publicationId: opened.publication.publicationId,
      publicationDigest: opened.publication.publicationDigest,
      publicationBytesDigest: opened.publicationBytesDigest,
      publicationCommitSeq: opened.publicationCommitSeq,
    },
    head: {
      headDigest: opened.head.headDigest,
      headBytesDigest: opened.headBytesDigest,
      headCommitSeq: opened.headCommitSeq,
    },
    sourceOccurrenceId: opened.sourceOccurrenceId,
    renderedSubjects: [...opened.publication.manifest.renderedSubjects],
    renderedSubjectCount: String(opened.publication.manifest.renderedSubjects.length),
    mountedAt: input.mountedAt,
    clientClockId: input.clientClockId,
    monotonicNs: input.monotonicNs,
    viewport: input.viewport,
    documentVisibility: input.documentVisibility,
    documentHasFocus: input.documentHasFocus,
    authority: "read_only_no_execution" as const,
    ceiling: "browser_reported_not_pixel_verified" as const,
    claimDigest: zeroDigest,
  };
  const claim: CockpitV2BrowserPresentationClaim = {
    ...unsealed,
    claimDigest: digestCockpitV2BrowserPresentationClaim(unsealed),
  };
  return parseCockpitV2BrowserPresentationClaim(claim, opened);
}
