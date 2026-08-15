"""Read-only access to pump.fun's social surface: comments, callouts, and the follow graph.

The operator's information environment is pump-native — they follow callers on pump.fun
itself, not on X — and JOSHI's parity surfaces (`design/glass.md` §1: the coin page, the
callouts stream, the trenches feed) need this data to exist at all. The structural reason
it is worth having: ON PUMP THE AUTHOR IS A WALLET. Every commenter, caller and follow edge
arrives as a native address, so the handle->wallet join that limited the X studies to 5 of
146 handles is not a problem that exists here.

Two backends, neither a superset of the other — see `endpoints.py` for the full map:

* `frontend-api-v3.pump.fun` — identity and the FOLLOW GRAPH (with follow timestamps).
* `api.coin-communities.xyz` — comment threads, callouts with the platform's own scoring,
  and the wallet<->X-numeric-id join.

Everything here is READ-ONLY by construction: `client.PumpSocialClient` consults the
endpoint catalogue and refuses to dispatch any route that would post, follow, like or
report as the operator. Nothing in this package signs or sends anything.

    python -m shitcoims_pumpsocial probe                  # re-measure the whole surface
    python -m shitcoims_pumpsocial thread <mint>          # comments + callouts on a coin
    python -m shitcoims_pumpsocial graph <wallet> --depth 1
    python -m shitcoims_pumpsocial profile <wallet>
    python -m shitcoims_pumpsocial callers <wallet>...    # pump's own caller scoreboard
"""

from .client import (
    MutatingEndpointRefused,
    NotFound,
    Provenance,
    PumpSocialClient,
    PumpSocialError,
)
from .crawl import (
    CrawlReport,
    caller_scorecard,
    crawl_follow_graph,
    crawl_recent_callouts,
    crawl_thread,
    full_profile,
    resolve_wallets,
)
from .endpoints import ENDPOINTS, LIVE, Endpoint, endpoint
from .models import (
    Author,
    Callout,
    CalloutStats,
    FollowEdge,
    NativeCallout,
    Post,
    Profile,
    on_curve,
)

__all__ = [
    "ENDPOINTS",
    "LIVE",
    "Author",
    "Callout",
    "CalloutStats",
    "CrawlReport",
    "Endpoint",
    "FollowEdge",
    "MutatingEndpointRefused",
    "NativeCallout",
    "NotFound",
    "Post",
    "Profile",
    "Provenance",
    "PumpSocialClient",
    "PumpSocialError",
    "caller_scorecard",
    "crawl_follow_graph",
    "crawl_recent_callouts",
    "crawl_thread",
    "endpoint",
    "full_profile",
    "on_curve",
    "resolve_wallets",
]
