"""dregg_site: the public shitcoims wire site, generated from the desk's own archives.

``python -m dregg_site.build --out DIR`` renders a small static site — index, screen,
record, research, and the wire archive — from the same data the wire composes from:
the screen's score ledgers, the callout archive sqlite, and the published wire
markdown artifacts. Same inputs, same bytes: no clocks, no randomness, no network.

The house rules (inherited from dregg_wire and enforced by tests):

* EVERY number carries its source and window, stamped beside it.
* Absent data is a STATED absence in the honest voice, never a zero or a placeholder
  that pretends to be a measurement.
* Provider-derived strings (symbols, theses, usernames, mints) are HTML-escaped at
  every render site; hostile text renders inert.
* Static marketing claims live in one registry (``pages.STATIC_CLAIMS``) pairing each
  number with its window, so "no fake numbers" is a checkable property.
"""
