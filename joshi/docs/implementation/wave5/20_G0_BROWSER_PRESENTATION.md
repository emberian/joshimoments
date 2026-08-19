# G0 Cockpit V2 browser presentation waist

Status: **cross-runtime intrinsic contract only**. This slice freezes what a browser may report
after mounting one exact headed Cockpit V2 publication. It does not prove a presentation happened,
does not prove pixels were visible, and does not raise W5-G0 or product qualification.

`joshi.cockpit.v2.browser_presentation_claim` binds all of the following in one self-excluding
SHA-256 digest:

- idempotency key, browser page ID, client presentation ID, and positive page-local sequence;
- exact publication semantic digest, exact publication-byte digest, and store commit sequence;
- exact head semantic digest, exact head-byte digest, and later store commit sequence;
- the store-resolved source occurrence and exact sorted rendered-subject partition;
- UTC mount time, browser clock identity, monotonic tick, bounded CSS viewport, and integer device
  pixel ratio in thousandths;
- document visibility/focus, read-only authority, and the immutable
  `browser_reported_not_pixel_verified` ceiling.

Rust and Glass independently parse, rederive, and adversarially validate the same canonical vector
at `fixtures/publication/cockpit_v2_browser_presentation_claim_v1.json`. The pinned claim digest is
`sha256:b3be9ee0b5097d2fb15d1718aca21d3d76b8d6e09860d887e0241bbf2de50a26`.
Glass constructs the claim only from a fully validated Core open response; it does not accept
caller-selected body/head coordinates or rendered subjects. Rust revalidates the request against
store-loaded canonical body/head bytes, both store commit coordinates, the source occurrence, and
the publication knowledge cutoff.

## Deliberate ceiling

No public constructor in this slice mints a durable presentation receipt. A future store adapter
must strictly parse the claim, resolve the headed publication and source occurrence inside the
write transaction, enforce idempotent exact-byte retry, fsync, and return a private store-derived
receipt after readback. A Core route must bind that adapter to the same authorized pairing session
that opened the publication. Only then may the React post-mount callback submit the claim.

Actual attached-browser QA was attempted against the loopback G0 inspector on 2026-08-18, but the
in-app browser runtime reported no connected browser instance after the required discovery checks.
Therefore no visual, accessibility, pixel, focus, or product-use witness is claimed. The exact next
qualification step is a real paired open -> React mount -> store receipt -> reopen/readback walk in
a connected browser, with screenshots/accessibility evidence retained separately from this
browser-authored claim.
