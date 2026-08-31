"""Measure what Helius STANDARD ``logsSubscribe`` actually delivers for the pump firehose.

The question this script exists to answer is narrow and empirical: **is a standard
websocket log subscription a complete, unmetered, self-sufficient feed of the pump
platform?** Four sub-questions, each of which this script measures rather than assumes:

1. **Sustained.** Messages per second over a bounded window, per program, plus the size
   distribution and whether the rate degrades as the window runs.
2. **Complete.** Recall against an independent ground truth. The websocket's own count
   proves nothing about what it dropped, so the received signature set is compared against
   ``getSignaturesForAddress`` pages covering an interior slice of the same window. Only
   *interior* slots are scored -- a slot straddling the connect or disconnect edge is
   missing for a reason that has nothing to do with the feed's quality.
3. **Metered.** Recorded as a delta of whatever usage counter Helius will expose to the
   key, if any; the run also reports the raw event count so the bill can be reasoned about
   from the published per-credit rate even when no counter is reachable.
4. **Reducible.** Whether the notification payload alone carries the structured event --
   the anchor self-CPI bytes that :mod:`shitcoims_cluster.pumpswap` already decodes out of
   transaction meta. If those bytes ride in the ``logs`` array, a reducer needs zero
   follow-up ``getTransaction`` and the whole firehose collapses to ~50-byte rows.

Read-only by construction: the only HTTP method used is ``getSignaturesForAddress``, via
:class:`shitcoims_cluster.rpc.HeliusRpc`, whose whitelist makes that structural. The
websocket sends ``logsSubscribe`` / ``logsUnsubscribe`` and nothing else. The API key is
read from a 0600 file, appended to the URL at connect time, and never logged -- every log
line names the host, never the URL.

Run::

    uv run python scripts/pump_logs_spike.py --seconds 60 --label smoke
    uv run python scripts/pump_logs_spike.py --seconds 600 --label main

Artifacts land in ``--out`` (default: a scratch dir): ``<label>-summary.json`` with every
measurement, and ``<label>-samples.jsonl`` with a bounded number of verbatim notification
payloads for the reducer sketch to be argued from actual bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import struct
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import websockets
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shitcoims_cluster.pumpswap import (
    ANCHOR_CPI_EVENT_TAG,
    EventDecodeError,
    decode_swap_event,
)

# The repo's own borsh reader, used deliberately rather than reimplemented: the claim under
# test is that the EXISTING decoder works on bytes taken from a log line, and a second reader
# written here would test this script instead of the thing we ship.
from shitcoims_cluster.pumpswap import _read as borsh_read
from shitcoims_cluster.rpc import HeliusRpc, read_secret_file

PUMP_FUN_PROGRAM: Final[str] = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PROGRAMS: Final[dict[str, str]] = {"pumpfun": PUMP_FUN_PROGRAM, "pumpswap": PUMPSWAP_PROGRAM}

#: PumpPortal's free ``subscribeNewToken`` feed. An independent vendor's view of the same
#: platform: every create it reports MUST appear in a complete pump.fun log stream, so its
#: mints are a second, vendor-crossed recall probe alongside the RPC one.
PUMPPORTAL_URL: Final[str] = "wss://pumpportal.fun/api/data"

#: Verbatim payloads kept per program, for the reducer sketch. Bounded so a 15-minute run at
#: ~1k/s does not write a hundred gigabytes to answer a question about field availability.
SAMPLE_LIMIT: Final[int] = 40

#: How many ``getSignaturesForAddress`` pages the recall probe may spend. Each page is 1000
#: signatures; on a program doing ~500/s that is ~2 seconds of platform time per page.
DEFAULT_RECALL_PAGES: Final[int] = 40

#: pump.fun's ``TradeEvent``, prefix only. Every field after ``timestamp`` has changed across
#: program upgrades (fee recipients, creator fees, boost) and none of them is needed to know
#: what trade happened, so the layout is deliberately truncated at the last field this script
#: is willing to claim. ``timestamp`` is the self-check: a correct decode puts it within
#: seconds of our receive clock, and a wrong one puts it in 1970 or the far future.
PUMP_TRADE_EVENT: Final[bytes] = bytes.fromhex("bddb7fd34ee661ee")
PUMP_TRADE_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("mint", "pubkey"),
    ("sol_amount", "u64"),
    ("token_amount", "u64"),
    ("is_buy", "bool"),
    ("user", "pubkey"),
    ("timestamp", "i64"),
)

#: pump.fun's ``CreateEvent``. Self-validating in a way no other event is: the first three
#: fields are borsh strings, so a correct decode yields readable text and the mint can be
#: checked against what PumpPortal independently reports for the same signature.
PUMP_CREATE_EVENT: Final[bytes] = bytes.fromhex("1b72a94ddeeb6376")
PUMP_CREATE_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("name", "string"),
    ("symbol", "string"),
    ("uri", "string"),
    ("mint", "pubkey"),
    ("bonding_curve", "pubkey"),
    ("user", "pubkey"),
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# -- measurement ----------------------------------------------------------------------


@dataclass
class StreamStats:
    """Everything one program's subscription is asked to report on."""

    program_label: str
    program_id: str
    subscribed_at: float | None = None
    first_message_at: float | None = None
    last_message_at: float | None = None
    messages: int = 0
    bytes_total: int = 0
    #: Helius meters streaming at 20 credits per uncompressed MB, so the bill is a function
    #: of BYTES, not of events -- which makes "how many of these bytes are worth anything"
    #: the central cost question rather than a curiosity. Bytes are therefore split by the
    #: two properties that decide whether a message carries signal: did the transaction
    #: succeed, and did it emit a decodable event.
    bytes_failed: int = 0
    bytes_with_event: int = 0
    messages_with_event: int = 0
    sizes: list[int] = field(default_factory=list)
    per_second: Counter[int] = field(default_factory=Counter)
    #: signature -> the slot the notification carried. A dict rather than a set because the
    #: recall probe has to score BOTH directions on the same slot range, and the stream's own
    #: slot is the only way to place a signature the RPC index never returned.
    sig_slot: dict[str, int] = field(default_factory=dict)
    duplicate_signatures: int = 0
    failed_txs: int = 0
    slot_first_seen: dict[int, float] = field(default_factory=dict)
    log_line_counts: list[int] = field(default_factory=list)
    #: Anchor event discriminators found in ``Program data:`` lines, by hex.
    event_discriminators: Counter[str] = field(default_factory=Counter)
    program_data_lines: int = 0
    messages_with_program_data: int = 0
    decoded_swap_events: int = 0
    decode_errors: int = 0
    #: Reducer proof: fully decoded rows, straight off the log line, no ``getTransaction``.
    reduced_rows: int = 0
    reduced_sample: list[dict[str, Any]] = field(default_factory=list)
    #: ``TradeEvent`` decodes whose embedded timestamp lands within 120s of our receive
    #: clock. A layout that is wrong cannot pass this by accident.
    trade_timestamp_sane: int = 0
    trade_timestamp_insane: int = 0
    #: signature -> mint, from CreateEvent decodes, for the PumpPortal cross-check.
    created_mints: dict[str, str] = field(default_factory=dict)
    disconnects: int = 0
    reconnects: int = 0
    errors: list[str] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    #: Time spent inside the receive loop's own processing, to expose self-inflicted
    #: backpressure: if this approaches the window length, WE are the bottleneck, not Helius.
    processing_seconds: float = 0.0

    def rate(self) -> float:
        if self.first_message_at is None or self.last_message_at is None:
            return 0.0
        span = self.last_message_at - self.first_message_at
        return self.messages / span if span > 0 else 0.0


