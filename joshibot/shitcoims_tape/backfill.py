"""Bootstrap history into the tape contract from MELT and RED-PUMP.

Two archives carry things we cannot re-derive:

**MELT** (arXiv:2602.13480) — 41,470 pump.fun launches, ~218M transactions, and *crawled Jito
bundle traces*. The bundle traces are the irreplaceable part: bundle membership is not
recoverable from chain after the fact, and it is the input to MELT's own sharpest ablation
(dropping holding concentration alone costs 0.0036 AUPRC, dropping bundle statistics costs
0.0278, dropping both costs 0.0461 — more than the sum). Re-deriving the 218M transactions
through ``getTransactionsForAddress`` would cost ~21.8M credits, i.e. 2.2 months of the
entire Helius plan. That arithmetic is the whole reason this module exists.

**RED-PUMP** (Zenodo, CC-BY-4.0) — ~860k launch records. Import it as a **launch-metadata
corpus only.** Its OUTCOME labels came from a collector that polled a top-50-newest endpoint,
so each token left view after a median ~2.77 minutes *because other tokens launched*. Those
labels are therefore displacement-censored, and a token labelled "did not graduate" may
simply have graduated after the observer stopped looking. Treating them as graduation ground
truth is how a 24-hour rate becomes a 6-minute rate.

The honest representation, and it is enforced here rather than documented and hoped for:

1. Every RED-PUMP record emits a ``LAUNCH`` event — the metadata is sound.
2. Every RED-PUMP record also emits a ``WatchWindow`` **closed with
   :data:`WatchClose.DISPLACED`**, so ``tape_health`` counts it, the censoring rate is
   non-zero, and ``TapeHealth.complete`` is False for any tape containing this import. A
   study reading it cannot mistake it for a full-horizon sample.
3. The OUTCOME label is written to a **sidecar file that is not tape**, next to the segments
   and never inside them. Joining it is a deliberate act with a censoring flag attached; it
   can never be picked up by accident by something iterating the tape.

The same sidecar mechanism carries MELT's bundle traces, because the frozen tape contract has
no bundle field and inventing one here would fork the interface every other track reads.

**The field maps are UNVERIFIED.** Neither archive was obtainable in this environment, so the
column names below are a best guess at the published schemas and are deliberately in one
overridable place. Re-point :class:`MeltFieldMap` / :class:`RedPumpFieldMap` against the real
archive before trusting an import; the loaders are otherwise complete and are exercised
against synthetic fixtures in the documented shape.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from solders.pubkey import Pubkey

from shitcoims_tape.schema import (
    Callout,
    Chainstamp,
    EventKind,
    Launch,
    Provenance,
    Side,
    TapeError,
    TapeEvent,
    Trade,
    WatchClose,
    WatchWindow,
    parse_amount,
)

LOGGER = logging.getLogger("shitcoims.tape.backfill")

MELT_SOURCE: Final[str] = "melt.arxiv:2602.13480"
RED_PUMP_SOURCE: Final[str] = "red-pump.zenodo"

#: The published collector's measured median time-in-view. Present as a named constant so an
#: operator who supplies it is quoting a measurement rather than inventing a number.
RED_PUMP_MEASURED_DISPLACEMENT_SECONDS: Final[int] = 166  # 2.77 minutes

#: The horizon RED-PUMP's outcome labels are *presented* as covering. The gap between this
#: and the line above is the entire bias.
RED_PUMP_CLAIMED_HORIZON: Final[timedelta] = timedelta(hours=24)


#: The existing ``intelligence.sqlite3`` evidence store. **Its two clocks are inverted between
#: row kinds**, verified by regressing slot on ``emitted_at`` and recovering 0.4213 s/slot,
#: which is Solana's slot time:
#:
#: * ``wallet_transaction`` rows: ``emitted_at`` is BLOCK time, ``observed_at`` is FETCH time.
#: * social rows (``x_mint_mention``, ``x_cashtag``, ``x_kol_post``, ``claudekol_claim``):
#:   ``observed_at`` is POST time, ``emitted_at`` is INGEST time — the exact reverse.
#:
#: The reversal is not cosmetic: the backfiller walks history backwards, so a single fetch at
#: 16:05Z carries the *oldest* slot. Reading ``observed_at`` as trade time therefore inverts
#: the arrow of causation on every event. These importers normalise that convention INTO the
#: contract — chain time to ``Chainstamp``, observer wall-clock to ``observed_at`` — so no
#: downstream consumer ever has to know which kind it is holding.
INTELLIGENCE_TRADE_SOURCE: Final[str] = "intelligence.wallet_transaction"
INTELLIGENCE_CALLOUT_SOURCE: Final[str] = "intelligence.social"

#: Social row kinds in the store whose ``observed_at`` is the post time.
INTELLIGENCE_SOCIAL_KINDS: Final[frozenset[str]] = frozenset(
    {"x_mint_mention", "x_cashtag", "x_kol_post", "claudekol_claim"}
)


class BackfillError(RuntimeError):
    """An archive could not be imported. Fail closed: a half-imported tape lies quietly."""


@dataclass(frozen=True, slots=True)
class MeltFieldMap:
    """Column names in a MELT export. UNVERIFIED — see the module docstring."""

    record_kind: str = "record_type"
    launch_kind: str = "launch"
    trade_kind: str = "trade"
    mint: str = "mint"
    creator: str = "creator"
    name: str = "name"
    symbol: str = "symbol"
    created_at: str = "created_at"
    initial_virtual_sol: str = "initial_virtual_sol_reserves"
    dev_buy_raw: str = "dev_buy_token_amount"
    wallet: str = "trader"
    is_buy: str = "is_buy"
    sol_amount: str = "sol_amount_lamports"
    token_amount: str = "token_amount_raw"
    fee_amount: str = "fee_lamports"
    pool: str = "bonding_curve"
    slot: str = "slot"
    signature: str = "signature"
    block_time: str = "block_time"
    bundle_id: str = "jito_bundle_id"
    bundle_index: str = "jito_bundle_index"
    #: Naive timestamps are refused unless the operator states they are UTC.
    assume_utc: bool = False


@dataclass(frozen=True, slots=True)
class RedPumpFieldMap:
    """Column names in a RED-PUMP export. UNVERIFIED — see the module docstring."""

    mint: str = "mint"
    creator: str = "creator"
    name: str = "name"
    symbol: str = "symbol"
    created_at: str = "created_at"
    outcome: str = "outcome"
    has_twitter: str = "has_twitter"
    has_telegram: str = "has_telegram"
    has_website: str = "has_website"
    #: Optional: when the collector recorded how long it actually watched, use it instead of
    #: the run-wide assumption.
    observed_until: str = "last_seen_at"
    assume_utc: bool = False


@dataclass(frozen=True, slots=True)
class BackfillReport:
    source: str
    records_read: int
    launches: int
    trades: int
    watches: int
    skipped: int
    sidecar_rows: int
    sidecar_path: str | None
    displacement_window_seconds: int | None = None
    callouts: int = 0
    without_block_time: int = 0
    rejected_addresses: int = 0
    ambiguous_multi_leg: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "records_read": self.records_read,
            "launches": self.launches,
            "callouts": self.callouts,
            "trades": self.trades,
            "watches": self.watches,
            "skipped": self.skipped,
            "sidecar_rows": self.sidecar_rows,
            "sidecar_path": self.sidecar_path,
            "displacement_window_seconds": self.displacement_window_seconds,
            "without_block_time": self.without_block_time,
            "rejected_addresses": self.rejected_addresses,
            "ambiguous_multi_leg": self.ambiguous_multi_leg,
        }


class SidecarWriter:
    """Append-only JSONL that is deliberately NOT tape.

    Anything here is either outside the frozen contract (MELT's bundle traces) or unsafe to
    put on the tape (RED-PUMP's censored outcome labels). Keeping it in a separate file means
    a study that iterates the tape cannot pick it up by accident; joining it has to be typed
    out, and every row carries the reason it was quarantined.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._rows = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def rows(self) -> int:
        return self._rows

    def write(self, row: Mapping[str, Any]) -> None:
        self._handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        self._rows += 1

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


def read_records(path: Path) -> Iterator[Mapping[str, Any]]:
    """Read a JSONL or CSV archive into dict rows.

    CSV is accepted on *input* only. The tape itself is JSONL because memecoin symbols
    contain commas, quotes and newlines by design; ``csv.DictReader`` handles them correctly
    when they are properly quoted, and mangles them when the producer did not quote — which
    is a defect of the archive, surfaced here rather than absorbed.
    """

    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson", ".json"}:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise BackfillError(f"{path.name}:{number} is not valid JSON") from exc
                if isinstance(payload, Mapping):
                    yield payload
        return
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    raise BackfillError(f"unsupported archive format: {path.suffix or '(none)'}")


def _timestamp(value: Any, *, assume_utc: bool, field: str) -> datetime:
    """Parse an archive timestamp. A naive one is refused unless explicitly declared UTC."""

    if isinstance(value, bool):
        raise BackfillError(f"{field} is a boolean")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(int(value), UTC)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), UTC)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BackfillError(f"{field} is not ISO-8601 or a unix timestamp") from exc
    if parsed.tzinfo is None:
        if not assume_utc:
            raise BackfillError(
                f"{field} has no timezone; set assume_utc=True on the field map to state "
                f"that this archive's naive timestamps are UTC"
            )
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def strict_pubkey(value: Any, *, field: str) -> str:
    """Decode-check an address, not just its character class.

    The tape contract's ``_MINT`` pattern is a base58 *alphabet* check: it accepts any string
    of legal characters, so a lowercased address passes it unchanged. Decoding to exactly 32
    bytes is strictly stronger — a lowercased pubkey is a different number, and ~3 in 4 of them
    no longer decode to 32 bytes (measured over 500 random keys: 380 rejected, 120 accepted).

    Be honest about what that buys: the remaining quarter is **indistinguishable from a real
    address** and no import-time check can recover it, which is why write-time validation
    belongs in the collector that first sees the string. One in 28 stored mint mentions is
    already corrupt this way. This check narrows the hole; it does not close it.
    """

    text = str(value).strip()
    try:
        Pubkey.from_string(text)
    except (ValueError, TypeError) as exc:
        raise BackfillError(f"{field} is not a 32-byte base58 address") from exc
    return text


