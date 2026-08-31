"""Retention at the wire: the transport is where the archive's depth comes from.

`shitcoims_pumpsocial.PumpSocialClient` parses bodies and throws the bytes away, which is
the right shape for a crawler and the wrong shape for an archive. Rather than fork the
client — pacing, 429 retries, the structural refusal of mutating routes and the identity-
substitution guard are all things this package wants EXACTLY as they are — the recorder
sits UNDER it as its injectable transport. Consequences, all deliberate:

* Every attempt is retained: the 200s the derived layer is built from, but also the 404s
  (a measured absence is an answer), the 429s (rate-limit weather, with its own record),
  and any garbage body that fails to parse upstream. The raw layer does not editorialise.
* The bytes the client parses are BY CONSTRUCTION the bytes the store hashed: the recorder
  hands the same buffer up that it wrote down, so "derived rows come from retained bytes"
  is not a convention anyone has to remember.
* The budget is metered at the same choke point. A request that happened is counted even
  if everything above it failed; a refusal (mutating route) is refused by the client
  BEFORE the transport is reached and therefore neither happens nor costs budget.

`route` is call-site context the transport cannot know (a URL is not an endpoint name),
so the service names each logical call before dispatching it. A forgotten label degrades
to "unrouted", visible in `stats`, rather than to a wrong one.
"""

from __future__ import annotations

from typing import Callable

from shitcoims_pumpsocial.client import Response, Transport, _urllib_transport

from .store import Store, utc_day


class RecordingTransport:
    """Wraps a Transport; every request/response pair lands in the store with two clocks."""

    def __init__(self, inner: Transport | None, store: Store, clock_ms: Callable[[], int]):
        self._inner: Transport = inner or _urllib_transport
        self._store = store
        self._clock_ms = clock_ms
        self.route = "unrouted"
        self.last_fetch_id: int | None = None
        self.last_status: int | None = None

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> Response:
        t0 = self._clock_ms()
        status, response_headers, raw = self._inner(method, url, headers, body)
        t1 = self._clock_ms()
        self.last_fetch_id = self._store.record_fetch(
            route=self.route, url=url, t_request_ms=t0, t_response_ms=t1, status=status, body=raw
        )
        self.last_status = status
        self._store.budget_spend(utc_day(t0))
        return status, response_headers, raw
