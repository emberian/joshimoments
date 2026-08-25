import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import { glassPairingSession, type MemoryOnlyPairingSession } from "../security/pairing";
import { parseVenueReadoutV1, type VenueReadoutAnswer } from "./contract";

/** A readout is a few kilobytes of prose and decimal strings; this is generous for one. */
export const MAX_VENUE_READOUT_BYTES = 256 * 1024;

export interface VenueReadoutSource {
  readonly kind: "loopback";
  load(mint: string, signal?: AbortSignal): Promise<VenueReadoutAnswer>;
}

/**
 * Reads one held coin's pre-trade readout from the local core.
 *
 * Nothing about this refreshes on its own. The core serves numbers from one retained account
 * capture taken at one slot, so re-asking would return the same bytes with a longer age; the
 * cockpit shows the age growing instead of implying a refresh that did not happen.
 */
export class LoopbackVenueReadoutSource implements VenueReadoutSource {
  readonly kind = "loopback" as const;
  private readonly baseUrl: URL;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(baseUrl: string, pairingSession: MemoryOnlyPairingSession = glassPairingSession) {
    const parsed = new URL(baseUrl);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    if (parsed.protocol !== "http:" || !loopbackHosts.has(parsed.hostname)) {
      throw new Error("glass core URL must be an explicit HTTP loopback address");
    }
    this.baseUrl = parsed;
    this.pairingSession = pairingSession;
  }

  async load(mint: string, signal?: AbortSignal): Promise<VenueReadoutAnswer> {
    const url = new URL(`/api/v1/glass/venue-readouts/${encodeURIComponent(mint)}`, this.baseUrl);
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
    const body = await readBounded(response);
    if (!response.ok) {
      return { state: "absent", absence: absenceFor(response.status, body) };
    }
    const wireError = validateJsonWithoutDuplicateKeys(body, false);
    if (wireError !== undefined) throw new Error(`invalid venue readout JSON: ${wireError}`);
    const decoded = JSON.parse(body, (key, value: unknown) => {
      if (key === "__proto__" || key === "constructor" || key === "prototype") {
        throw new Error(`forbidden venue readout JSON key: ${key}`);
      }
      return value;
    }) as unknown;
    return { state: "measured", readout: parseVenueReadoutV1(decoded) };
  }
}

/**
 * The core's own words for why it served no readout, kept distinct per reason.
 *
 * A failure to reach the core is not the same as a core that has measured nothing, which is not
 * the same as a core that has measured other coins and not this one. All three render as absences
 * and none of them renders as a number.
 */
function absenceFor(status: number, body: string): string {
  let code: unknown;
  try {
    code = (JSON.parse(body) as { code?: unknown }).code;
  } catch {
    code = undefined;
  }
  if (code === "venue_readouts_not_mounted") {
    return "The local core was started without a venue account capture, so it has measured no "
      + "coin's fee floor or clip interval.";
  }
  if (code === "venue_readout_not_measured") {
    return "The capture this core is serving supports no venue readout for this mint. It may name "
      + "no venue for this coin, or the venue it named could not be assembled from the retained bytes.";
  }
  if (status === 401 || status === 403) {
    return "This session is not paired for cockpit reads, so no measurement was requested.";
  }
  return `The local core answered ${status} and stated no readout.`;
}

async function readBounded(response: Response): Promise<string> {
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > MAX_VENUE_READOUT_BYTES) {
    throw new Error("venue readout exceeds the browser response bound");
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

export function configuredVenueReadoutSource(): VenueReadoutSource | null {
  // Same-origin first, exactly like every other live source (LiveSurfaceShell builds them all
  // from window.location.origin, so requests ride the dev proxy). This was the standing
  // venue-readout NetworkError: this factory alone used the absolute core URL, the browser
  // made it cross-origin, and core serves no CORS headers — by design; loopback same-origin
  // is the contract. The absolute URL remains only as a fallback for non-browser harnesses.
  try {
    return new LoopbackVenueReadoutSource(window.location.origin);
  } catch {
    const loopbackUrl = import.meta.env.VITE_JOSHI_CORE_URL as string | undefined;
    return loopbackUrl ? new LoopbackVenueReadoutSource(loopbackUrl) : null;
  }
}
