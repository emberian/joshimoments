"""The portal's request handling: one gate, one place, no way past it.

ONE ENFORCEMENT POINT. Every byte of gated content leaves this process through
``_serve_gated``, and that function's FIRST act is to resolve a session into a standing.
There is no second path to those files — Caddy's root for this name is /var/www, and the
bundle deliberately does not live there — so "the portal never serves gated artifacts
without a valid session" is a property of one function rather than a habit spread over a
routing table. A test asserts it by walking every route.

WHY THE STANDARD LIBRARY. This process needs two things the anchor does not already have:
an HTTP loop and ed25519. The second must be ``solders``, because that is the check
``dregg_gate`` runs and a second library would be a second opinion. The first is
``http.server``, and that IS a considered choice rather than laziness: the alternative in
this repo's dependency set is uvicorn[standard] + FastAPI, which is fifteen more packages
including two more compiled extensions, installed on the box the architecture calls the
one we cannot lose, to serve a dozen routes to a small readership behind a hardened
front. ``http.server``'s well-known caveat is that it is not fit to face the internet
directly; it does not, and cannot — ``Config`` refuses a non-loopback bind. If this ever
needs ASGI it is one file's worth of change, and the routing below is written to make
that swap boring.

RESPONSE HYGIENE IS CENTRAL, NOT PER-ROUTE. ``_respond`` is the only writer, and it sets
``Cache-Control: private, no-store`` and ``Vary: Cookie`` on EVERYTHING. A cache — the
browser's, a corporate proxy's, Caddy's if it ever grows one — holding one holder's page
and handing it to the next reader is the scariest bug available here, and a rule applied
in one function cannot be forgotten in the thirteenth route. Security headers (CSP, HSTS)
are Caddy's, in the Caddyfile, next to their reasons: two CSP headers INTERSECT rather
than merge, a lesson that file already records twice by name.
"""

from __future__ import annotations

import json
import logging
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dregg_site.chrome import esc

from . import FRESHNESS_MARKER, SCHEMA_MANIFEST
from .challenge import build_challenge, new_nonce, signature_matches, valid_wallet
from .config import Config
from .render import (
    freshness_banner,
    page_denied,
    page_front,
    page_me,
    page_message,
    page_no_roster,
    page_signin,
)
from .roster import Roster, RosterError, Standing, decide
from .roster import load as load_roster
from .session import (
    clear_cookie,
    from_cookie_header,
    set_cookie,
)
from .session import (
    mint as mint_session,
)
from .session import (
    read as read_session,
)
from .signerjs import wallet_crypto
from .store import Challenge, PortalStore

