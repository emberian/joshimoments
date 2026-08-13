"""Advisory Helius ``transactionSubscribe`` for configured seed and KOL wallets.

This module is deliberately advisory.  It unions the operator's seed wallets with
declared KOL wallet claims, then hands that finite watchlist to the existing
read-only stream and collector.  It never imports a wallet keypair or the
sentinel executor, and it never signs or submits anything.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from shitcoims_intelligence.collector import CanonicalObservationSink, LiveStreamCollector
from shitcoims_intelligence.helius import HeliusTransactionStream, WatchlistSnapshot
from shitcoims_intelligence.kol_wallets import wallets_from_kols

LOGGER = logging.getLogger("shitcoims.intelligence.helius_live")

WATCHLIST_ADDRESS_CAP = 20
WATCHLIST_VERSION_PREFIX = "helius-live"


def watchlist_addresses(config) -> tuple[str, ...]:
    """Unique seed + declared KOL wallets, first-seen order, hard-capped at 20."""

    declared = wallets_from_kols(config.adapters.x_apify.kols)
    unique: list[str] = []
    seen: set[str] = set()
    for wallet in (*config.helius.seed_wallets, *declared):
        if wallet in seen:
            continue
        seen.add(wallet)
        unique.append(wallet)
        if len(unique) >= WATCHLIST_ADDRESS_CAP:
            break
    return tuple(unique)


def _watchlist_snapshot(addresses: tuple[str, ...]) -> WatchlistSnapshot:
    digest = hashlib.sha256("\n".join(addresses).encode()).hexdigest()[:16]
    return WatchlistSnapshot(
        version=f"{WATCHLIST_VERSION_PREFIX}-{digest}",
        addresses=addresses,
    )


async def run_helius_live(config, record_observation, stop: asyncio.Event) -> None:
    """Subscribe to confirmed wallet activity for the configured watchlist.

    An empty union is a no-op: no API key is read and no socket is opened.
    """

    addresses = watchlist_addresses(config)
    if not addresses:
        return

    helius = config.helius
    stream = HeliusTransactionStream(
        api_key_file=helius.api_key_file,
        websocket_url_template=helius.websocket_url_template,
        keepalive_seconds=helius.keepalive_seconds,
        reconnect_seconds=helius.reconnect_seconds,
        max_addresses=WATCHLIST_ADDRESS_CAP,
    )
    sink = CanonicalObservationSink(record_observation)
    snapshot = _watchlist_snapshot(addresses)

    async def watchlist_provider() -> WatchlistSnapshot:
        return snapshot

    LOGGER.info("Helius live stream watching %s addresses", len(addresses))
    await LiveStreamCollector(stream=stream, sink=sink).run(watchlist_provider, stop=stop)