def _flag(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"true", "t", "yes", "y", "1"}


def load_melt(
    path: Path,
    *,
    fields: MeltFieldMap | None = None,
    fetched_at: datetime | None = None,
    bundle_sidecar: SidecarWriter | None = None,
) -> Iterator[TapeEvent | BackfillReport]:
    """Stream MELT records as tape events, ending with a :class:`BackfillReport`.

    Launches and trades land on the tape. Jito bundle membership goes to ``bundle_sidecar``
    when one is supplied, because the frozen contract has no bundle field and widening it
    here would fork the interface every other track reads.

    No watch records are emitted. MELT is a *closed historical archive*, not an observation
    this instrument made, so it has no watch window — inventing one would let a survival
    study treat a third party's coverage decisions as ours.
    """

    field_map = fields or MeltFieldMap()
    moment = (fetched_at or datetime.now(UTC)).astimezone(UTC)
    provenance = Provenance(
        source=MELT_SOURCE, fetched_at=moment.isoformat(), cursor=f"file:{path.name}"
    )
    read = launches = trades = skipped = 0
    for row in read_records(path):
        read += 1
        kind = str(row.get(field_map.record_kind, "")).strip().lower()
        try:
            if kind == field_map.launch_kind:
                yield _melt_launch(row, field_map, provenance, moment)
                launches += 1
            elif kind == field_map.trade_kind:
                event = _melt_trade(row, field_map, provenance, moment)
                if bundle_sidecar is not None and row.get(field_map.bundle_id):
                    bundle_sidecar.write(
                        {
                            "source": MELT_SOURCE,
                            "signature": str(row.get(field_map.signature, "")),
                            "bundle_id": str(row.get(field_map.bundle_id)),
                            "bundle_index": row.get(field_map.bundle_index),
                            "note": "jito bundle membership is not recoverable from chain",
                        }
                    )
                yield event
                trades += 1
            else:
                skipped += 1
        except (BackfillError, TapeError, KeyError, TypeError, ValueError) as exc:
            skipped += 1
            LOGGER.warning("MELT record %s skipped: %s", read, type(exc).__name__)
    yield BackfillReport(
        source=MELT_SOURCE,
        records_read=read,
        launches=launches,
        trades=trades,
        watches=0,
        skipped=skipped,
        sidecar_rows=0 if bundle_sidecar is None else bundle_sidecar.rows,
        sidecar_path=None if bundle_sidecar is None else str(bundle_sidecar.path),
    )