log = logging.getLogger(__name__)

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _number(value: object) -> float | None:
    """A real number or None. ``bool`` is an int in Python and is never a timestamp."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
# The gated pages that are one flat artifact each. Anything with a parameter is handled
# by the two prefix routes below, which validate the parameter as base58 first.
FLAT_PAGES = {"": "index.html", "screen": "screen.html", "record": "record.html"}
PREFIX_PAGES = {"coin": "coin", "wallet": "wallet"}


class PortalError(RuntimeError):
    pass


class Portal:
    """All decisions. The HTTP handler below is a thin adapter over this object."""

    def __init__(
        self,
        config: Config,
        store: PortalStore,
        session_key: bytes,
        *,
        clock=time.time,
        page_url: str = "https://shitcoims.dregg.studio/portal/signin",
        app_url: str = "https://shitcoims.dregg.studio",
    ):
        self.config = config
        self.store = store
        self.session_key = session_key
        self.clock = clock
        self.page_url = page_url
        self.app_url = app_url
        self._wallet_js: str | None = None

    # -- artifacts -------------------------------------------------------------------

    @property
    def base(self) -> str:
        return self.config.base_path

    def roster(self) -> Roster | None:
        try:
            return load_roster(self.config.artifacts_dir / "roster.json")
        except RosterError as exc:
            log.warning("holder roster unavailable (%s)", exc)
            return None

    def manifest(self) -> dict:
        try:
            raw = json.loads((self.config.artifacts_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_MANIFEST:
            return {}
        return raw

    def wallet_js(self) -> str:
        if self._wallet_js is None:
            self._wallet_js = wallet_crypto()
        return self._wallet_js

    # -- identity --------------------------------------------------------------------

    def signed_in_wallet(self, cookie_header: object) -> str | None:
        token = from_cookie_header(cookie_header)
        if token is None:
            return None
        return read_session(self.session_key, token, now=self.clock())

    # -- routes ----------------------------------------------------------------------

    def handle(self, method: str, path: str, headers: dict, body: bytes, client: str) -> "Response":
        base = self.base
        if not path.startswith(base):
            return Response(404, "text/plain; charset=utf-8", b"not found\n")
        rest = path[len(base) :].strip("/")
        cookie = headers.get("cookie")

        if method == "POST":
            if rest == "api/nonce":
                return self._api_nonce(body, client)
            if rest == "api/session":
                return self._api_session(body, client)
            if rest == "api/signout":
                return self._api_signout()
            return Response(404, "application/json", b'{"error":"no such endpoint"}')

        if method not in ("GET", "HEAD"):
            return Response(
                405, "text/plain; charset=utf-8", b"method not allowed\n", allow="GET, HEAD, POST"
            )

        if rest == "health":
            return self._health()
        limit = self.config.reads_per_hour_per_ip
        if not self.store.allow("read", client, limit=limit, now=self.clock()):
            return self._page(429, page_message(
                base=base,
                title="slow down · portal",
                heading="too many requests from this address",
                message="Give it an hour. Nothing is wrong with your seat.",
            ))
        if rest == "signin":
            return self._page(200, page_signin(
                base=base,
                wallet_js=self.wallet_js(),
                page_url=self.page_url,
                app_url=self.app_url,
            ))
        if rest == "me":
            return self._me(cookie)
        return self._serve_gated(rest, cookie)

    # -- the gate --------------------------------------------------------------------

    def _authorize(self, cookie: object) -> tuple[str | None, Roster | None, Standing | None]:
        wallet = self.signed_in_wallet(cookie)
        roster = self.roster()
        if wallet is None or roster is None:
            return wallet, roster, None
        return wallet, roster, decide(roster, wallet)

    def _serve_gated(self, rest: str, cookie: object) -> "Response":
        """THE ONLY WAY GATED BYTES LEAVE THIS PROCESS. The gate is the first thing here."""

        wallet, roster, standing = self._authorize(cookie)
        if rest == "" and wallet is None:
            # The front door is public on purpose: someone arriving with no session needs
            # to be told what this is and how to get in, not handed a 401.
            threshold = roster.threshold_tokens if roster else None
            return self._page(200, page_front(
                base=self.base, threshold_tokens=threshold, roster=roster, now=self.clock()
            ))
        if wallet is None:
            return self._page(401, page_message(
                base=self.base,
                title="sign in · portal",
                heading="this page is for $DREGG holders",
                message="Sign in with the wallet that holds, and this opens. It takes one signature "
                        "on a line of text — never a transaction.",
                detail="no session cookie on this request",
            ))
        if roster is None:
            return self._page(503, page_no_roster(base=self.base))
        assert standing is not None
        if not standing.entitled:
            return self._page(403, page_denied(
                base=self.base, wallet=wallet, standing=standing, roster=roster, now=self.clock()
            ))

        target = self._artifact_path(rest)
        if target is None:
            return self._page(404, page_message(
                base=self.base,
                title="not in this bundle · portal",
                heading="nothing here by that name",
                message="That is not one of the pages this portal serves.",
            ))
        try:
            html = target.read_text(encoding="utf-8")
        except OSError:
            return self._page(404, self._absent_artifact(rest, target))
        if FRESHNESS_MARKER not in html:
            # A page that cannot show its own age is a page that will be read as current
            # forever. Refusing it is louder than serving it, and loud is correct.
            log.error(
                "gated artifact %s carries no freshness marker; refusing to serve it", target.name
            )
            return self._page(500, page_message(
                base=self.base,
                title="artifact refused · portal",
                heading="that page was built without a freshness stamp",
                message="It is not being served. A page that cannot say how old it is would be "
                        "read as current forever, and this desk does not publish undated numbers.",
                detail=f"artifact {target.name}",
            ))
        manifest = self.manifest()
        generated = manifest.get("generated_at")
        banner = freshness_banner(
            roster,
            _number(generated),
            self.clock(),
        )
        return self._page(200, html.replace(FRESHNESS_MARKER, banner))

    def _artifact_path(self, rest: str) -> Path | None:
        root = (self.config.artifacts_dir / "gated").resolve()
        if rest in FLAT_PAGES:
            return root / FLAT_PAGES[rest]
        head, _, tail = rest.partition("/")
        if head in PREFIX_PAGES and BASE58.match(tail):
            candidate = (root / PREFIX_PAGES[head] / f"{tail}.html").resolve()
            # Belt over the base58 braces: a resolved path that escaped the root is a bug
            # in the matcher, and the answer to a bug in a security check is not to trust
            # the check. Traversal never reaches the filesystem.
            return candidate if candidate.is_relative_to(root) else None
        return None

    def _absent_artifact(self, rest: str, target: Path) -> str:
        head, _, tail = rest.partition("/")
        manifest = self.manifest()
        window = manifest.get("slice_window") or "the current publish slice"
        if head == "coin":
            what, ask = "coin", f"/coin {tail}"
        elif head == "wallet":
            what, ask = "wallet", f"/wallet {tail}"
        else:
            what, ask = "page", "/help"
        return page_message(
            base=self.base,
            title=f"not in the slice · {what} · portal",
            heading=f"no page for that {what} in this bundle",
            message=(
                f"The portal renders a bounded slice — {window} — and this {what} is not in it. "
                "That is an absence of a PAGE, not a finding about the address: nothing has been "
                "measured and nothing is being claimed."
            ),
            detail=f"live lookup: @ltshitcoims_bot, {ask} · missing artifact {target.name}",
        )

    # -- pages the service owns ------------------------------------------------------

    def _me(self, cookie: object) -> "Response":
        wallet, roster, standing = self._authorize(cookie)
        if wallet is None:
            return self._page(401, page_message(
                base=self.base,
                title="sign in · portal",
                heading="no seat on this browser yet",
                message="Sign in with the wallet that holds to see its standing.",
            ))
        if roster is None:
            return self._page(503, page_no_roster(base=self.base))
        assert standing is not None
        watchlist, note = self._watchlist(wallet)
        return self._page(200, page_me(
            base=self.base,
            wallet=wallet,
            standing=standing,
            roster=roster,
            now=self.clock(),
            watchlist=watchlist,
            watch_note=note,
        ))

    def _watchlist(self, wallet: str) -> tuple[list[dict] | None, str]:
        path = self.config.artifacts_dir / "holders" / f"{wallet}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return None, (
                "No per-holder view for this wallet in the current bundle. Watch subscriptions "
                "live against a Telegram account; the portal can only show them once that "
                "account has verified this wallet with the bot."
            )
        except json.JSONDecodeError:
            return None, "The per-holder view for this wallet did not parse and is not being guessed at."
        items = raw.get("watchlist") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return None, "This wallet's per-holder view carries no watchlist section."
        note = str(
            raw.get("watch_note")
            or "source: watch.sqlite on the desk box, via the linked Telegram account"
        )
        return [item for item in items if isinstance(item, dict)], note

    def _health(self) -> "Response":
        """Liveness only. No holder data, no wallet, no key material, ever."""

        roster = self.roster()
        manifest = self.manifest()
        now = self.clock()
        generated = manifest.get("generated_at")
        payload = {
            "ok": True,
            "roster": None
            if roster is None
            else {
                "age_seconds": int(roster.age_seconds(now)),
                "freshness": roster.freshness(now),
                "wallets": len(roster.holdings),
                "sweep_status": roster.sweep_status,
            },
            "artifacts_age_seconds": (
                int(max(0.0, now - _number(generated))) if _number(generated) is not None else None
            ),
            "open_challenges": self.store.open_challenges(),
        }
        return Response(200, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))

    # -- the sign-in api -------------------------------------------------------------

    def _api_nonce(self, body: bytes, client: str) -> "Response":
        payload = _json_body(body)
        if payload is None:
            return _error(400, "that request body was not JSON")
        wallet = valid_wallet(payload.get("wallet"))
        if wallet is None:
            return _error(400, "that is not a Solana address")
        now = self.clock()
        if not self.store.allow("nonce-ip", client, limit=self.config.nonce_per_hour_per_ip, now=now):
            return _error(429, "too many sign-in lines from this address in the last hour")
        if not self.store.allow("nonce-wallet", wallet, limit=self.config.nonce_per_hour_per_wallet, now=now):
            return _error(429, "too many sign-in lines for that wallet in the last hour")
        nonce = new_nonce()
        message = build_challenge(wallet, nonce, now)
        stored = self.store.put_challenge(
            Challenge(
                nonce=nonce,
                wallet=wallet,
                message=message,
                issued_at=now,
                expires_at=now + self.config.challenge_ttl_seconds,
            )
        )
        if not stored:
            return _error(503, "too many sign-ins are open at once; try again in a few minutes")
        return _json(200, {
            "nonce": nonce,
            "wallet": wallet,
            "message": message,
            "expires_in": self.config.challenge_ttl_seconds,
        })

    def _api_session(self, body: bytes, client: str) -> "Response":
        payload = _json_body(body)
        if payload is None:
            return _error(400, "that request body was not JSON")
        now = self.clock()
        if not self.store.allow("session-ip", client, limit=self.config.session_per_hour_per_ip, now=now):
            return _error(429, "too many sign-in attempts from this address in the last hour")
        wallet = valid_wallet(payload.get("wallet"))
        signature = payload.get("signature")
        if wallet is None or not isinstance(signature, str):
            return _error(400, "a wallet and a signature are both required")
        # Single use, enforced by the delete: a replay finds nothing to consume.
        challenge = self.store.consume(payload.get("nonce"), now=now)
        if challenge is None:
            return _error(400, "that sign-in line has expired or was already used — ask for a fresh one")
        if challenge.wallet != wallet:
            return _error(400, "that sign-in line was issued for a different wallet")
        if not signature_matches(challenge.message, wallet, signature):
            return _error(401, "that signature does not verify for that wallet")

        roster = self.roster()
        token = mint_session(self.session_key, wallet, now=now, ttl_seconds=self.config.session_ttl_seconds)
        cookie = set_cookie(token, ttl_seconds=self.config.session_ttl_seconds)
        if roster is None:
            # Signature proven, entitlement unknowable. Issue the session anyway — the
            # proof is real and re-signing later would cost the reader a ceremony for our
            # outage — and say plainly that the door cannot be opened yet.
            return _json(200, {
                "entitled": False,
                "standing": "unknown",
                "reason": "no holder roster has landed on this box yet, so standing cannot be checked",
                "next": f"{self.base}/me",
            }, cookie=cookie)
        standing = decide(roster, wallet)
        return _json(200, {
            "entitled": standing.entitled,
            "standing": standing.standing,
            "held_raw": str(standing.held_raw),
            "required_raw": str(standing.required_raw),
            "gap_raw": str(standing.gap_raw),
            "decimals": roster.decimals,
            "roster_age_seconds": int(roster.age_seconds(now)),
            "next": f"{self.base}/" if standing.entitled else f"{self.base}/me",
        }, cookie=cookie)

    def _api_signout(self) -> "Response":
        return Response(
            303,
            "text/plain; charset=utf-8",
            b"signed out\n",
            cookie=clear_cookie(),
            location=f"{self.base}/",
        )

    def _page(self, status: int, html: str) -> "Response":
        return Response(status, "text/html; charset=utf-8", html.encode("utf-8"))


class Response:
    __slots__ = ("allow", "body", "content_type", "cookie", "location", "status")

    def __init__(
        self,
        status: int,
        content_type: str,
        body: bytes,
        *,
        cookie: str | None = None,
        location: str | None = None,
        allow: str | None = None,
    ):
        self.status = status
        self.content_type = content_type
        self.body = body
        self.cookie = cookie
        self.location = location
        self.allow = allow

    def headers(self) -> list[tuple[str, str]]:
        out = [
            ("Content-Type", self.content_type),
            ("Content-Length", str(len(self.body))),
            # ONE PLACE. Every response, no exceptions, no per-route memory required.
            ("Cache-Control", "private, no-store"),
            ("Vary", "Cookie"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Robots-Tag", "noindex, nofollow, noarchive"),
        ]
        if self.cookie:
            out.append(("Set-Cookie", self.cookie))
        if self.location:
            out.append(("Location", self.location))
        if self.allow:
            out.append(("Allow", self.allow))
        return out


def _json(status: int, payload: dict, *, cookie: str | None = None) -> Response:
    return Response(
        status,
        "application/json; charset=utf-8",
        json.dumps(payload).encode("utf-8"),
        cookie=cookie,
    )


def _error(status: int, message: str) -> Response:
    return _json(status, {"error": message})


def _json_body(body: bytes) -> dict | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def client_address(headers: dict, peer: str) -> str:
    """The real peer, taken as the LAST X-Forwarded-For entry.

    Caddy APPENDS the socket peer to whatever XFF arrived, so a client that sends
    ``X-Forwarded-For: 1.2.3.4`` produces ``1.2.3.4, <real>``. Reading the FIRST entry —
    the usual reflex — would let anyone forge their rate-limit identity and reset their
    own bucket at will. The last entry is the one our own proxy wrote.
    """

    forwarded = headers.get("x-forwarded-for")
    if isinstance(forwarded, str) and forwarded.strip():
        return forwarded.split(",")[-1].strip()[:64]
    return peer[:64]


class PortalHandler(BaseHTTPRequestHandler):
    """The adapter. Holds no policy: everything it decides, it asks ``Portal``."""

    protocol_version = "HTTP/1.1"
    server_version = "dregg-portal"
    sys_version = ""
    portal: Portal  # set on the server; bound per-connection by the runner

    def log_message(self, format: str, *args) -> None:
        # Method, path and status only. Never the query string, never a header, never a
        # body: a signature and a wallet ride in those, and an access log that quietly
        # accumulates them is a leak with a rotation policy.
        log.info("%s %s", self.address_string(), format % args)

    def _dispatch(self, method: str) -> None:
        try:
            path = unquote(urlsplit(self.path).path)
        except (ValueError, UnicodeDecodeError):
            self._write(Response(400, "text/plain; charset=utf-8", b"bad request\n"), head=False)
            return
        headers = {key.lower(): value for key, value in self.headers.items()}
        body = b""
        if method == "POST":
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > self.portal.config.max_body_bytes:
                self._write(_error(413, "that request body is too large"), head=False)
                return
            body = self.rfile.read(length) if length else b""
        client = client_address(headers, self.client_address[0] if self.client_address else "-")
        try:
            response = self.portal.handle(method, path, headers, body, client)
        except Exception:
            log.exception("portal request failed")
            response = Response(500, "text/html; charset=utf-8", _oops())
        self._write(response, head=(method == "HEAD"))

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _write(self, response: Response, *, head: bool) -> None:
        self.send_response(response.status)
        for key, value in response.headers():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(response.body)


def _oops() -> bytes:
    return (
        "<!doctype html><meta charset=utf-8><title>portal error</title>"
        f"<p>{esc('Something on this box failed. Nothing about your seat changed.')}</p>"
    ).encode("utf-8")
