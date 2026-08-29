"""dregg_portal: the shitcoims wire on the web, gated by the same $DREGG line as Telegram.

Sign in with a Solana wallet, hold 888,888 $DREGG, read the desk's work in a browser.
Two halves that never run on the same machine:

* **publish** (``dregg_portal.publish``) runs ON HBOX beside the data. It renders the
  gated pages and a HOLDER ROSTER into a bundle directory, then that bundle is pushed
  OUT to the anchor. hbox keeps every secret it already has and gains none.
* **service** (``dregg_portal.service``) runs ON THE ANCHOR behind Caddy. It verifies a
  wallet signature, decides entitlement by looking the wallet up IN THE PUSHED ROSTER,
  and serves the pushed bytes. It has no chain provider, no Telegram token, and no
  database of its own beyond single-use nonces.

THE ONE SECRET ON THE PUBLIC BOX is a session HMAC key, generated on that box, never
transmitted, never in this repo. Its entire blast radius is "someone reads gated pages
they did not pay for" — not funds, not the bot, not chain access. That bound is the
whole reason the balance check is a roster lookup instead of a Helius call: an API key
on the public edge would have been a second, much worse secret, bought for nothing.

WHY A ROSTER AND NOT A LIVE BALANCE CALL. The bot already decides who holds — daily
re-verify, 48h grace, never eject on a provider error (``dregg_gate.sweep``). Re-asking
Helius from a second surface would be a SECOND implementation of that decision, free to
disagree with the first. The roster ships the DECISION, so the web and the group cannot
drift: they are reading the same table.

THE OUTAGE RULE, mirrored exactly:

* roster PRESENT but old  -> serve, and say how old. A stale roster never revokes a seat,
  for the same reason a Helius timeout never ejects a member.
* roster ABSENT entirely  -> refuse gated content and SAY SO. This is not the outage
  case; it is the "this box has never been told who holds" case, and serving everything
  would be worse than serving nothing.

The house honesty rules from ``dregg_site`` carry over unchanged: every number stamped
with its source and window, absence stated in the honest voice rather than zeroed,
provider-derived strings escaped at every render site, and a page that cannot show how
stale it is does not get served at all (``dregg_portal.app`` refuses one).

NEVER A TRANSACTION. Sign-in is ``signMessage`` on a plain-text challenge that says so
in the text the wallet displays. The portal never builds, requests, or accepts a
transaction, and holds no key that could sign one.
"""

SCHEMA_ROSTER = "dregg-portal-roster/1"
SCHEMA_MANIFEST = "dregg-portal-manifest/1"
SCHEMA_HOLDER = "dregg-portal-holder/1"

# The marker every generated gated page must carry, and which the service replaces with a
# freshness banner computed AT SERVE TIME. Generation time is what the page knows; age is
# what the reader needs, and only the server holds the clock that measures it.
FRESHNESS_MARKER = "<!--dregg-portal-freshness-->"

__all__ = ["FRESHNESS_MARKER", "SCHEMA_HOLDER", "SCHEMA_MANIFEST", "SCHEMA_ROSTER"]