def _scan_logs(stats: StreamStats, logs: list[str], signature: str | None, t_recv: float) -> None:
    """Pull every structured thing the log array itself carries. No follow-up RPC.

    This is the reducer, in miniature. If it can name the mint, the direction and the size of
    a trade from the notification alone, then the production reducer needs no
    ``getTransaction`` and the ~100GB/day of logs collapses to a row per trade.
    """

    saw_program_data = False
    for line in logs:
        if not line.startswith("Program data: "):
            continue
        saw_program_data = True
        stats.program_data_lines += 1
        try:
            raw = base64.b64decode(line[14:], validate=True)
        except Exception:
            stats.decode_errors += 1
            continue
        if len(raw) < 8:
            stats.decode_errors += 1
            continue
        # Anchor's `emit!` writes the bare 8-byte event discriminator; `emit_cpi!` prefixes
        # the CPI tag. Both spellings are accepted so the count is of EVENTS, not of styles.
        if raw.startswith(ANCHOR_CPI_EVENT_TAG):
            discriminator, body, wrapped = raw[8:16], raw[16:], True
        else:
            discriminator, body, wrapped = raw[:8], raw[8:], False
        stats.event_discriminators[("cpi:" if wrapped else "bare:") + discriminator.hex()] += 1

        row: dict[str, Any] | None = None
        try:
            if discriminator == PUMP_TRADE_EVENT:
                decoded = borsh_read(body, PUMP_TRADE_FIELDS)
                drift = abs(t_recv - float(decoded["timestamp"]))
                if drift <= 120:
                    stats.trade_timestamp_sane += 1
                else:
                    stats.trade_timestamp_insane += 1
                row = {
                    "kind": "pumpfun_trade",
                    "mint": decoded["mint"],
                    "side": "buy" if decoded["is_buy"] else "sell",
                    "sol_lamports": decoded["sol_amount"],
                    "token_raw": decoded["token_amount"],
                    "user": decoded["user"],
                    "event_ts": decoded["timestamp"],
                }
            elif discriminator == PUMP_CREATE_EVENT:
                decoded = borsh_read(body, PUMP_CREATE_FIELDS)
                row = {
                    "kind": "pumpfun_create",
                    "mint": decoded["mint"],
                    "name": decoded["name"],
                    "symbol": decoded["symbol"],
                    "user": decoded["user"],
                }
                if signature:
                    stats.created_mints[signature] = str(decoded["mint"])
            else:
                # PumpSwap buy/sell, through the decoder this repo already ships. It expects
                # the CPI wrapper, so a bare emit is re-wrapped rather than re-parsed.
                event = decode_swap_event(raw if wrapped else ANCHOR_CPI_EVENT_TAG + raw)
                if event is not None:
                    stats.decoded_swap_events += 1
                    row = {
                        "kind": "pumpswap_swap",
                        "pool": event.pool,
                        "side": event.side,
                        "pool_base_raw": event.pool_base_raw,
                        "pool_quote_raw": event.pool_quote_raw,
                    }
        except (EventDecodeError, KeyError, ValueError, struct.error):
            stats.decode_errors += 1
            continue

        if row is not None:
            stats.reduced_rows += 1
            if len(stats.reduced_sample) < 8:
                stats.reduced_sample.append({"signature": signature, **row})
    if saw_program_data:
        stats.messages_with_program_data += 1