def _melt_launch(
    row: Mapping[str, Any], fields: MeltFieldMap, provenance: Provenance, moment: datetime
) -> TapeEvent:
    created = _timestamp(
        row[fields.created_at], assume_utc=fields.assume_utc, field=fields.created_at
    )
    launch = Launch(
        mint=str(row[fields.mint]),
        creator=str(row[fields.creator]),
        name=str(row.get(fields.name, "")),
        symbol=str(row.get(fields.symbol, "")),
        initial_virtual_sol=parse_amount(
            row.get(fields.initial_virtual_sol, 0), field="initial_virtual_sol"
        ),
        dev_buy_raw=parse_amount(row.get(fields.dev_buy_raw, 0), field="dev_buy_raw"),
    )
    chain = _melt_chainstamp(row, fields, block_time_default=int(created.timestamp()))
    return TapeEvent(
        kind=EventKind.LAUNCH,
        # An archive record was observed when we imported it; the chainstamp carries when it
        # happened. Conflating the two is the observer-lag error the schema exists to prevent.
        observed_at=moment.isoformat(),
        provenance=provenance,
        body=launch,
        chain=chain,
    )


def _melt_trade(
    row: Mapping[str, Any], fields: MeltFieldMap, provenance: Provenance, moment: datetime
) -> TapeEvent:
    chain = _melt_chainstamp(row, fields, block_time_default=None)
    if chain is None:
        raise BackfillError("a MELT trade without a signature cannot be ordered")
    is_buy = _flag(row, fields.is_buy)
    sol = parse_amount(row[fields.sol_amount], field="sol_amount")
    tokens = parse_amount(row[fields.token_amount], field="token_amount")
    if sol < 0 or tokens < 0:
        raise BackfillError("MELT trade amounts are magnitudes; sign comes from is_buy")
    pool = row.get(fields.pool)
    trade = Trade(
        mint=str(row[fields.mint]),
        wallet=str(row[fields.wallet]),
        side=Side.BUY if is_buy else Side.SELL,
        sol_delta_lamports=-sol if is_buy else sol,
        token_delta_raw=tokens if is_buy else -tokens,
        pool=str(pool) if pool else None,
        fee_lamports=parse_amount(row.get(fields.fee_amount, 0), field="fee_lamports"),
    )
    return TapeEvent(
        kind=EventKind.TRADE,
        observed_at=moment.isoformat(),
        provenance=provenance,
        body=trade,
        chain=chain,
    )


