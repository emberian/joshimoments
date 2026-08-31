"""The long-running process on the anchor: bind loopback, serve, heartbeat, exit clean.

A ``simple`` service on the box the architecture calls the one we cannot lose. It reads
its config once, refuses to start without a session key, and then does nothing that can
fail into an unsafe state — the config schema has no provider key to misplace and the
handler has no route that writes anything but a nonce.

NOT A ONESHOT + TIMER. ``edge/relay`` is a oneshot on a timer because a publication cycle
is a batch job; this answers requests and must be resident. The rest of that unit's shape
— dedicated system user, state under /var/lib, MemoryMax, no shell — is copied exactly.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from .app import Portal, PortalHandler
from .config import Config, PortalConfigError
from .session import SessionKeyError, generate_key, read_key, write_key
from .store import PortalStore, sweep_expired

log = logging.getLogger("dregg_portal")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Caddy is the only client and it is polite, but a socket that can never time out is
    # a socket a bug can pin forever. Bounded, on purpose.
    timeout = 30

    def __init__(self, address, handler, portal: Portal):
        self.portal = portal
        # Bound ONCE, on the handler class, before the first connection is accepted. Doing
        # it per-request would be a write from every worker thread to shared class state —
        # harmless today because it is always the same object, and exactly the kind of
        # "harmless today" that stops being true the first time someone adds a second one.
        handler.portal = portal
        super().__init__(address, handler)

    def finish_request(self, request, client_address) -> None:
        # A socket with no timeout is a socket one bug can pin forever. Caddy is polite;
        # this does not depend on that.
        request.settimeout(30)
        super().finish_request(request, client_address)


def heartbeat(portal: Portal, path: Path) -> dict:
    now = portal.clock()
    roster = portal.roster()
    manifest = portal.manifest()
    generated = manifest.get("generated_at")
    beat = {
        "t": now,
        "roster_present": roster is not None,
        "roster_age_seconds": None if roster is None else int(roster.age_seconds(now)),
        "roster_wallets": 0 if roster is None else len(roster.holdings),
        "artifacts_generated_at": generated if isinstance(generated, (int, float)) else None,
        "open_challenges": portal.store.open_challenges(),
    }
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".new")
        temporary.write_text(json.dumps(beat, indent=1), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        log.warning("could not write the heartbeat; serving continues")
    return beat


def build(config: Config, *, clock=time.time, origin: str = "https://shitcoims.dregg.studio") -> Portal:
    key = read_key(config.session_key_file)
    store = PortalStore(config.state_db)
    sweep_expired(store, now=clock())
    return Portal(
        config,
        store,
        key,
        clock=clock,
        page_url=f"{origin}{config.base_path}/signin",
        app_url=origin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dregg_portal", description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--origin", default="https://shitcoims.dregg.studio")
    parser.add_argument(
        "--keygen",
        action="store_true",
        help="create the session key at [paths] session_key and exit; refuses to overwrite",
    )
    parser.add_argument("--check", action="store_true", help="load config and artifacts, report, exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = Config.load(args.config)
    except PortalConfigError as exc:
        print(f"portal config refused: {exc}", file=sys.stderr)
        return 2

    if args.keygen:
        try:
            write_key(config.session_key_file, generate_key())
        except FileExistsError:
            print(
                f"a session key already exists at {config.session_key_file} — refusing to replace it. "
                "Delete it deliberately if you mean to sign everyone out.",
                file=sys.stderr,
            )
            return 3
        print(f"session key written to {config.session_key_file} (0600)")
        return 0

    try:
        portal = build(config, origin=args.origin)
    except SessionKeyError as exc:
        print(f"session key refused: {exc}\nrun with --keygen to create one on this box.", file=sys.stderr)
        return 4

    if args.check:
        print(json.dumps(heartbeat(portal, config.heartbeat_path), indent=1))
        return 0

    family = socket.AF_INET6 if ":" in config.bind_host else socket.AF_INET
    _Server.address_family = family
    server = _Server((config.bind_host, config.bind_port), PortalHandler, portal)
    log.info("portal listening on %s:%s at %s", config.bind_host, config.bind_port, config.base_path)
    heartbeat(portal, config.heartbeat_path)

    def _stop(_signum, _frame) -> None:
        log.info("shutting down")
        server.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        server.serve_forever(poll_interval=1.0)
    finally:
        server.server_close()
        portal.store.close()
    return 0