async def run_logs_subscription(
    url: str,
    label: str,
    program: str,
    seconds: float,
    commitment: str,
    stop_at: float,
    live: dict[str, StreamStats] | None = None,
) -> StreamStats:
    """Subscribe, drain for the window, unsubscribe. Reconnects if the socket drops."""

    stats = StreamStats(program_label=label, program_id=program)
    if live is not None:
        live[label] = stats
    while time.time() < stop_at:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                max_size=None,
                max_queue=1 << 16,
            ) as ws:
                if stats.messages:
                    stats.reconnects += 1
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "logsSubscribe",
                            "params": [{"mentions": [program]}, {"commitment": commitment}],
                        }
                    )
                )
                ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if "error" in ack:
                    stats.errors.append(f"subscribe rejected: {ack['error']}")
                    log(f"{label}: subscribe REJECTED: {ack['error']}")
                    return stats
                subscription_id = ack.get("result")
                stats.subscribed_at = time.time()
                log(f"{label}: subscribed (id={subscription_id}) at {commitment}")

                while True:
                    remaining = stop_at - time.time()
                    if remaining <= 0:
                        break
                    try:
                        # `decode=False` keeps the text frame as bytes. That is not a
                        # micro-optimisation: the meter charges by the MEGABYTE, and
                        # `len(str)` counts CHARACTERS -- a token name with an emoji in it
                        # would be undercounted. The billable unit is the byte, so the byte
                        # is what gets measured.
                        raw = await asyncio.wait_for(ws.recv(decode=False), timeout=min(remaining, 30))
                    except TimeoutError:
                        continue
                    t_recv = time.time()
                    t0 = time.perf_counter()
                    stats.messages += 1
                    stats.bytes_total += len(raw)
                    stats.sizes.append(len(raw))
                    stats.per_second[int(t_recv)] += 1
                    if stats.first_message_at is None:
                        stats.first_message_at = t_recv
                    stats.last_message_at = t_recv
                    try:
                        payload = json.loads(raw)
                    except ValueError:
                        stats.errors.append("non-json frame")
                        continue
                    params = payload.get("params") or {}
                    result = params.get("result") or {}
                    slot = (result.get("context") or {}).get("slot")
                    value = result.get("value") or {}
                    signature = value.get("signature")
                    logs = value.get("logs") or []
                    if isinstance(slot, int) and slot not in stats.slot_first_seen:
                        stats.slot_first_seen[slot] = t_recv
                    if isinstance(signature, str):
                        if signature in stats.sig_slot:
                            stats.duplicate_signatures += 1
                        stats.sig_slot[signature] = slot if isinstance(slot, int) else -1
                    if value.get("err") is not None:
                        stats.failed_txs += 1
                        stats.bytes_failed += len(raw)
                    stats.log_line_counts.append(len(logs))
                    before_rows = stats.reduced_rows
                    _scan_logs(stats, logs, signature if isinstance(signature, str) else None, t_recv)
                    if stats.reduced_rows > before_rows:
                        stats.messages_with_event += 1
                        stats.bytes_with_event += len(raw)
                    if len(stats.samples) < SAMPLE_LIMIT:
                        stats.samples.append(payload)
                    stats.processing_seconds += time.perf_counter() - t0

                if subscription_id is not None:
                    with_timeout = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "logsUnsubscribe",
                            "params": [subscription_id],
                        }
                    )
                    await ws.send(with_timeout)
                    log(f"{label}: unsubscribed")
                break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats.disconnects += 1
            stats.errors.append(f"{type(exc).__name__}: {exc}"[:200])
            log(f"{label}: connection lost ({type(exc).__name__}); reconnecting")
            await asyncio.sleep(1.0)
    return stats