def _melt_chainstamp(
    row: Mapping[str, Any], fields: MeltFieldMap, *, block_time_default: int | None
) -> Chainstamp | None:
    signature = row.get(fields.signature)
    if not signature:
        return None
    block_time_raw = row.get(fields.block_time)
    block_time = int(block_time_raw) if block_time_raw else block_time_default
    return Chainstamp(
        slot=int(row.get(fields.slot, 0) or 0),
        signature=str(signature),
        block_time=block_time,
    )


def load_red_pump(
    path: Path,
    *,
    displacement_window_seconds: int,
    fields: RedPumpFieldMap | None = None,
    fetched_at: datetime | None = None,
    outcome_sidecar: SidecarWriter | None = None,
) -> Iterator[TapeEvent | BackfillReport]:
    """Stream RED-PUMP records as launches plus DISPLACED watch windows.

    ``displacement_window_seconds`` has **no default on purpose**. How long the original
    collector actually saw each token is the single number that decides what its OUTCOME
    label means, and it is not in the archive. Requiring it forces the operator to state the
    assumption; it is then stamped into ``Provenance.cursor`` so the assumption travels with
    every row it produced and can be audited off the tape years later.
    :data:`RED_PUMP_MEASURED_DISPLACEMENT_SECONDS` is the published measurement.

    Every record yields a watch window that is already closed with ``DISPLACED``. That is not
    a formality: it makes ``tape_health.censoring_rate`` non-zero and ``complete`` False for
    any tape containing this import, which is the correct verdict.
    """

    if displacement_window_seconds <= 0:
        raise ValueError("displacement_window_seconds must be positive")
    field_map = fields or RedPumpFieldMap()
    moment = (fetched_at or datetime.now(UTC)).astimezone(UTC)
    provenance = Provenance(
        source=RED_PUMP_SOURCE,
        fetched_at=moment.isoformat(),
        cursor=(
            f"file:{path.name};displacement_window_s={displacement_window_seconds};"
            f"outcome_labels=censored"
        ),
    )
    read = launches = watches = skipped = 0
    for row in read_records(path):
        read += 1
        try:
            created = _timestamp(
                row[field_map.created_at], assume_utc=field_map.assume_utc, field=field_map.created_at
            )
            launch = Launch(
                mint=str(row[field_map.mint]),
                creator=str(row[field_map.creator]),
                name=str(row.get(field_map.name, "")),
                symbol=str(row.get(field_map.symbol, "")),
                has_twitter=_flag(row, field_map.has_twitter),
                has_telegram=_flag(row, field_map.has_telegram),
                has_website=_flag(row, field_map.has_website),
            )
        except (BackfillError, TapeError, KeyError, TypeError, ValueError):
            skipped += 1
            continue
        yield TapeEvent(
            kind=EventKind.LAUNCH,
            observed_at=moment.isoformat(),
            provenance=provenance,
            body=launch,
            # No chainstamp: RED-PUMP is a launch registry, not a transaction archive, and a
            # fabricated slot would let a study order these against real chain events.
        )
        launches += 1

        observed_until = row.get(field_map.observed_until)
        if observed_until:
            closed = _timestamp(
                observed_until, assume_utc=field_map.assume_utc, field=field_map.observed_until
            )
        else:
            closed = created + timedelta(seconds=displacement_window_seconds)
        yield TapeEvent(
            kind=EventKind.WATCH,
            observed_at=moment.isoformat(),
            provenance=provenance,
            body=WatchWindow(
                mint=launch.mint,
                opened_at=created.isoformat(),
                # The deadline is the horizon the labels are *presented* as covering. The gap
                # between it and closed_at is the bias, made measurable instead of asserted.
                deadline=(created + RED_PUMP_CLAIMED_HORIZON).isoformat(),
                closed_at=closed.isoformat(),
                close_reason=WatchClose.DISPLACED,
            ),
        )
        watches += 1

        if outcome_sidecar is not None and field_map.outcome in row:
            outcome_sidecar.write(
                {
                    "source": RED_PUMP_SOURCE,
                    "mint": launch.mint,
                    "outcome": row[field_map.outcome],
                    "censoring": "displacement",
                    "observed_seconds": int((closed - created).total_seconds()),
                    "claimed_horizon_seconds": int(RED_PUMP_CLAIMED_HORIZON.total_seconds()),
                    "is_graduation_ground_truth": False,
                    "note": (
                        "collector polled a top-50-newest endpoint; a token labelled "
                        "not-graduated may have graduated after it left view"
                    ),
                }
            )
    yield BackfillReport(
        source=RED_PUMP_SOURCE,
        records_read=read,
        launches=launches,
        trades=0,
        watches=watches,
        skipped=skipped,
        sidecar_rows=0 if outcome_sidecar is None else outcome_sidecar.rows,
        sidecar_path=None if outcome_sidecar is None else str(outcome_sidecar.path),
        displacement_window_seconds=displacement_window_seconds,
    )


