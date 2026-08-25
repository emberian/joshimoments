import type { Candidate, FlowWindow } from "../contract/v1";

/**
 * Read helpers for the parity-density seam's provider-claimed candidate fields
 * (docs/planning/PARITY_DENSITY_SEAM.md). Everything here is a LOOKUP or a presentation
 * ratio over two served figures — no market fact is computed, and an absent field stays
 * absent (`null`) so every renderer can state the absence instead of a zero.
 */

/** The movers-tap windows in duration order, for column layout and the volume glyph. */
export const FLOW_WINDOWS: Array<FlowWindow["window"]> = ["5m", "15m", "1h", "24h"];

/** The flow entry for one named window, or null when this candidate's wire carries none. */
export function flowFor(candidate: Candidate, window: FlowWindow["window"]): FlowWindow | null {
  return candidate.flow?.find((entry) => entry.window === window) ?? null;
}

/**
 * TRUE coin age in whole seconds: the scene's own render clock minus the provider's claimed
 * creation clock. Anchored to `renderedAt` deliberately — a replayed scene must state the age
 * as of the scene, not as of whenever a browser happens to look — and never negative-looking:
 * a creation clock ahead of the render clock is a clock disagreement, stated as zero age with
 * the hover carrying the words, not a countdown.
 */
export function trueAgeSeconds(candidate: Candidate, renderedAtUnixMs: number | null): string | null {
  if (candidate.createdAtUnixMs === undefined || renderedAtUnixMs === null || !Number.isFinite(renderedAtUnixMs)) {
    return null;
  }
  const created = Number(candidate.createdAtUnixMs);
  if (!Number.isFinite(created)) return null;
  return String(Math.max(0, Math.floor((renderedAtUnixMs - created) / 1000)));
}

/**
 * The ATH progress ratio: rendered market cap over the provider's claimed all-time-high cap.
 * A presentation ratio of two served decimals (like a sparkline's normalization), clamped to
 * [0, 1] for the bar; `aboveClaimedAth` survives the clamp so the caption can say the current
 * cap exceeds the provider's own recorded high instead of silently pinning the bar.
 */
export function athProgress(candidate: Candidate): { ratio: number; aboveClaimedAth: boolean } | null {
  if (candidate.athMarketCapUsd === undefined || candidate.metrics.marketCapUsd === null) return null;
  const ath = Number(candidate.athMarketCapUsd);
  const current = Number(candidate.metrics.marketCapUsd);
  if (!Number.isFinite(ath) || !Number.isFinite(current) || ath <= 0 || current < 0) return null;
  const raw = current / ath;
  return { ratio: Math.min(1, Math.max(0, raw)), aboveClaimedAth: raw > 1 };
}

/**
 * The hover sentence for a provider-claimed cell: the field's own evidence note verbatim when
 * this view carries one, otherwise the generic labelled-claim sentence. Never rewrites a
 * served note; only decides where it appears.
 */
export function providerClaimTitle(candidate: Candidate, field: string, what: string): string {
  const reference = candidate.evidence.find((item) => item.field === field);
  if (reference) return `${what}: ${reference.evidenceClass} (${reference.status}) — ${reference.note}`;
  return `${what}: a provider claim carried verbatim from this coin's own record in this view.`;
}

/**
 * What this candidate's provider-claimed chain is, read client-side from the verbatim
 * `chainId` (pump.fun went multichain; the 0x rows are other-chain coins, not broken Solana
 * mints). Three states, deliberately distinct:
 *
 * - `solana`: the chainId positively claims Solana (`solana:` namespace) — the only state in
 *   which JOSHI's Solana-only instruments (venue floor, curve, tape) can apply.
 * - `other`: a positive claim of some other chain; `family` is the chainId's namespace
 *   segment, verbatim, for the loud chip face.
 * - `unknown`: the view states no chainId. NEVER read as Solana — and never as foreign
 *   either, so a venue-scoped board keeps unknown coins visible rather than silently
 *   assuming them away.
 */
export type ChainReading =
  | { kind: "solana"; chainId: string }
  | { kind: "other"; family: string; chainId: string }
  | { kind: "unknown" };

export function chainReading(candidate: Candidate): ChainReading {
  const chainId = candidate.chainId;
  if (chainId === undefined) return { kind: "unknown" };
  if (/^solana:/.test(chainId)) return { kind: "solana", chainId };
  const colon = chainId.indexOf(":");
  const family = colon > 0 ? chainId.slice(0, colon) : chainId.slice(0, 10);
  return { kind: "other", family, chainId };
}

/**
 * Whether an image URI is one this cockpit will hand to an <img> at all. http(s) is the
 * provider-CDN case the seam's security rules govern; data:image/ URIs are self-contained
 * bytes (the offline fixture uses them) and fetch nothing. Anything else — ipfs://,
 * javascript:, a bare CID — is not loadable here and falls back to the monogram.
 */
export function loadableImageUri(imageUri: string | undefined): string | null {
  if (imageUri === undefined) return null;
  return /^(?:https?:\/\/|data:image\/)/.test(imageUri) ? imageUri : null;
}
