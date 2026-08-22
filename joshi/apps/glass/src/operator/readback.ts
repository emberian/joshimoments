import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";
import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";
import { glassPairingSession, type MemoryOnlyPairingSession } from "../security/pairing";
import {
  operatorPayloadSchemas,
  wireDigestSchema,
  wireIdentitySchema,
  wireU64Schema,
  type OperatorCommandKind,
  type OperatorPayload,
} from "./contract";

/**
 * Reading durable operator acts back out of the catalog.
 *
 * `GET /api/v1/operator/commands?sceneId=…` is the journal's query path and the held rail's
 * reload path in one route: every evidence act — hold, note, journal entry, disposition — was
 * appended through one POST route, so one read route returns them all, in commit order, with the
 * exact retained payload bytes. This module renders nothing; it validates the wire against the
 * same frozen payload schemas the write path used and hands typed records to the surface.
 */
export const MAX_OPERATOR_READBACK_BYTES = 4 * 1024 * 1024;

const readbackCommandSchema = z.object({
  commandId: wireIdentitySchema,
  commitSeq: wireU64Schema,
  scene: z.object({
    sceneId: wireIdentitySchema,
    // `null` only when the stored command names a scene row the catalog no longer joins; the
    // surface renders that as a stated gap, never as a digest.
    viewDigest: wireDigestSchema.nullable(),
  }).strict(),
  clientSessionId: wireIdentitySchema,
  clientCommandSeq: wireU64Schema,
  idempotencyKey: wireIdentitySchema,
  commandKind: z.enum([
    "record_focus",
    "nominate_candidate",
    "request_hot_scope",
    "record_disposition",
    "record_crackle_family",
    "record_gesture",
    "record_annotation",
    "record_choice_set",
    "record_post_action_report",
    "link_interview",
    "compensate_command",
  ]),
  subject: z.object({ kind: wireIdentitySchema, key: wireIdentitySchema }).strict(),
  issuedAt: exactUtcInstantSchema,
  receivedAt: exactUtcInstantSchema,
  clientClockId: wireIdentitySchema,
  authorityClass: z.literal("evidence_only"),
  effectCeiling: z.literal("observe_only"),
  payload: z.unknown(),
}).strict();

const readbackSchema = z.object({
  contract: z.literal("joshi.core.operator_command_readback"),
  schemaVersion: z.literal(1),
  authority: z.literal("read_only_no_execution"),
  sceneId: wireIdentitySchema,
  sceneRetention: z.enum(["durable", "served_not_yet_durable"]),
  commands: z.array(readbackCommandSchema),
}).strict();

/** One durable operator act as the catalog returned it, with its payload validated per kind. */
export type DurableOperatorCommand = Omit<z.infer<typeof readbackCommandSchema>, "payload"> & {
  commandKind: OperatorCommandKind;
  payload: OperatorPayload;
};

export type DurableSceneCommands = {
  sceneId: string;
  /**
   * `durable` when the store retains the scene; `served_not_yet_durable` when the core derived
   * and is serving it but no act has made it durable yet. Kept apart so an empty list is never
   * read as "nothing was ever said".
   */
  sceneRetention: "durable" | "served_not_yet_durable";
  commands: DurableOperatorCommand[];
};

/**
 * Either the catalog's answer or the stated reason there cannot be one.
 *
 * `no_catalog` is not a failure: an offline-fixture cockpit has no durable catalog behind it, and
 * saying so is different from a loopback read that failed (which throws and is rendered as its
 * own explicit state by the hook).
 */
export type DurableReadbackAnswer =
  | { state: "read"; answer: DurableSceneCommands }
  | { state: "no_catalog"; absence: string };

export interface OperatorCommandReader {
  readonly kind: "offline_fixture" | "loopback";
  listSceneCommands(sceneId: string, signal?: AbortSignal): Promise<DurableReadbackAnswer>;
}