def load_intelligence_wallet_transactions(
    rows: Iterable[Mapping[str, Any]],
    *,
    fetched_at: datetime | None = None,
) -> Iterator[TapeEvent | BackfillReport]:
    """Import stored ``wallet_transaction`` observations, un-inverting their two clocks.

    For these rows the store puts **block time in ``emitted_at``** and **fetch time in
    ``observed_at``** — the reverse of its own social rows. Here the block time becomes
    ``Chainstamp.block_time`` and the fetch time becomes ``TapeEvent.observed_at``, which is
    what those fields mean everywhere in the contract. After this import nothing downstream
    has to remember the store's convention, because the convention no longer exists.

    Three refusals, each a defect the store accepted and the contract does not:

    * **A malformed address is refused, never coerced.** Base58 is case-sensitive, so a
      lowercased 44-character address is unrecoverable; it is counted, not repaired.
    * **A multi-leg transaction is skipped, not split.** One native SOL delta against several
      token legs has no unambiguous per-leg price, and dividing it evenly — as the existing
      projection does — fabricates a number that no downstream study can distinguish from a
      measurement.
    * **A failed transaction is skipped.** It moved nothing.

    A row with no block time is **kept**, not dropped: the slot is still an exact ordering and
    an approximate clock at ~0.4213 s/slot. It is counted so a timed study knows its
    denominator, which is the part that matters — around 11% of the store's chain rows are in
    this state.
    """

    del fetched_at  # every row carries its own observer stamp; a run-wide one would mask it
    read = trades = skipped = no_block_time = rejected = multi_leg = 0
    for row in rows:
        read += 1
        payload = row.get("payload")
        if not isinstance(payload, Mapping) or payload.get("succeeded") is False:
            skipped += 1
            continue
        legs = [
            leg
            for leg in (payload.get("token_deltas") or [])
            if isinstance(leg, Mapping) and int(leg.get("raw_delta") or 0) != 0
        ]
        if len(legs) != 1:
            multi_leg += 1
            skipped += 1
            continue
        try:
            # emitted_at is BLOCK time for this row kind. observed_at is our fetch.
            emitted = row.get("emitted_at")
            block_time = (
                int(_timestamp(emitted, assume_utc=False, field="emitted_at").timestamp())
                if emitted
                else None
            )
            if block_time is None:
                no_block_time += 1
            seen = _timestamp(row["observed_at"], assume_utc=False, field="observed_at")
            raw_delta = int(legs[0]["raw_delta"])
            sol_delta = parse_amount(payload["sol_delta_lamports"], field="sol_delta_lamports")
            fee = (
                parse_amount(payload.get("fee_lamports") or 0, field="fee_lamports")
                if payload.get("wallet_paid_fee")
                else 0
            )
            event = TapeEvent(
                kind=EventKind.TRADE,
                observed_at=seen.isoformat(),
                provenance=Provenance(
                    source=INTELLIGENCE_TRADE_SOURCE,
                    fetched_at=seen.isoformat(),
                    cursor="clocks_uninverted:emitted_at->chain,observed_at->observer",
                ),
                chain=Chainstamp(
                    slot=int(payload["slot"]),
                    signature=str(payload["signature"]),
                    block_time=block_time,
                    tx_index=payload.get("transaction_index"),
                ),
                body=Trade(
                    mint=strict_pubkey(legs[0]["mint"], field="mint"),
                    wallet=strict_pubkey(row["subject_id"], field="wallet"),
                    side=Side.BUY if raw_delta > 0 else Side.SELL,
                    sol_delta_lamports=sol_delta,
                    token_delta_raw=raw_delta,
                    fee_lamports=fee,
                ),
            )
        except (TapeError, BackfillError) as exc:
            # An address the contract or the decode check refuses is corrupt at the source
            # and unrecoverable. Counted, never coerced into something that parses.
            if isinstance(exc, TapeError) or "address" in str(exc):
                rejected += 1
            skipped += 1
            continue
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        yield event
        trades += 1
    yield BackfillReport(
        source=INTELLIGENCE_TRADE_SOURCE,
        records_read=read,
        launches=0,
        trades=trades,
        watches=0,
        skipped=skipped,
        sidecar_rows=0,
        sidecar_path=None,
        without_block_time=no_block_time,
        rejected_addresses=rejected,
        ambiguous_multi_leg=multi_leg,
    )


