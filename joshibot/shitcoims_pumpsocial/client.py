"""Transport for the pump social surface: paced, refusing, and honest about time.

THREE PROPERTIES THIS CLIENT HAS ON PURPOSE
-------------------------------------------
1. **It cannot write.** Every mutating route in `endpoints.ENDPOINTS` is marked, and
   `request()` refuses to dispatch one — not by inspecting the HTTP verb (two of the
   POSTs are reads) but by consulting the catalogue. The operator's pump identity is
   their own; a crawler that can follow, post, like or report as them is a liability with
   no upside, and "we just won't call those" is a convention, which is the class of thing
   this repo has watched fail. The refusal is structural and it is tested.

2. **It paces itself, per host.** `api.coin-communities.xyz` rate-limits hard: a bare
   6-request burst measured 3x429, and it answers with `retry-after: 1`. The limiter is
   per-host because the two backends have completely different tolerances, and it honours
   `Retry-After` when the server sends one rather than guessing a backoff.

3. **It records two clocks and never invents the first one.** `t_event` is the API's own
   `createdAt`; `t_ingest` is when we saw it. Where a body states its own staleness
   (`feed_public.computedAt`, `sol-price.asOfTimestamp`) that is carried as a third,
   separate field. They are compared, never mixed — the intelligence store's inverted
   clocks are in this repo's scar list (JOSHI.md §2).

ON THE ONE HAZARD THAT IS NOT A TIMEOUT
---------------------------------------
`GET /users/{key}` on frontend-api-v3 resolves an address OR a username and returns
whichever profile matched, so asking for an address you believe in and getting a *different*
wallet back is a 200, not an error. Given that a live address-poisoning campaign targets
this operator with prefix-and-suffix lookalikes (`wallet_labels.yaml`), a resolver that
silently substitutes one address for another is the exact shape of the thing we are
defending against. `profile()` therefore checks the echoed address and raises.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from .endpoints import BROWSER_UA, PUBLIC_API_KEY, Endpoint, endpoint

#: (status, headers, body_bytes)
Response = tuple[int, dict[str, str], bytes]
#: (method, url, headers, body) -> Response
Transport = Callable[[str, str, dict[str, str], bytes | None], Response]

#: Minimum seconds between requests, per host. Measured, not guessed: coin-communities
#: 429s on a ~2/s burst and recovers at ~1/s; frontend-api-v3 sustained 0.35 s spacing
#: across a 60-request sweep with zero 429s.
HOST_PACE: dict[str, float] = {
    "api.coin-communities.xyz": 1.15,
    "frontend-api-v3.pump.fun": 0.35,
}
DEFAULT_PACE = 1.0


class PumpSocialError(RuntimeError):
    """Transport or contract failure. Carries the endpoint name for provenance."""

    def __init__(self, message: str, *, endpoint_name: str = "", status: int | None = None):
        super().__init__(message)
        self.endpoint_name = endpoint_name
        self.status = status


class MutatingEndpointRefused(PumpSocialError):
    """Raised when something asks this client to change state on pump.fun as the operator."""


class NotFound(PumpSocialError):
    """A measured 404. An answer, not a failure — callers routinely expect these."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a record came from and when we saw it. Attached to every emitted object."""

    endpoint_name: str
    host: str
    path: str
    t_ingest: str
    #: The body's own statement of its age, when it makes one (`computedAt`,
    #: `asOfTimestamp`). None means the source said nothing, which is NOT the same as
    #: "fresh" and is never rendered as such.
    t_source_computed: str | None = None
    contract_status: str = "unsupported_reverse_engineered"

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint_name,
            "host": self.host,
            "path": self.path,
            "t_ingest": self.t_ingest,
            "t_source_computed": self.t_source_computed,
            "contract_status": self.contract_status,
        }


@dataclass(slots=True)
class Stats:
    """Request accounting, so a crawl can report what it cost and where it stalled."""

    requests: int = 0
    retries_429: int = 0
    not_found: int = 0
    errors: int = 0
    seconds_waiting: float = 0.0

    def line(self) -> str:
        return (
            f"{self.requests} requests, {self.retries_429} rate-limited retries, "
            f"{self.not_found} 404s, {self.errors} errors, "
            f"{self.seconds_waiting:.1f}s paced"
        )


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Response:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


