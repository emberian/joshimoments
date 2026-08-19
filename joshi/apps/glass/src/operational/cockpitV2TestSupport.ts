import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  cockpitV2ManifestSchema,
  digestCanonicalJson,
  type CockpitV2Index,
  type CockpitV2Manifest,
  type CockpitV2Open,
} from "./cockpitV2";

export const fixture = (name: string): unknown => JSON.parse(readFileSync(
  resolve(process.cwd(), `../../fixtures/publication/${name}`),
  "utf8",
));

export const fixtureText = (name: string): string => readFileSync(
  resolve(process.cwd(), `../../fixtures/publication/${name}`),
  "utf8",
);

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

export function sealCockpitV2(input: unknown): { opened: CockpitV2Open; index: CockpitV2Index } {
  const manifest = cockpitV2ManifestSchema.parse(structuredClone(input));
  manifest.observedUniverse.universeDigest = digestCanonicalJson({
    domain: "joshi.cockpit.v2.observed_universe.v1",
    universeId: manifest.observedUniverse.universeId,
    eligibleCount: manifest.observedUniverse.eligibleCount,
    eligibleSubjects: manifest.observedUniverse.eligibleSubjects,
  });
  const semantic = semanticMaterial(manifest);
  manifest.semanticDigest = digestCanonicalJson(semantic);
  manifest.containerDigest = digestCanonicalJson({
    semantic,
    semanticDigest: manifest.semanticDigest,
    containerDigest: `sha256:${"0".repeat(64)}`,
  });
  const checkpoint = {
    contract: "joshi.cockpit.v2.checkpoint" as const,
    schemaVersion: 2 as const,
    profileDigest: manifest.surfaceProfile.profileDigest,
    universeDigest: manifest.observedUniverse.universeDigest,
    cutoff: manifest.cutoff,
    semanticDigest: manifest.semanticDigest,
    containerDigest: manifest.containerDigest,
    checkpointDigest: "",
    authority: "read_only_no_execution" as const,
  };
  checkpoint.checkpointDigest = digestCanonicalJson([
    checkpoint.profileDigest,
    checkpoint.universeDigest,
    checkpoint.cutoff,
    checkpoint.semanticDigest,
    checkpoint.containerDigest,
  ]);
  const publication = {
    contract: "joshi.cockpit.v2.publication" as const,
    schemaVersion: 2 as const,
    publicationId: "cockpit-v2-g0-1",
    manifest,
    checkpoint,
    commitSeq: "11",
    supersedesPublicationId: null,
    publicationDigest: "",
    authority: "read_only_no_execution" as const,
  };
  publication.publicationDigest = digestCanonicalJson({
    contract: publication.contract,
    schemaVersion: publication.schemaVersion,
    publicationId: publication.publicationId,
    manifest: publication.manifest,
    checkpoint: publication.checkpoint,
    commitSeq: publication.commitSeq,
    supersedesPublicationId: publication.supersedesPublicationId,
    authority: publication.authority,
  });
  const head = {
    contract: "joshi.cockpit.v2.head" as const,
    schemaVersion: 2 as const,
    publicationId: publication.publicationId,
    publicationDigest: publication.publicationDigest,
    commitSeq: publication.commitSeq,
    headDigest: "",
    authority: "read_only_no_execution" as const,
  };
  head.headDigest = digestCanonicalJson({
    contract: head.contract,
    schemaVersion: head.schemaVersion,
    publicationId: head.publicationId,
    publicationDigest: head.publicationDigest,
    commitSeq: head.commitSeq,
    authority: head.authority,
  });
  const opened: CockpitV2Open = {
    authority: "read_only_no_execution",
    contract: "joshi.core.cockpit_v2_open",
    head,
    headBytesDigest: digestCanonicalJson(head),
    headCommitSeq: "12",
    publication,
    publicationBytesDigest: digestCanonicalJson(publication),
    publicationCommitSeq: publication.commitSeq,
    schemaVersion: 1,
    sourceOccurrenceId: "source-occurrence-vector-1",
  };
  const index: CockpitV2Index = {
    contract: "joshi.core.cockpit_v2_index",
    schemaVersion: 1,
    authority: "read_only_no_execution",
    items: [{
      publicationId: publication.publicationId,
      publicationDigest: publication.publicationDigest,
      publicationBytesDigest: opened.publicationBytesDigest,
      publicationCommitSeq: publication.commitSeq,
      headDigest: head.headDigest,
      headBytesDigest: opened.headBytesDigest,
      headCommitSeq: opened.headCommitSeq,
      sourceOccurrenceId: opened.sourceOccurrenceId,
      supersedesPublicationId: null,
      eligibleCount: manifest.observedUniverse.eligibleCount,
      factCount: String(manifest.sourceFacts.length),
      gapCount: String(manifest.gaps.length),
      ceiling: "unverified_semantic",
    }],
  };
  return { opened, index };
}