def load_intelligence_callouts(
    rows: Iterable[Mapping[str, Any]],
    *,
    fetched_at: datetime | None = None,
) -> Iterator[TapeEvent | BackfillReport]:
    """Import stored social observations as CALLOUT events, un-inverting their two clocks.

    For social rows the store puts the **post time in ``observed_at``** and the ingest stamp
    in ``emitted_at`` — the opposite of its chain rows. The post time is the causal origin, so
    it is preserved in ``Provenance.cursor`` as ``posted_at=...``; ``TapeEvent.observed_at``
    keeps its single contract-wide meaning of "when we saw it" and carries the ingest stamp.
    The frozen ``Callout`` has no field for a post time, which is the gap that forces this.

    Only rows that resolve to an actual mint become callouts. A cashtag is a *claim*, not an
    identifier, and pooling the two corrupts the study — which is why ``resolved_from``
    records how the mint was identified.
    """

    moment = (fetched_at or datetime.now(UTC)).astimezone(UTC)
    read = callouts = skipped = rejected = 0
    for row in rows:
        read += 1
        kind = str(row.get("kind") or "")
        payload = row.get("payload")
        if kind not in INTELLIGENCE_SOCIAL_KINDS or not isinstance(payload, Mapping):
            skipped += 1
            continue
        mint = payload.get("mint") or (
            row.get("subject_id") if row.get("subject_type") == "token" else None
        )
        if not mint:
            skipped += 1
            continue
        try:
            posted = _timestamp(row["observed_at"], assume_utc=False, field="observed_at")
            ingested = (
                _timestamp(row["emitted_at"], assume_utc=False, field="emitted_at")
                if row.get("emitted_at")
                else moment
            )
            text = str(payload.get("text") or payload.get("url") or row.get("source_native_id") or "")
            event = TapeEvent(
                kind=EventKind.CALLOUT,
                observed_at=ingested.isoformat(),
                provenance=Provenance(
                    source=INTELLIGENCE_CALLOUT_SOURCE,
                    fetched_at=ingested.isoformat(),
                    cursor=f"posted_at={posted.isoformat()};kind={kind}",
                ),
                body=Callout(
                    mint=strict_pubkey(mint, field="mint"),
                    platform=str(row.get("source_id") or "unknown"),
                    author=str(payload.get("author_username") or "unknown"),
                    resolved_from=kind,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    author_followers=parse_amount(
                        payload.get("author_followers") or 0, field="author_followers"
                    ),
                    engagement=parse_amount(
                        (payload.get("like_count") or 0) + (payload.get("retweet_count") or 0),
                        field="engagement",
                    ),
                ),
            )
        except (TapeError, BackfillError):
            rejected += 1
            skipped += 1
            continue
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        yield event
        callouts += 1
    yield BackfillReport(
        source=INTELLIGENCE_CALLOUT_SOURCE,
        records_read=read,
        launches=0,
        trades=0,
        watches=0,
        skipped=skipped,
        sidecar_rows=0,
        sidecar_path=None,
        callouts=callouts,
        rejected_addresses=rejected,
    )