class PumpSocialClient:
    """Read-only, self-pacing access to both pump social backends.

    `transport` is injectable so the whole package is testable without a network: the
    tests drive real recorded bodies through it. Nothing else in here reaches the wire.
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        api_key: str = PUBLIC_API_KEY,
        max_429_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport or _urllib_transport
        self._api_key = api_key
        self._max_429 = max_429_retries
        self._sleep = sleep
        self._clock = clock
        self._last_call: dict[str, float] = {}
        self.stats = Stats()

    # -- pacing ---------------------------------------------------------------

    def _pace(self, host: str) -> None:
        gap = HOST_PACE.get(host, DEFAULT_PACE)
        last = self._last_call.get(host)
        if last is not None:
            wait = gap - (self._clock() - last)
            if wait > 0:
                self.stats.seconds_waiting += wait
                self._sleep(wait)
        self._last_call[host] = self._clock()

    # -- the one dispatch point -----------------------------------------------

    def request(
        self,
        name: str,
        *,
        path_params: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, Provenance]:
        spec = endpoint(name)
        if spec.mutating:
            raise MutatingEndpointRefused(
                f"{name} ({spec.method} {spec.path}) changes state on pump.fun as the "
                "operator; this package is read-only by construction",
                endpoint_name=name,
            )
        path = spec.path
        for key, value in (path_params or {}).items():
            token = "{" + key + "}"
            if token not in path:
                raise PumpSocialError(
                    f"{name} has no path parameter {key!r} (template {spec.path})",
                    endpoint_name=name,
                )
            path = path.replace(token, urllib.parse.quote(str(value), safe=""))
        if "{" in path:
            raise PumpSocialError(
                f"{name} left path parameters unfilled: {path}", endpoint_name=name
            )
        url = spec.host + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        return self._send(spec, url, path, body)

    def _send(
        self, spec: Endpoint, url: str, path: str, body: dict[str, Any] | None
    ) -> tuple[Any, Provenance]:
        host = urllib.parse.urlsplit(url).hostname or spec.host
        headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
        if spec.auth == "api_key":
            headers["x-api-key"] = self._api_key
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        for attempt in range(self._max_429 + 1):
            self._pace(host)
            self.stats.requests += 1
            status, response_headers, raw = self._transport(spec.method, url, headers, payload)
            if status == 429:
                self.stats.retries_429 += 1
                if attempt == self._max_429:
                    raise PumpSocialError(
                        f"{spec.name}: rate limited {attempt + 1}x, giving up",
                        endpoint_name=spec.name,
                        status=429,
                    )
                retry_after = response_headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 1.0
                except ValueError:
                    delay = 1.0
                self.stats.seconds_waiting += delay * (attempt + 1)
                self._sleep(delay * (attempt + 1))
                continue
            break

        t_ingest = datetime.now(UTC).isoformat()
        if status == 404:
            self.stats.not_found += 1
            raise NotFound(f"{spec.name}: 404 for {path}", endpoint_name=spec.name, status=404)
        if status >= 400:
            self.stats.errors += 1
            raise PumpSocialError(
                f"{spec.name}: HTTP {status} — {raw[:200]!r}",
                endpoint_name=spec.name,
                status=status,
            )
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            self.stats.errors += 1
            raise PumpSocialError(
                f"{spec.name}: body is not JSON ({exc})", endpoint_name=spec.name, status=status
            ) from exc

        computed = None
        if isinstance(parsed, dict):
            raw_computed = parsed.get("computedAt") or parsed.get("asOfTimestamp")
            if raw_computed is not None:
                computed = str(raw_computed)
        return parsed, Provenance(
            endpoint_name=spec.name,
            host=host,
            path=path,
            t_ingest=t_ingest,
            t_source_computed=computed,
        )

    # -- typed reads ----------------------------------------------------------

    def profile(self, address: str) -> tuple[dict[str, Any], Provenance]:
        """frontend-api-v3 profile for an ADDRESS, with the substitution guard.

        Raises if the API answers about a different wallet than the one asked for. That
        is not paranoia about a hypothetical: `/users/batch` returns the profile of a user
        whose username is "batch", at an unrelated address, with HTTP 200.
        """

        data, prov = self.request("user_profile_v3", path_params={"key": address})
        if not isinstance(data, dict):
            raise PumpSocialError("user_profile_v3: expected an object", endpoint_name="user_profile_v3")
        echoed = data.get("address")
        if echoed != address:
            raise PumpSocialError(
                f"user_profile_v3 substituted an identity: asked for {address!r}, "
                f"answered about {echoed!r} (username {data.get('username')!r}). This "
                "endpoint resolves usernames as well as addresses.",
                endpoint_name="user_profile_v3",
            )
        return data, prov

    def search_users(self, term: str) -> tuple[list[dict[str, Any]], Provenance]:
        data, prov = self.request("user_search", query={"searchTerm": term})
        return (data if isinstance(data, list) else []), prov

    def following(
        self, address: str, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict[str, Any]], Provenance]:
        data, prov = self.request(
            "following_v3", path_params={"address": address}, query={"limit": limit, "offset": offset}
        )
        return (data if isinstance(data, list) else []), prov

    def users_by_wallet(self, addresses: list[str]) -> tuple[dict[str, Any], Provenance]:
        data, prov = self.request("users_by_wallet_batch", body={"addresses": addresses})
        results = data.get("results") if isinstance(data, dict) else None
        return (results if isinstance(results, dict) else {}), prov

    def wallet_callout_stats(self, address: str) -> tuple[dict[str, Any], Provenance]:
        data, prov = self.request("wallet_callout_stats", path_params={"address": address})
        return (data if isinstance(data, dict) else {}), prov

    def messages(
        self, mint: str, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, Provenance]:
        data, prov = self.request(
            "messages_public", path_params={"mint": mint}, query={"limit": limit, "cursor": cursor}
        )
        return (*_page(data, "messages"), prov)

    def callouts(
        self, mint: str, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, Provenance]:
        data, prov = self.request(
            "callouts_public", path_params={"mint": mint}, query={"limit": limit, "cursor": cursor}
        )
        return (*_page(data, "callouts"), prov)

    def callout_replies(
        self, mint: str, callout_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, Provenance]:
        """Replies under one callout. Publicly readable, unlike replies under a comment."""

        data, prov = self.request(
            "callout_replies_public",
            path_params={"mint": mint, "callout_id": callout_id},
            query={"limit": limit, "cursor": cursor},
        )
        # The body key is `messages` on this route even though the parent is a callout.
        rows, cursor_out = _page(data, "messages")
        if not rows:
            rows, cursor_out = _page(data, "replies")
        return rows, cursor_out, prov

    def recent_callouts(
        self, *, limit: int = 50, page_token: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, Provenance]:
        """pump's live callout firehose. Keyset-paginated via `nextPageToken`."""

        data, prov = self.request(
            "callout_recent", query={"limit": limit, "pageToken": page_token}
        )
        return (*_callout_page(data), prov)

    def top_callouts(self, mint: str, *, limit: int = 50) -> tuple[list[dict[str, Any]], Provenance]:
        data, prov = self.request("callout_top", path_params={"mint": mint}, query={"limit": limit})
        return _callout_page(data)[0], prov

    def mint_callouts(
        self, mint: str, *, limit: int = 50, page_token: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, Provenance]:
        data, prov = self.request(
            "callout_list_mint",
            path_params={"mint": mint},
            query={"limit": limit, "sortBy": "TIMESTAMP", "sortOrder": "DESC",
                   "pageToken": page_token},
        )
        return (*_callout_page(data), prov)

    def community(self, mint: str) -> tuple[dict[str, Any], Provenance]:
        data, prov = self.request("community", path_params={"mint": mint})
        return (data if isinstance(data, dict) else {}), prov