function parseReadbackBody(body: string, requestedSceneId: string): DurableSceneCommands {
  const wireError = validateJsonWithoutDuplicateKeys(body, false);
  if (wireError !== undefined) throw new Error(`invalid operator readback JSON: ${wireError}`);
  const decoded = JSON.parse(body, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") {
      throw new Error(`forbidden operator readback JSON key: ${key}`);
    }
    return value;
  }) as unknown;
  const envelope = readbackSchema.parse(decoded);
  if (envelope.sceneId !== requestedSceneId) {
    throw new Error("operator readback answered for a different scene than was requested");
  }
  const commands = envelope.commands.map((command): DurableOperatorCommand => ({
    ...command,
    payload: operatorPayloadSchemas[command.commandKind].parse(command.payload) as OperatorPayload,
  }));
  return {
    sceneId: envelope.sceneId,
    sceneRetention: envelope.sceneRetention,
    commands,
  };
}

async function readBoundedUtf8(response: Response): Promise<string> {
  const declaredLength = response.headers.get("Content-Length");
  if (declaredLength !== null && Number(declaredLength) > MAX_OPERATOR_READBACK_BYTES) {
    throw new Error("operator readback exceeds the browser response bound");
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_OPERATOR_READBACK_BYTES) {
      throw new Error("operator readback exceeds the browser response bound");
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_OPERATOR_READBACK_BYTES) {
      await reader.cancel("operator readback response bound exceeded");
      throw new Error("operator readback exceeds the browser response bound");
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

/**
 * A cockpit with no durable catalog behind it states exactly that.
 *
 * The offline fixture keeps this browser session's acts in the session journal already; what it
 * cannot do is answer for a catalog, and pretending an empty answer would be worse than saying
 * why there is none.
 */
export class OfflineFixtureOperatorReader implements OperatorCommandReader {
  readonly kind = "offline_fixture" as const;

  async listSceneCommands(): Promise<DurableReadbackAnswer> {
    return Promise.resolve({
      state: "no_catalog",
      absence:
        "This cockpit is running on the offline fixture, so no durable catalog stands behind it "
        + "and nothing can be read back. Acts recorded in this browser session are listed below; "
        + "an absent catalog answer is not evidence that a real catalog holds nothing.",
    });
  }
}

export class LoopbackOperatorReader implements OperatorCommandReader {
  readonly kind = "loopback" as const;
  private readonly baseUrl: URL;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(
    baseUrl: string,
    pairingSession: MemoryOnlyPairingSession = glassPairingSession,
    requireSameOrigin = false,
  ) {
    const parsed = new URL(baseUrl);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    if (parsed.protocol !== "http:" || !loopbackHosts.has(parsed.hostname)) {
      throw new Error("operator core URL must be an explicit HTTP loopback address");
    }
    if (requireSameOrigin && parsed.origin !== window.location.origin) {
      throw new Error("operator readback transport must use the exact page origin");
    }
    this.baseUrl = parsed;
    this.pairingSession = pairingSession;
  }

  async listSceneCommands(sceneId: string, signal?: AbortSignal): Promise<DurableReadbackAnswer> {
    const url = new URL("/api/v1/operator/commands", this.baseUrl);
    url.searchParams.set("sceneId", sceneId);
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.pairingSession.paired()) {
      headers["X-Joshi-Pairing-Token"] = this.pairingSession.authorizationHeader("cockpit_read");
    }
    const response = await fetch(url, {
      ...(signal ? { signal } : {}),
      credentials: "omit",
      cache: "no-store",
      headers,
    });
    if (!response.ok) throw new Error(`operator readback request failed (${response.status})`);
    return { state: "read", answer: parseReadbackBody(await readBoundedUtf8(response), sceneId) };
  }
}

export function configuredOperatorReader(): OperatorCommandReader {
  const loopbackUrl = import.meta.env.VITE_JOSHI_CORE_URL as string | undefined;
  return loopbackUrl ? new LoopbackOperatorReader(loopbackUrl) : new OfflineFixtureOperatorReader();
}
