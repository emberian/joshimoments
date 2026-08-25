import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";
import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";
import { candidateSchema, replayModeSchema } from "../contract/v1";

/**
 * One candidate sliced verbatim out of an immutable scene:
 * `GET /api/v1/glass/scenes/{scene_id}/candidates/{candidate_id}` (cockpit_read).
 *
 * The core borrows the candidate bytes from the canonical view — never re-serialized — and
 * stamps `viewDigest` with the FULL view's digest, so a slice is always traceable to the
 * exact scene it was cut from. A slice is a read projection only: operator acts keep binding
 * to the scene id and the full view digest, never to a slice.
 *
 * Three non-answers, kept apart:
 * - `render_bound`: the scene renders a bounded candidate set and this id fell outside it.
 *   The core's own words are load-bearing — an elided candidate remains observed in the
 *   catalog; falling out of render is a bound, never a denial — so this renders as that
 *   statement, never as an error.
 * - `unavailable`: an older core without the route (bare 404/405), an unpaired session, or a
 *   transport failure. The full snapshot remains the authority; the caller falls back to it
 *   silently, because the slice is an optimization and its absence must never cost the page.
 */
const wireU64 = z.string().regex(/^(?:0|[1-9]\d*)$/, "must be a non-negative integer string");

export const candidateSliceV1Schema = z.object({
  contract: z.literal("joshi.glass.candidate_slice"),
  schemaVersion: z.literal(1),
  sceneId: z.string().min(1),
  viewDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/),
  mode: replayModeSchema,
  catalogCommit: wireU64,
  renderedAt: exactUtcInstantSchema,
  renderedCandidateCount: wireU64,
  renderedOrdinal: wireU64,
  candidate: candidateSchema,
}).strict();

export type CandidateSliceV1 = z.infer<typeof candidateSliceV1Schema>;

export type CandidateSliceAnswer =
  | { state: "sliced"; slice: CandidateSliceV1 }
  | { state: "render_bound"; detail: string }
  | { state: "unavailable"; reason: string };

/** A slice is one candidate with evidence and a price path; a megabyte is already generous. */
export const MAX_CANDIDATE_SLICE_BYTES = 16 * 1024 * 1024;

export function parseCandidateSliceV1(value: unknown): CandidateSliceV1 {
  return candidateSliceV1Schema.parse(value);
}

/**
 * Fetch and classify one slice. `fetchImpl` is the caller's authenticated same-origin fetch;
 * this module owns only the wire discipline (bounded read, duplicate-key refusal, strict
 * parse) and the three-way classification above.
 */
export async function loadCandidateSlice(
  baseUrl: URL,
  sceneId: string,
  candidateId: string,
  headers: Record<string, string>,
  signal?: AbortSignal,
): Promise<CandidateSliceAnswer> {
  const url = new URL(
    `/api/v1/glass/scenes/${encodeURIComponent(sceneId)}/candidates/${encodeURIComponent(candidateId)}`,
    baseUrl,
  );
  let response: Response;
  try {
    response = await fetch(url, {
      ...(signal ? { signal } : {}),
      credentials: "omit",
      cache: "no-store",
      headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { state: "unavailable", reason: error instanceof Error ? error.message : "slice transport failed" };
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > MAX_CANDIDATE_SLICE_BYTES) {
    return { state: "unavailable", reason: "candidate slice exceeds the browser response bound" };
  }
  let body: string;
  try {
    body = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return { state: "unavailable", reason: "candidate slice was not valid UTF-8" };
  }
  if (!response.ok) {
    if (response.status === 404) {
      let code: unknown;
      let detail: unknown;
      try {
        const problem = JSON.parse(body) as { code?: unknown; detail?: unknown };
        code = problem.code;
        detail = problem.detail;
      } catch {
        code = undefined;
      }
      if (code === "candidate_not_rendered") {
        return {
          state: "render_bound",
          detail: typeof detail === "string" && detail.length > 0
            ? detail
            : "This scene's rendered candidate set is bounded and this coin fell outside it; "
              + "it remains observed in the catalog.",
        };
      }
    }
    // A bare 404/405 is an older core without the route; anything else is a transport-level
    // non-answer. Both fall back to the full snapshot, which remains the authority.
    return { state: "unavailable", reason: `candidate slice route answered ${response.status}` };
  }
  const wireError = validateJsonWithoutDuplicateKeys(body, false);
  if (wireError !== undefined) return { state: "unavailable", reason: `invalid candidate slice JSON: ${wireError}` };
  try {
    const decoded = JSON.parse(body, (key, value: unknown) => {
      if (key === "__proto__" || key === "constructor" || key === "prototype") {
        throw new Error(`forbidden candidate slice JSON key: ${key}`);
      }
      return value;
    }) as unknown;
    return { state: "sliced", slice: parseCandidateSliceV1(decoded) };
  } catch (error) {
    return { state: "unavailable", reason: error instanceof Error ? error.message : "candidate slice did not parse" };
  }
}