def _callout_page(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """The `/callout/*` family's own envelope: `{callouts: [...], nextPageToken: "..."}`.

    Kept separate from `_page` because the token is an EMPTY STRING when exhausted, not
    an absent key — a falsy-but-present cursor that a generic unwrapper would either loop
    on or mis-read as a missing field.
    """

    if not isinstance(data, dict):
        return ([], None)
    rows = data.get("callouts")
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    token = data.get("nextPageToken")
    return (rows, token if isinstance(token, str) and token else None)


def _page(data: Any, key: str) -> tuple[list[dict[str, Any]], str | None]:
    """Unwrap a listing body into (items, next_cursor).

    The cursor field name is not stable across these routes, so every plausible spelling
    is checked and an unrecognised one yields None — which stops pagination rather than
    looping forever on the same page. A crawl that stops early is visible in the item
    count; a crawl that loops is not.
    """

    if not isinstance(data, dict):
        return ([], None)
    items = data.get(key)
    if not isinstance(items, list):
        return ([], None)
    cursor = None
    for candidate in ("nextCursor", "next_cursor", "cursor", "nextPageCursor"):
        value = data.get(candidate)
        if isinstance(value, str) and value:
            cursor = value
            break
    return ([i for i in items if isinstance(i, dict)], cursor)