#: Helius's enhanced-websocket host. ``transactionSubscribe`` is the only subscription on
#: offer anywhere that filters SERVER-SIDE on ``failed``, which under a per-megabyte meter is
#: the difference between paying for the spam and not. Whether this key may use it is a
#: plan-gating question the vendor answers on the wire, so it is asked rather than assumed.
ATLAS_WS_TEMPLATE: Final[str] = "wss://atlas-mainnet.helius-rpc.com/?api-key={api_key}"


async def probe_transaction_subscribe(
    api_key: str,
    program: str,
    commitment: str,
    seconds: float,
) -> dict[str, Any]:
    """Ask whether the filtered, successful-only feed is available to this key, and weigh it.

    Two outcomes, both useful. A rejection names the plan tier the vendor wants for
    server-side filtering. An acceptance gives a byte rate that can be compared, like for
    like, against the log firehose -- fewer messages but fatter ones, and only the measurement
    settles which way the product goes.
    """

    url = ATLAS_WS_TEMPLATE.format(api_key=api_key)
    out: dict[str, Any] = {
        "method": "transactionSubscribe",
        "filter": {"failed": False, "accountInclude": [program]},
        "accepted": None,
        "messages": 0,
        "bytes": 0,
        "failed_seen": 0,
        "sizes": [],
        "error": None,
    }
    stop_at = time.time() + seconds
    try:
        async with websockets.connect(url, ping_interval=20, max_size=None) as ws:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "transactionSubscribe",
                        "params": [
                            {"failed": False, "accountInclude": [program]},
                            {
                                "commitment": commitment,
                                "encoding": "base64",
                                "transactionDetails": "full",
                                "showRewards": False,
                                "maxSupportedTransactionVersion": 0,
                            },
                        ],
                    }
                )
            )
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if "error" in ack:
                out["accepted"] = False
                out["error"] = ack["error"]
                log(f"transactionSubscribe REJECTED: {ack['error']}")
                return out
            out["accepted"] = True
            log("transactionSubscribe accepted; measuring")
            while time.time() < stop_at:
                remaining = stop_at - time.time()
                try:
                    raw = await asyncio.wait_for(ws.recv(decode=False), timeout=min(remaining, 20))
                except TimeoutError:
                    continue
                out["messages"] += 1
                out["bytes"] += len(raw)
                if len(out["sizes"]) < 5000:
                    out["sizes"].append(len(raw))
                try:
                    payload = json.loads(raw)
                except ValueError:
                    continue
                value = ((payload.get("params") or {}).get("result") or {}).get("transaction") or {}
                if (value.get("meta") or {}).get("err") is not None:
                    out["failed_seen"] += 1
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        if out["accepted"] is None:
            out["accepted"] = False
    sizes = out.pop("sizes")
    out["size_bytes_mean"] = round(sum(sizes) / len(sizes)) if sizes else None
    out["megabytes_per_second"] = round(out["bytes"] / 1e6 / seconds, 4)
    return out


async def watch_slot_lag(
    rpc: HeliusRpc,
    streams: dict[str, StreamStats],
    stop_at: float,
    period: float = 10.0,
) -> list[dict[str, Any]]:
    """Sample ``getSlot`` against the highest slot each stream has delivered.

    This is the honest latency measure. ``getBlockTime`` compares a cluster-estimated
    timestamp against our wall clock and the two disagree by seconds for reasons that have
    nothing to do with delivery. Asking the SAME endpoint at the SAME commitment "what slot
    are you on" and subtracting the stream's high-water mark is clock-free: the answer is in
    slots, and a slot is 400ms by construction.
    """

    samples: list[dict[str, Any]] = []
    while time.time() < stop_at - 1:
        await asyncio.sleep(min(period, max(0.0, stop_at - 1 - time.time())))
        if time.time() >= stop_at - 1:
            break

        def heads() -> dict[str, int | None]:
            return {
                label: (max(s.slot_first_seen) if s.slot_first_seen else None) for label, s in streams.items()
            }

        before = heads()
        t0 = time.perf_counter()
        try:
            tip = await asyncio.to_thread(rpc.call, "getSlot", [{"commitment": "confirmed"}])
        except Exception as exc:
            samples.append({"error": type(exc).__name__})
            continue
        rtt = time.perf_counter() - t0
        after = heads()
        if not isinstance(tip, int):
            continue
        # The round trip means the true lag lies between the two brackets: `before` was read
        # too early to have seen slots the RPC already knows about, `after` too late.
        samples.append(
            {
                "rpc_confirmed_slot": tip,
                "rpc_rtt_seconds": round(rtt, 3),
                "lag_slots_upper": {
                    label: (tip - head) if head is not None else None for label, head in before.items()
                },
                "lag_slots_lower": {
                    label: (tip - head) if head is not None else None for label, head in after.items()
                },
            }
        )
    return samples


