import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { z } from "zod";

import { exactUtcInstantSchema, unixSecondsToNumber } from "../contract/instant";

const asciiIdentityPattern = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;
const sha256DigestPattern = /^sha256:[0-9a-f]{64}$/;
const wireU64Pattern = /^(0|[1-9][0-9]*)$/;
const ppmPattern = /^(0|[1-9][0-9]{0,5}|1000000)$/;

const exactString = (maximum: number) => z.string().min(1).max(maximum).refine((value) => value === value.trim(), "must not have surrounding whitespace");
const asciiIdentity = z.string().min(1).max(512).regex(asciiIdentityPattern);
const digest = z.string().regex(sha256DigestPattern);
const wireU64 = z.string().regex(wireU64Pattern);
const instant = exactUtcInstantSchema;

const subject = z.object({
  kind: asciiIdentity,
  key: asciiIdentity,
}).strict();

const sceneReference = z.object({
  sceneId: asciiIdentity,
  viewDigest: digest,
}).strict();

const clientClock = z.object({
  clockId: asciiIdentity,
  monotonicNs: wireU64,
}).strict();

const context = z.object({
  uiLabel: exactString(120),
  uiLabelVersion: wireU64,
  confidencePpm: z.string().regex(ppmPattern).nullable(),
  urgency: z.enum(["low", "normal", "high", "immediate"]).nullable(),
  whyNow: exactString(800).nullable(),
  note: exactString(4_000).nullable(),
}).strict();

const episodeReference = z.object({ episodeId: asciiIdentity }).strict();
const choiceSubject = z.object({ kind: z.literal("candidate"), key: asciiIdentity }).strict();

const recordFocusPayload = z.object({
  context,
  dwellMilliseconds: wireU64.nullable(),
}).strict();

const nominateCandidatePayload = z.object({
  context,
  nomination: exactString(240),
}).strict();

const requestHotScopePayload = z.object({
  context,
  scope: z.object({
    family: asciiIdentity,
    subject,
  }).strict(),
}).strict();

const recordDispositionPayload = z.object({
  context,
  disposition: exactString(240),
  provisional: z.literal(true),
}).strict();

const recordCrackleFamilyPayload = z.object({
  context,
  crackleFamily: exactString(240),
  provisional: z.literal(true),
}).strict();

const recordGesturePayload = z.object({
  context,
  gestureLabel: exactString(240),
  episodeRef: episodeReference.nullable(),
  observedExternally: z.boolean(),
}).strict();

const timeAnchor = z.object({
  anchorKind: z.literal("time"),
  at: instant,
}).strict();

const pointAnchor = z.object({
  anchorKind: z.literal("point"),
  sampleId: asciiIdentity,
  at: instant,
}).strict();

const rangeAnchor = z.object({
  anchorKind: z.literal("range"),
  startSampleId: asciiIdentity,
  endSampleId: asciiIdentity,
  startAt: instant,
  endAt: instant,
}).strict().superRefine((value, refinement) => {
  if (Date.parse(value.startAt) > Date.parse(value.endAt)) {
    refinement.addIssue({ code: "custom", message: "chart range must be ordered", path: ["endAt"] });
  }
});

export const chartAnchor = z.discriminatedUnion("anchorKind", [timeAnchor, pointAnchor, rangeAnchor]);

const recordAnnotationPayload = z.object({
  context,
  annotationId: asciiIdentity,
  chart: z.object({
    candidateId: asciiIdentity,
    seriesId: asciiIdentity,
    anchor: chartAnchor,
  }).strict(),
}).strict();

const recordChoiceSetPayload = z.object({
  context,
  choiceSet: z.object({
    setKind: z.enum(["surfaced", "filtered", "viewport", "interacted", "compared", "pointed"]),
    subjects: z.array(choiceSubject).min(1).max(1_000),
    selectedSubject: choiceSubject.nullable(),
  }).strict(),
}).strict().superRefine((value, refinement) => {
  const identities = value.choiceSet.subjects.map((item) => `${item.kind}\0${item.key}`);
  const canonical = [...identities].sort();
  if (new Set(identities).size !== identities.length) {
    refinement.addIssue({ code: "custom", message: "choice subjects must be unique", path: ["choiceSet", "subjects"] });
  }
  if (canonical.some((identity, index) => identity !== identities[index])) {
    refinement.addIssue({ code: "custom", message: "choice subjects must use canonical ASCII order", path: ["choiceSet", "subjects"] });
  }
  if (value.choiceSet.selectedSubject && !identities.includes(`candidate\0${value.choiceSet.selectedSubject.key}`)) {
    refinement.addIssue({ code: "custom", message: "selected subject must be a member of the choice set", path: ["choiceSet", "selectedSubject"] });
  }
});

const recordPostActionReportPayload = z.object({
  context,
  reportId: asciiIdentity,
  episodeRef: episodeReference.nullable(),
  relatedCommandId: asciiIdentity.nullable(),
  actionObservedAt: instant.nullable(),
  outcomeHidden: z.boolean(),
}).strict();

