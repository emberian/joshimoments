import { memo, useState } from "react";

import type { Candidate } from "../contract/v1";
import { loadableImageUri } from "./candidateFacts";

/**
 * One coin's art, everywhere art renders — memecoins ARE their art, and this is the single
 * element allowed to fetch it. The seam's security rules
 * (docs/planning/PARITY_DENSITY_SEAM.md) are enforced HERE so no surface can drift:
 *
 * - `referrerPolicy="no-referrer"`: the provider-controlled host learns nothing about this
 *   cockpit's origin or route.
 * - `crossOrigin="anonymous"`: the fetch carries NO cookies or credentials. A CDN that
 *   refuses anonymous CORS simply errors into the monogram — an honest degradation, never a
 *   credentialed retry.
 * - `loading="lazy"` + `decoding="async"`: two hundred board rows must not fetch two hundred
 *   images before the first paint.
 * - A fixed box with `object-fit: cover` (the CSS side), so a provider-sized image cannot
 *   reflow the row under her pointer.
 * - The page's CSP (`img-src 'self' data:` in index.html) stays TIGHT: a provider-controlled
 *   remote host is exactly the surface it exists to refuse, and a host allowlist would be
 *   brittle and unbounded. Provider art therefore renders through a same-origin core
 *   image-proxy route when one is mounted (its own core lane; not built here), and until
 *   then a remote URL is blocked by the browser, errors, and falls back to the monogram —
 *   which is the honest state, not a defect. data: URIs (the offline fixture's art) render
 *   today because they fetch nothing.
 *
 * The fallback is the monogram this cockpit always drew: the ticker's (or mint's) leading
 * characters. It renders when the view carries no `imageUri`, when the URI is not a scheme
 * this cockpit will hand to an <img> (ipfs://, a bare CID), and when the fetch itself fails
 * or is refused by the CSP. A provider-claimed `nsfw` flag blurs the art (the claim rides
 * the container's data attribute for CSS); the identity text beside the art stays legible
 * either way.
 */
export const CoinArt = memo(function CoinArt({ candidate, size = "row" }: {
  candidate: Candidate;
  /** Which fixed box this art fills; the CSS sizes each. */
  size?: "row" | "card" | "page" | "strip";
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const uri = loadableImageUri(candidate.imageUri);
  const showImage = uri !== null && failed !== uri;
  return (
    <span
      className="coin-art"
      data-size={size}
      data-nsfw={candidate.nsfw === true || undefined}
      title={candidate.imageUri === undefined
        ? "This view does not observe coin art for this mint."
        : showImage
          ? "Provider-asserted coin art, fetched from the provider's URL with no referrer and no credentials; JOSHI does not host it."
          : "This view carries an art URL this cockpit did not load — an unsupported scheme, a failed fetch, or the page's same-origin image policy (provider art renders via the core image-proxy route once mounted). The monogram stands in."}
    >
      {showImage ? (
        <img
          src={uri}
          alt=""
          aria-hidden="true"
          referrerPolicy="no-referrer"
          crossOrigin="anonymous"
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(uri)}
        />
      ) : (
        <span className="coin-art-monogram" aria-hidden="true">
          {(candidate.symbol ?? candidate.mint).slice(0, 2)}
        </span>
      )}
    </span>
  );
});