async def run_pumpportal(stop_at: float) -> dict[str, Any]:
    """Collect PumpPortal's free create feed as an independent view of the same platform."""

    out: dict[str, Any] = {"mints": [], "errors": [], "messages": 0}
    try:
        async with websockets.connect(PUMPPORTAL_URL, ping_interval=20) as ws:
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            log("pumpportal: subscribed newToken")
            while True:
                remaining = stop_at - time.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
                except TimeoutError:
                    continue
                out["messages"] += 1
                try:
                    payload = json.loads(raw)
                except ValueError:
                    continue
                if payload.get("txType") == "create" and payload.get("signature"):
                    out["mints"].append(
                        {
                            "signature": payload["signature"],
                            "mint": payload.get("mint"),
                            "t_recv": time.time(),
                        }
                    )
    except Exception as exc:
        out["errors"].append(f"{type(exc).__name__}: {exc}"[:200])
    return out


# -- ground truth ---------------------------------------------------------------------


def recall_probe(
    rpc: HeliusRpc,
    program: str,
    received: dict[str, int],
    slot_lo: int,
    slot_hi: int,
    pages: int,
) -> dict[str, Any]:
    """Page ``getSignaturesForAddress`` backwards and score recall on interior slots only.

    Paging walks newest-first from the live tip. Only signatures whose slot lands strictly
    inside ``[slot_lo, slot_hi]`` -- the range the subscription was demonstrably live for --
    are scored, so the subscription is never blamed for a transaction it could not have been
    connected to see.
    """

    truth: dict[str, int] = {}
    truth_failed: set[str] = set()
    before: str | None = None
    calls = 0
    for _ in range(pages):
        page = rpc.signatures_for_address(program, limit=1000, before=before)
        calls += 1
        if not page:
            break
        for entry in page:
            sig = entry.get("signature")
            slot = entry.get("slot")
            if isinstance(sig, str) and isinstance(slot, int):
                truth[sig] = slot
                if entry.get("err") is not None:
                    truth_failed.add(sig)
        before = page[-1].get("signature")
        oldest = min((e.get("slot") or 0) for e in page)
        if oldest < slot_lo:
            break
    interior = {sig: slot for sig, slot in truth.items() if slot_lo <= slot <= slot_hi}
    covered = bool(truth) and min(truth.values()) <= slot_lo
    hits = sum(1 for sig in interior if sig in received)
    misses = [sig for sig in interior if sig not in received]
    # The other direction: signatures the STREAM delivered in the scored range that the RPC
    # index does not list. A non-zero count here does not mean the stream invented anything;
    # it means the two views of "mentions this program" differ, which is worth knowing.
    received_interior = {sig for sig, slot in received.items() if slot_lo <= slot <= slot_hi}
    extra = [sig for sig in received_interior if sig not in truth]
    interior_failed = sum(1 for sig in interior if sig in truth_failed)
    return {
        "rpc_calls": calls,
        "truth_signatures_fetched": len(truth),
        "truth_slot_min": min(truth.values()) if truth else None,
        "truth_slot_max": max(truth.values()) if truth else None,
        "truth_reached_scored_range": covered,
        "scored_slot_lo": slot_lo,
        "scored_slot_hi": slot_hi,
        "interior_truth": len(interior),
        "interior_hits": hits,
        "interior_misses": len(misses),
        "recall": (hits / len(interior)) if interior else None,
        "miss_sample": misses[:10],
        "interior_truth_failed_fraction": round(interior_failed / len(interior), 4) if interior else None,
        "stream_interior_matched": len(received_interior),
        "stream_signatures_absent_from_truth_index": len(extra),
    }