const linkInterviewPayload = z.object({
  context,
  interviewId: asciiIdentity,
  timing: z.enum(["quick", "later"]),
  outcomeVisibility: z.enum(["hidden", "aware"]),
  episodeRef: episodeReference.nullable(),
  sourceCommandIds: z.array(asciiIdentity).max(100),
}).strict().superRefine((value, refinement) => {
  if (new Set(value.sourceCommandIds).size !== value.sourceCommandIds.length) {
    refinement.addIssue({ code: "custom", message: "source command IDs must be unique", path: ["sourceCommandIds"] });
  }
  const canonical = [...value.sourceCommandIds].sort();
  if (canonical.some((commandId, index) => commandId !== value.sourceCommandIds[index])) {
    refinement.addIssue({ code: "custom", message: "source command IDs must use canonical ASCII order", path: ["sourceCommandIds"] });
  }
});

const compensateCommandPayload = z.object({
  context,
  compensatesCommandId: asciiIdentity,
  reason: exactString(800),
}).strict();

const commandHead = {
  contract: z.literal("joshi.operator.command"),
  schemaVersion: z.literal(1),
  commandId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  clientSessionId: asciiIdentity,
  clientCommandSeq: wireU64,
  scene: sceneReference,
  issuedAt: instant,
  clientClock,
} as const;

const presentationReference = z.object({
  presentationId: asciiIdentity,
  presentationDigest: digest,
  assignmentId: asciiIdentity,
}).strict();

const cockpitPublicationReference = z.object({
  cockpitPublicationId: asciiIdentity,
  cockpitPublicationDigest: digest,
}).strict();

const commandHeadV2 = {
  ...commandHead,
  schemaVersion: z.literal(2),
  presentation: presentationReference,
  cockpitPublication: cockpitPublicationReference,
} as const;

function commandVariant<const Kind extends string, Payload extends z.ZodType>(kind: Kind, payload: Payload) {
  return z.object({
    ...commandHead,
    commandKind: z.literal(kind),
    subject,
    payload,
    authorityClass: z.literal("evidence_only"),
    effectCeiling: z.literal("observe_only"),
  }).strict();
}

function commandVariantV2<const Kind extends string, Payload extends z.ZodType>(kind: Kind, payload: Payload) {
  return z.object({
    ...commandHeadV2,
    commandKind: z.literal(kind),
    subject,
    payload,
    authorityClass: z.literal("evidence_only"),
    effectCeiling: z.literal("observe_only"),
  }).strict();
}

/**
 * The eleven frozen kind-specific payload shapes, addressable by wire kind.
 *
 * Exported so the durable read-back path (`operator/readback.ts`) validates a payload the store
 * returns against the exact same schema the write path validated it with, instead of growing a
 * second, drifting description of the same bytes.
 */
export const operatorPayloadSchemas = {
  record_focus: recordFocusPayload,
  nominate_candidate: nominateCandidatePayload,
  request_hot_scope: requestHotScopePayload,
  record_disposition: recordDispositionPayload,
  record_crackle_family: recordCrackleFamilyPayload,
  record_gesture: recordGesturePayload,
  record_annotation: recordAnnotationPayload,
  record_choice_set: recordChoiceSetPayload,
  record_post_action_report: recordPostActionReportPayload,
  link_interview: linkInterviewPayload,
  compensate_command: compensateCommandPayload,
} as const;

/** Wire building blocks shared with the read-back contract. */
export const wireIdentitySchema = asciiIdentity;
export const wireDigestSchema = digest;
export const wireU64Schema = wireU64;

export const operatorCommandV1Schema = z.discriminatedUnion("commandKind", [
  commandVariant("record_focus", recordFocusPayload),
  commandVariant("nominate_candidate", nominateCandidatePayload),
  commandVariant("request_hot_scope", requestHotScopePayload),
  commandVariant("record_disposition", recordDispositionPayload),
  commandVariant("record_crackle_family", recordCrackleFamilyPayload),
  commandVariant("record_gesture", recordGesturePayload),
  commandVariant("record_annotation", recordAnnotationPayload),
  commandVariant("record_choice_set", recordChoiceSetPayload),
  commandVariant("record_post_action_report", recordPostActionReportPayload),
  commandVariant("link_interview", linkInterviewPayload),
  commandVariant("compensate_command", compensateCommandPayload),
]);

export const operatorCommandV2Schema = z.discriminatedUnion("commandKind", [
  commandVariantV2("record_focus", recordFocusPayload),
  commandVariantV2("nominate_candidate", nominateCandidatePayload),
  commandVariantV2("request_hot_scope", requestHotScopePayload),
  commandVariantV2("record_disposition", recordDispositionPayload),
  commandVariantV2("record_crackle_family", recordCrackleFamilyPayload),
  commandVariantV2("record_gesture", recordGesturePayload),
  commandVariantV2("record_annotation", recordAnnotationPayload),
  commandVariantV2("record_choice_set", recordChoiceSetPayload),
  commandVariantV2("record_post_action_report", recordPostActionReportPayload),
  commandVariantV2("link_interview", linkInterviewPayload),
  commandVariantV2("compensate_command", compensateCommandPayload),
]);

