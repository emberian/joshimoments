import type { Candidate, EvidenceClass, EvidenceRef } from "../contract/v1";

/**
 * The one presentational rule for epistemics (NORTH_STAR commitment #4): honesty lives in
 * STRUCTURE — the em-dash for an absence, a compact chip for a stated fact, a provenance
 * glyph — and the full derivation-authored sentences live exactly one hover or expand away.
 * Nothing here rewrites a served sentence; these helpers only decide where it appears.
 */

export const EVIDENCE_CLASS_ORDER: EvidenceClass[] = ["observed", "derived", "attested", "interpreted", "unknown"];

export const EVIDENCE_CLASS_GLYPH: Record<EvidenceClass, string> = {
  observed: "O",
  derived: "D",
  attested: "A",
  interpreted: "I",
  unknown: "?",
};

/** Which provenance classes this candidate's evidence carries, for the compact claims glyph. */
export function evidenceClassesPresent(evidence: readonly EvidenceRef[]): EvidenceClass[] {
  return EVIDENCE_CLASS_ORDER.filter((cls) => evidence.some((ref) => ref.evidenceClass === cls));
}

/** The full field-by-field provenance, verbatim notes included, one hover away behind the glyph. */
export function evidenceTitle(evidence: readonly EvidenceRef[]): string {
  return [
    "Field provenance in this view:",
    ...evidence.map((ref) => `${ref.field}: ${ref.evidenceClass} (${ref.status}) — ${ref.note}`),
  ].join("\n");
}

/**
 * The card-face hover for a candidate: the derivation's own attention sentence and social
 * sentence, verbatim. These are exactly the paragraphs that must never sit ON the face.
 */
export function candidateHoverText(candidate: Candidate): string {
  return `${candidate.attentionReason}\n${candidate.socialSummary}`;
}

/**
 * The provider asserts two USD market caps side by side in the same document, and they disagree.
 * The derivation renders one, names the other in the evidence note, and tags the candidate. The
 * tag is the machine-readable disagreement signal; the note carries both figures. The chip is
 * the whole affordance: a flag beside the number, both values one hover away, never an average.
 */
export function marketCapDisagreementNote(candidate: Candidate): string | null {
  if (!candidate.tags.includes("market_cap_fields_disagree")) return null;
  const reference = candidate.evidence.find((item) => item.field === "metrics.marketCapUsd");
  return reference?.note
    ?? "The provider asserts two USD market caps in this document and they disagree; this view renders usd_market_cap and names the sibling in its evidence.";
}