def usage_probe(api_key: str) -> dict[str, Any]:
    """Try every plausible Helius usage/credit endpoint. Report what each one said.

    There is no documented public credit-counter endpoint, so this probes and records the
    HTTP status rather than pretending to a number. A 404 here is a finding: it means the
    metering question can only be answered from the dashboard or the pricing docs.
    """

    import httpx

    candidates = [
        "https://api.helius.xyz/v0/usage",
        "https://api.helius.xyz/v0/account/usage",
        "https://api.helius.xyz/v0/addresses/usage",
        "https://api-mainnet.helius-rpc.com/v0/usage",
    ]
    out: dict[str, Any] = {}
    with httpx.Client(timeout=15.0) as client:
        for url in candidates:
            label = url.split("//", 1)[1]
            try:
                response = client.get(url, params={"api-key": api_key})
            except Exception as exc:
                out[label] = {"error": type(exc).__name__}
                continue
            body = response.text[:400]
            out[label] = {"status": response.status_code, "body": body}
    return out


# -- reporting ------------------------------------------------------------------------


def summarize(stats: StreamStats, block_times: dict[int, int]) -> dict[str, Any]:
    sizes = sorted(stats.sizes)
    seconds = sorted(stats.per_second)
    # Drop the first and last bucket: both are partial seconds and drag the floor down.
    interior_buckets = [stats.per_second[s] for s in seconds[1:-1]] if len(seconds) > 2 else []
    half = len(interior_buckets) // 2
    span = (
        (stats.last_message_at - stats.first_message_at)
        if stats.first_message_at is not None and stats.last_message_at is not None
        else 0.0
    )
    lags = [
        stats.slot_first_seen[slot] - block_times[slot]
        for slot in stats.slot_first_seen
        if slot in block_times
    ]

    def pct(values: list[int] | list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return float(ordered[min(len(ordered) - 1, int(q * len(ordered)))])

    return {
        "program": stats.program_label,
        "program_id": stats.program_id,
        "messages": stats.messages,
        "unique_signatures": len(stats.sig_slot),
        "duplicate_signatures": stats.duplicate_signatures,
        "failed_txs": stats.failed_txs,
        "failed_fraction": round(stats.failed_txs / stats.messages, 4) if stats.messages else None,
        "bytes_total": stats.bytes_total,
        "megabytes_total": round(stats.bytes_total / 1e6, 2),
        "megabytes_per_second": round(stats.bytes_total / 1e6 / span, 4) if span else None,
        "bytes_failed_fraction": round(stats.bytes_failed / stats.bytes_total, 4)
        if stats.bytes_total
        else None,
        "bytes_with_event_fraction": round(stats.bytes_with_event / stats.bytes_total, 4)
        if stats.bytes_total
        else None,
        "messages_with_event": stats.messages_with_event,
        "messages_per_second_mean": round(stats.rate(), 1),
        "messages_per_second_p50": pct(interior_buckets, 0.5),
        "messages_per_second_p95": pct(interior_buckets, 0.95),
        "messages_per_second_max": max(interior_buckets) if interior_buckets else None,
        "rate_first_half": round(statistics.mean(interior_buckets[:half]), 1) if half else None,
        "rate_second_half": round(statistics.mean(interior_buckets[half:]), 1) if half else None,
        "size_bytes_min": sizes[0] if sizes else None,
        "size_bytes_p50": pct(sizes, 0.5),
        "size_bytes_p95": pct(sizes, 0.95),
        "size_bytes_max": sizes[-1] if sizes else None,
        "log_lines_p50": pct(stats.log_line_counts, 0.5),
        "log_lines_max": max(stats.log_line_counts) if stats.log_line_counts else None,
        "slots_seen": len(stats.slot_first_seen),
        "slot_min": min(stats.slot_first_seen) if stats.slot_first_seen else None,
        "slot_max": max(stats.slot_first_seen) if stats.slot_first_seen else None,
        "slot_gaps": _slot_gaps(sorted(stats.slot_first_seen)),
        "blocktime_to_receive_seconds_p50": pct(lags, 0.5),
        "blocktime_to_receive_seconds_p95": pct(lags, 0.95),
        "blocktime_samples": len(lags),
        "messages_with_program_data": stats.messages_with_program_data,
        "program_data_lines": stats.program_data_lines,
        "anchor_event_discriminators": dict(stats.event_discriminators.most_common(12)),
        "decoded_swap_events": stats.decoded_swap_events,
        "decode_errors": stats.decode_errors,
        "reduced_rows": stats.reduced_rows,
        "reduced_rows_per_second": round(stats.reduced_rows / span, 1) if span else None,
        "trade_timestamp_sane": stats.trade_timestamp_sane,
        "trade_timestamp_insane": stats.trade_timestamp_insane,
        "reduced_sample": stats.reduced_sample,
        "creates_decoded": len(stats.created_mints),
        "disconnects": stats.disconnects,
        "reconnects": stats.reconnects,
        "processing_seconds": round(stats.processing_seconds, 1),
        "errors": stats.errors[:10],
    }


#: Helius's published streaming meter, unified across LaserStream gRPC and WebSockets on
#: 2026-04-07 and switched on for previously-unmetered WSS traffic on 2026-05-01. The unit is
#: UNCOMPRESSED megabytes, which is what this script measures: ``len(raw)`` is the frame after
#: the client has inflated it, so our megabyte count is the billable one and not a transport
#: figure that permessage-deflate would have flattered.
CREDITS_PER_MB: Final[float] = 20.0
#: Overage price on every paid tier.
USD_PER_MILLION_CREDITS: Final[float] = 5.0
#: (name, monthly USD, included monthly credits).
PLANS: Final[tuple[tuple[str, float, float], ...]] = (
    ("free", 0.0, 1e6),
    ("developer", 49.0, 10e6),
    ("business", 499.0, 100e6),
    ("professional", 999.0, 200e6),
)


def cost_projection(megabytes_per_second: float) -> dict[str, Any]:
    """Turn a measured byte rate into the monthly bill on each published plan.

    This is the whole decision. The spike was launched on the hypothesis that standard
    websockets are unmetered; the meter is real and it is charged by the megabyte, so the
    question "can we sustain 960 events/sec" was never the binding one -- "what do those
    events weigh" is.
    """

    mb_day = megabytes_per_second * 86_400
    mb_month = mb_day * 30
    credits_month = mb_month * CREDITS_PER_MB
    plans: dict[str, dict[str, Any]] = {}
    for name, monthly, included in PLANS:
        overage = max(0.0, credits_month - included)
        if name == "free" and overage > 0:
            plans[name] = {"usd_month": None, "note": "no overage available; stream is cut off"}
            continue
        plans[name] = {
            "usd_month": round(monthly + overage / 1e6 * USD_PER_MILLION_CREDITS, 2),
            "overage_credits": round(overage),
        }
    return {
        "megabytes_per_second": round(megabytes_per_second, 4),
        "gigabytes_per_day": round(mb_day / 1000, 1),
        "credits_per_day": round(mb_day * CREDITS_PER_MB),
        "credits_per_month": round(credits_month),
        "marginal_usd_per_gb": round(1000 * CREDITS_PER_MB / 1e6 * USD_PER_MILLION_CREDITS, 4),
        "plans": plans,
    }


def _slot_gaps(slots: list[int]) -> dict[str, Any]:
    """Missing slots inside the observed range. A complete feed sees (almost) every slot."""

    if len(slots) < 2:
        return {"observed": len(slots), "expected_span": None, "missing": None}
    span = slots[-1] - slots[0] + 1
    return {
        "observed": len(slots),
        "expected_span": span,
        "missing": span - len(slots),
        "missing_fraction": round(1 - len(slots) / span, 4),
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    config = yaml.safe_load(Path(args.config).read_text())
    rpc_config = config["rpc"]
    key = read_secret_file(Path(rpc_config["helius_api_key_file"]).expanduser(), required=True)
    assert key is not None
    ws_url = rpc_config["websocket_url_template"].format(api_key=key)
    commitment = args.commitment or rpc_config.get("commitment", "confirmed")

    stop_at = time.time() + args.seconds
    log(f"streaming {args.seconds}s at commitment={commitment}")
    live: dict[str, StreamStats] = {}
    tasks = {
        label: asyncio.create_task(
            run_logs_subscription(ws_url, label, program, args.seconds, commitment, stop_at, live)
        )
        for label, program in PROGRAMS.items()
    }
    portal_task = asyncio.create_task(run_pumpportal(stop_at))
    with HeliusRpc(commitment=commitment) as rpc:
        lag_task = asyncio.create_task(watch_slot_lag(rpc, live, stop_at))
        stream_stats: list[StreamStats] = list(await asyncio.gather(*tasks.values()))
        lag_samples = await lag_task
        lag_rpc_calls = rpc.calls
    portal = await portal_task
    log("streams closed")
    atlas: dict[str, Any] | None = None
    if args.atlas_seconds > 0:
        atlas = await probe_transaction_subscribe(key, PUMP_FUN_PROGRAM, commitment, args.atlas_seconds)
    return {
        "atlas": atlas,
        "stats": stream_stats,
        "portal": portal,
        "commitment": commitment,
        "key": key,
        "lag_samples": lag_samples,
        "lag_rpc_calls": lag_rpc_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--label", default="spike")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.yaml"))
    parser.add_argument("--commitment", default=None)
    parser.add_argument("--out", default=".")
    parser.add_argument("--recall-pages", type=int, default=DEFAULT_RECALL_PAGES)
    parser.add_argument(
        "--atlas-seconds",
        type=float,
        default=0.0,
        help="also probe the enhanced `transactionSubscribe` feed (failed:false) for N seconds",
    )
    parser.add_argument("--skip-recall", action="store_true")
    parser.add_argument("--skip-usage", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    usage_before: dict[str, Any] = {}
    result = asyncio.run(main_async(args))
    key = result.pop("key")
    if not args.skip_usage:
        usage_before = usage_probe(key)

    summary: dict[str, Any] = {
        "label": args.label,
        "window_seconds": args.seconds,
        "commitment": result["commitment"],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - args.seconds)),
        "streams": {},
        "pumpportal": {
            "messages": result["portal"]["messages"],
            "creates": len(result["portal"]["mints"]),
            "errors": result["portal"]["errors"],
        },
        "usage_endpoints": usage_before,
        "slot_lag_samples": result["lag_samples"],
        "transaction_subscribe_probe": result["atlas"],
    }

    with HeliusRpc(commitment=result["commitment"]) as rpc:
        for stats in result["stats"]:
            block_times: dict[int, int] = {}
            slots = sorted(stats.slot_first_seen)
            if slots:
                # A thin sample. Kept only as a sanity check on the slot-lag measurement:
                # `blockTime` is a cluster ESTIMATE and disagrees with wall clock by seconds,
                # so `slot_lag_samples` is the number to believe, not this one.
                probe_slots = slots[:: max(1, len(slots) // 8)][:8]
                for slot in probe_slots:
                    try:
                        value = rpc.call("getBlockTime", [slot])
                    except Exception:
                        continue
                    if isinstance(value, int):
                        block_times[slot] = value
            summary["streams"][stats.program_label] = summarize(stats, block_times)

            if not args.skip_recall and len(slots) > 30:
                # Score a slice near the END of the window. Paging walks backwards from the
                # live tip at ~1000 signatures a page, and on a program doing hundreds of
                # transactions per second the budget only reaches back a minute or so -- a
                # slice from the start of a ten-minute window is simply unreachable, which is
                # exactly how the first version of this probe scored zero rows.
                lo, hi = slots[-14], slots[-4]
                log(f"{stats.program_label}: recall probe over slots {lo}..{hi}")
                summary["streams"][stats.program_label]["recall"] = recall_probe(
                    rpc, stats.program_id, stats.sig_slot, lo, hi, args.recall_pages
                )

        # PumpPortal cross-check: every create it saw must be in the pump.fun log stream, and
        # the mint we decoded out of the log must be the mint it independently reported.
        pumpfun = next((s for s in result["stats"] if s.program_label == "pumpfun"), None)
        if pumpfun is not None and result["portal"]["mints"]:
            portal_mints = {m["signature"]: m.get("mint") for m in result["portal"]["mints"]}
            hits = [sig for sig in portal_mints if sig in pumpfun.sig_slot]
            agree = sum(
                1
                for sig in hits
                if sig in pumpfun.created_mints and pumpfun.created_mints[sig] == portal_mints[sig]
            )
            summary["pumpportal"]["cross_check"] = {
                "creates": len(portal_mints),
                "found_in_logs_stream": len(hits),
                "recall": round(len(hits) / len(portal_mints), 4),
                "missing_sample": [s for s in portal_mints if s not in pumpfun.sig_slot][:5],
                "create_event_decoded_from_logs": sum(1 for sig in hits if sig in pumpfun.created_mints),
                "decoded_mint_agrees_with_vendor": agree,
            }
        summary["rpc_calls_spent"] = rpc.calls + result["lag_rpc_calls"]

    combined_mbps = sum((s.get("megabytes_per_second") or 0.0) for s in summary["streams"].values())
    summary["cost"] = {
        "basis": "Helius meters streaming at 20 credits/uncompressed MB (unified 2026-04-07; "
        "WSS metering live for all projects 2026-05-01). Overage $5 per 1M credits.",
        "both_programs": cost_projection(combined_mbps),
        "per_program": {
            label: cost_projection(stream.get("megabytes_per_second") or 0.0)
            for label, stream in summary["streams"].items()
        },
        "event_bearing_bytes_only": cost_projection(
            sum(
                (s.get("megabytes_per_second") or 0.0) * (s.get("bytes_with_event_fraction") or 0.0)
                for s in summary["streams"].values()
            )
        ),
    }

    summary_path = out_dir / f"{args.label}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=False))
    samples_path = out_dir / f"{args.label}-samples.jsonl"
    with samples_path.open("w") as handle:
        for stats in result["stats"]:
            for sample in stats.samples:
                handle.write(json.dumps({"program": stats.program_label, "payload": sample}) + "\n")
    log(f"wrote {summary_path} and {samples_path}")
    print(json.dumps(summary, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