export const operatorCommandSchema = z.union([operatorCommandV1Schema, operatorCommandV2Schema]);

export const commandReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.command_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  commandId: asciiIdentity,
  commandPayloadDigest: digest,
  commandDigest: digest,
  scene: sceneReference,
  commitSeq: wireU64,
  status: z.enum(["accepted", "idempotent"]),
}).strict();

export const commandReceiptV2Schema = z.object({
  contract: z.literal("joshi.store.command_receipt"),
  schemaVersion: z.literal(2),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  commandId: asciiIdentity,
  commandPayloadDigest: digest,
  commandDigest: digest,
  scene: sceneReference,
  presentation: presentationReference,
  cockpitPublication: cockpitPublicationReference,
  commitSeq: wireU64,
  status: z.enum(["accepted", "idempotent"]),
}).strict();

export const commandReceiptSchema = z.union([commandReceiptV1Schema, commandReceiptV2Schema]);

export type OperatorCommandV1 = z.infer<typeof operatorCommandV1Schema>;
export type OperatorCommandV2 = z.infer<typeof operatorCommandV2Schema>;
export type OperatorCommand = OperatorCommandV1 | OperatorCommandV2;
export type OperatorCommandKind = OperatorCommand["commandKind"];
export type OperatorPayload = OperatorCommand["payload"];
export type CommandReceiptV1 = z.infer<typeof commandReceiptV1Schema>;
export type CommandReceiptV2 = z.infer<typeof commandReceiptV2Schema>;
export type CommandReceipt = CommandReceiptV1 | CommandReceiptV2;
export type ChartAnchor = z.infer<typeof chartAnchor>;
export type CaptureContext = z.infer<typeof context>;

const encoder = new TextEncoder();

function digestBytes(bytes: Uint8Array): string {
  return `sha256:${bytesToHex(sha256(bytes))}`;
}

export function canonicalOperatorCommand(command: OperatorCommand): string {
  return JSON.stringify(operatorCommandSchema.parse(command));
}

export function canonicalOperatorPayload(command: OperatorCommand): string {
  return JSON.stringify(operatorCommandSchema.parse(command).payload);
}

export function digestOperatorCommand(command: OperatorCommand): string {
  return digestBytes(encoder.encode(canonicalOperatorCommand(command)));
}

export function digestOperatorPayload(command: OperatorCommand): string {
  return digestBytes(encoder.encode(canonicalOperatorPayload(command)));
}

export function parseCommandReceiptV1(input: unknown): CommandReceiptV1 {
  return commandReceiptV1Schema.parse(input);
}

export function parseCommandReceipt(input: unknown): CommandReceipt {
  return commandReceiptSchema.parse(input);
}

export function assertReceiptMatchesCommand(receipt: CommandReceiptV1, command: OperatorCommandV1): void {
  if (receipt.commandId !== command.commandId) throw new Error("operator receipt command ID mismatch");
  if (receipt.scene.sceneId !== command.scene.sceneId || receipt.scene.viewDigest !== command.scene.viewDigest) {
    throw new Error("operator receipt scene reference mismatch");
  }
  if (receipt.commandPayloadDigest !== digestOperatorPayload(command)) throw new Error("operator receipt payload digest mismatch");
  if (receipt.commandDigest !== digestOperatorCommand(command)) throw new Error("operator receipt command digest mismatch");
}

export function assertAnyReceiptMatchesCommand(receipt: CommandReceipt, command: OperatorCommand): void {
  if (receipt.schemaVersion !== command.schemaVersion) throw new Error("operator receipt version mismatch");
  if (receipt.commandId !== command.commandId) throw new Error("operator receipt command ID mismatch");
  if (receipt.scene.sceneId !== command.scene.sceneId || receipt.scene.viewDigest !== command.scene.viewDigest) {
    throw new Error("operator receipt scene reference mismatch");
  }
  if (receipt.schemaVersion === 2 && command.schemaVersion === 2) {
    if (receipt.presentation.presentationId !== command.presentation.presentationId
      || receipt.presentation.presentationDigest !== command.presentation.presentationDigest
      || receipt.presentation.assignmentId !== command.presentation.assignmentId) {
      throw new Error("operator receipt presentation reference mismatch");
    }
    if (receipt.cockpitPublication.cockpitPublicationId !== command.cockpitPublication.cockpitPublicationId
      || receipt.cockpitPublication.cockpitPublicationDigest !== command.cockpitPublication.cockpitPublicationDigest) {
      throw new Error("operator receipt cockpit publication reference mismatch");
    }
  }
  if (receipt.commandPayloadDigest !== digestOperatorPayload(command)) throw new Error("operator receipt payload digest mismatch");
  if (receipt.commandDigest !== digestOperatorCommand(command)) throw new Error("operator receipt command digest mismatch");
}

export function exactUtcNow(now: Date = new Date()): string {
  return now.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z");
}

export function chartInstant(timeUnix: string): string {
  return exactUtcNow(new Date(unixSecondsToNumber(timeUnix) * 1_000));
}
