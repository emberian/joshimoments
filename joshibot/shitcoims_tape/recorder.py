"""The tape recorder: chain transactions in, tape JSONL out.

Build order item #1 in PROGRAM.md, and it is first for one reason — *data compounds
regardless of which strategy eventually wins, and it cannot be recorded retroactively*. A
launch that happened while nothing was listening is gone; a model trained next month can be
retrained.

**Decoding is reused, not reinvented.** ``shitcoims_intelligence.pump`` already holds
hand-audited Borsh layouts pinned to a specific pump-public-docs commit, with a fail-closed
quarantine path. This module supplies the one thing that decoder deliberately does not do —
*attribution*: a ``Program data:`` log line is only trustworthy if you know which program
emitted it, which means tracking the invocation stack across ``Program <id> invoke [n]`` and
``Program <id> success``. Attributing by discriminator alone lets any program forge a pump
event into our tape.

**The money path is integers, end to end.** ``sol_amount``/``token_amount`` arrive as u64 and
stay ``int``; the tape serialises them as strings. No float touches a raw amount.

**Fee convention, stated once so replay can reconcile.** ``Trade.sol_delta_lamports`` is the
*curve leg only*, signed: ``-sol_amount`` on a buy, ``+sol_amount`` on a sell.
``Trade.fee_lamports`` is the sum of the protocol fee, the creator fee and the buyback fee.
``cashback`` is a rebate, not a fee, and is deliberately excluded. Splitting it this way is
what makes ``sol_delta`` reconcile exactly against the recorded reserves under the AMM
identity, with fees as a separate, additive term.

**Non-SOL quote pools are skipped, not coerced.** Both pump and PumpSwap events carry a
``quote_mint``. When it is not wrapped SOL, ``quote_amount``/``sol_amount`` are not lamports,
and writing them into ``sol_delta_lamports`` would be a unit error of exactly the kind that
cost this desk 7.47 SOL. Those events are counted and dropped.

Credit arithmetic (Helius Developer, $49/mo = 10M credits):

* ``getTransactionsForAddress`` costs **10 credits per 100 transactions** = 0.1 credits/tx.
  One full page is therefore :data:`CREDITS_PER_TRANSACTION_PAGE`.
* The Enhanced Transactions API costs **100 credits per call** — 1000x worse per transaction.
  This module never calls it; that is why the Borsh decoding lives here at all.
* MELT's 218M transactions would cost ~21.8M credits, i.e. **2.2 months of the entire plan**
  to re-derive. That is the whole argument for :mod:`shitcoims_tape.backfill`.
* Practical budget: at a mean ~120 transactions per watched mint, one mint's full history is
  ~12 credits. A 100k-credit run (1% of the monthly allowance) backfills ~8,300 mints.
  pump.fun launches tens of thousands of tokens a day, so **per-mint history polling can
  never cover the firehose** — it is for targeted backfill of already-watched mints, and
  full coverage has to come from a program-level subscription.

Read-only, always. Nothing in this module signs, submits, or reads a wallet key.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from shitcoims_intelligence.pump import (
    AdvisoryPumpEvent,
    PumpValue,
    QuarantinedPumpEvent,
    decode_pump_event,
)
from shitcoims_intelligence.pump_layouts import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID
from shitcoims_tape.schema import (
    Callout,
    Chainstamp,
    EventKind,
    Launch,
    Provenance,
    Reserves,
    Side,
    TapeError,
    TapeEvent,
    Trade,
    WatchClose,
)
from shitcoims_tape.watch import WatchRegistry

LOGGER = logging.getLogger("shitcoims.tape.recorder")

WRAPPED_SOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"

#: One page of ``getTransactionsForAddress`` is <=100 transactions at 10 credits per 100.
CREDITS_PER_TRANSACTION_PAGE: Final[int] = 10
#: The Enhanced Transactions API. Recorded here only so the comparison is on the page; the
#: recorder must never call it, and :meth:`CreditBudget.charge` is never invoked with it.
CREDITS_PER_ENHANCED_CALL: Final[int] = 100

_LOG_DATA_PREFIX: Final[str] = "Program data: "
_INVOKE = re.compile(r"^Program ([1-9A-HJ-NP-Za-km-z]{32,44}) invoke \[(\d+)\]$")
_RESULT = re.compile(r"^Program ([1-9A-HJ-NP-Za-km-z]{32,44}) (success|failed.*)$")
_TRUNCATED = "Log truncated"

_PUMP_PROGRAMS: Final[frozenset[str]] = frozenset({PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID})


class RecorderError(RuntimeError):
    """A recorder-level failure. Sanitised: never carries a credentialed URL."""


class CreditBudgetExceeded(RecorderError):
    """The run would spend more Helius credits than it was authorised to spend."""


@dataclass(slots=True)
class CreditBudget:
    """A hard ceiling on Helius spend for one run. Fail closed, never best-effort."""

    limit: int
    spent: int = 0

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError("credit limit must not be negative")

    @property
    def remaining(self) -> int:
        return max(self.limit - self.spent, 0)

    def can_afford(self, credits: int) -> bool:
        return self.spent + credits <= self.limit

    def charge(self, credits: int) -> int:
        if credits <= 0:
            raise ValueError("a credit charge must be positive")
        if not self.can_afford(credits):
            raise CreditBudgetExceeded(
                f"budget of {self.limit} credits exhausted at {self.spent}; "
                f"a further {credits} was requested"
            )
        self.spent += credits
        return self.spent


# --- program-invocation-stack attribution ------------------------------------------


@dataclass(frozen=True, slots=True)
class AttributedLog:
    """One ``Program data:`` payload, with the program that actually emitted it."""

    program_id: str
    depth: int
    payload: str


@dataclass(frozen=True, slots=True)
class Custody:
    """Who signed a transaction, and who merely paid for it.

    Kept as one object so the two can never be threaded independently and swapped. Signing
    requires the private key and is the strongest entity-resolution evidence available;
    paying a fee requires nothing at all, and merging on it fuses unrelated actors — in the
    live store a single sponsor touched both watched wallets.
    """

    signers: tuple[str, ...] = ()
    fee_payer: str | None = None


#: The empty custody. A module-level singleton so it can be an argument default: a frozen
#: value is safe to share, and "we recorded no custody evidence" must be one identity rather
#: than a fresh object per call site.
NO_CUSTODY: Final[Custody] = Custody()


def resolve_pool_facts(
    transaction: Mapping[str, Any], pool: str
) -> tuple[str, str] | None:
    """Learn a pool's (base, quote) mints from the transaction's own token balances.

    Without this the recorder can only attribute trades on pools whose ``CreatePoolEvent`` it
    personally witnessed — so a recorder started today records NOTHING for any already-migrated
    token, permanently, because that event happened weeks ago and never comes again. Found by
    replaying real transactions: 27 of 27 decoded AMM trades were dropped as unattributed.

    The pool holds a token account per side, and jsonParsed balances name the owner and mint of
    each, so the pair is recoverable with no extra RPC. Fails closed: anything other than
    exactly two distinct mints, one of them wrapped SOL, returns ``None`` rather than a guess —
    attributing a trade to the wrong mint is worse than not recording it.
    """
    meta = transaction.get("meta")
    if not isinstance(meta, Mapping):
        return None
    mints: set[str] = set()
    for key in ("preTokenBalances", "postTokenBalances"):
        balances = meta.get(key)
        if not isinstance(balances, Sequence) or isinstance(balances, str | bytes):
            continue
        for balance in balances:
            if not isinstance(balance, Mapping):
                continue
            if balance.get("owner") != pool:
                continue
            mint = balance.get("mint")
            if isinstance(mint, str):
                mints.add(mint)
    if len(mints) != 2 or WRAPPED_SOL_MINT not in mints:
        return None
    base = next(mint for mint in mints if mint != WRAPPED_SOL_MINT)
    return base, WRAPPED_SOL_MINT


def extract_custody(transaction: Mapping[str, Any]) -> Custody:
    """Pull the signer set and fee payer out of a jsonParsed transaction.

    In jsonParsed form each account key carries its own ``signer`` flag, and the fee payer is
    by protocol the first account. Anything malformed yields an EMPTY custody rather than a
    guess: a wrong signer set is worse than none, because it would be treated as strong
    evidence of shared key custody.
    """
    inner = transaction.get("transaction")
    message = inner.get("message") if isinstance(inner, Mapping) else None
    keys = message.get("accountKeys") if isinstance(message, Mapping) else None
    if not isinstance(keys, Sequence) or isinstance(keys, str | bytes) or not keys:
        return NO_CUSTODY
    signers: list[str] = []
    fee_payer: str | None = None
    for index, key in enumerate(keys):
        if isinstance(key, Mapping):
            pubkey = key.get("pubkey")
            is_signer = bool(key.get("signer"))
        else:
            pubkey, is_signer = key, index == 0
        if not isinstance(pubkey, str):
            continue
        if index == 0:
            fee_payer = pubkey
        if is_signer:
            signers.append(pubkey)
    return Custody(signers=tuple(signers), fee_payer=fee_payer)


@dataclass(frozen=True, slots=True)
class AttributedLogs:
    entries: tuple[AttributedLog, ...]
    truncated: bool
    unbalanced: bool


def attribute_program_data(log_messages: Sequence[str]) -> AttributedLogs:
    """Attribute every ``Program data:`` line to the program on top of the invoke stack.

    Attribution cannot be inferred from the Anchor discriminator: any program may emit any
    eight bytes it likes. Only the runtime's own ``invoke``/``success`` bracketing says who
    was executing, so that is what we track.

    Two failure modes are reported rather than hidden. ``truncated`` means the validator cut
    the log (``Log truncated``), so events are *missing* from this transaction — a study
    counting trades per token must know. ``unbalanced`` means the invoke/result brackets did
    not match, which makes every attribution after that point untrustworthy.
    """

    stack: list[str] = []
    entries: list[AttributedLog] = []
    truncated = False
    unbalanced = False
    for line in log_messages:
        if not isinstance(line, str):
            unbalanced = True
            continue
        if line.startswith(_TRUNCATED):
            truncated = True
            continue
        invoke = _INVOKE.match(line)
        if invoke is not None:
            depth = int(invoke.group(2))
            if depth != len(stack) + 1:
                unbalanced = True
            stack.append(invoke.group(1))
            continue
        result = _RESULT.match(line)
        if result is not None:
            if not stack or stack[-1] != result.group(1):
                unbalanced = True
                if stack:
                    stack.pop()
                continue
            stack.pop()
            continue
        if line.startswith(_LOG_DATA_PREFIX):
            if not stack:
                unbalanced = True
                continue
            entries.append(
                AttributedLog(
                    program_id=stack[-1],
                    depth=len(stack),
                    payload=line[len(_LOG_DATA_PREFIX) :],
                )
            )
    if stack:
        unbalanced = True
    return AttributedLogs(tuple(entries), truncated=truncated, unbalanced=unbalanced)


# --- decoded-event -> tape ----------------------------------------------------------


@dataclass(slots=True)
class RecorderCounters:
    """Everything the recorder chose not to write, and why. Reported, never inferred."""

    transactions_seen: int = 0
    transactions_failed: int = 0
    transactions_truncated_logs: int = 0
    transactions_unbalanced_logs: int = 0
    events_decoded: int = 0
    events_quarantined: int = 0
    events_foreign_program: int = 0
    chain_without_block_time: int = 0
    tape_events_written: int = 0
    tape_events_deduped: int = 0
    launches: int = 0
    callouts: int = 0
    trades: int = 0
    reserves: int = 0
    graduations: int = 0
    deaths: int = 0
    non_sol_quote_skipped: int = 0
    unattributed_pool_skipped: int = 0
    pools_resolved_from_balances: int = 0
    rejected_by_schema: int = 0

    def to_json(self) -> dict[str, int]:
        return {
            "transactions_seen": self.transactions_seen,
            "transactions_failed": self.transactions_failed,
            "transactions_truncated_logs": self.transactions_truncated_logs,
            "transactions_unbalanced_logs": self.transactions_unbalanced_logs,
            "events_decoded": self.events_decoded,
            "events_quarantined": self.events_quarantined,
            "events_foreign_program": self.events_foreign_program,
            "chain_without_block_time": self.chain_without_block_time,
            "tape_events_written": self.tape_events_written,
            "tape_events_deduped": self.tape_events_deduped,
            "launches": self.launches,
            "callouts": self.callouts,
            "trades": self.trades,
            "reserves": self.reserves,
            "graduations": self.graduations,
            "deaths": self.deaths,
            "non_sol_quote_skipped": self.non_sol_quote_skipped,
            "unattributed_pool_skipped": self.unattributed_pool_skipped,
            "pools_resolved_from_balances": self.pools_resolved_from_balances,
            "rejected_by_schema": self.rejected_by_schema,
        }


@dataclass(frozen=True, slots=True)
class PoolFacts:
    """What we learned about a pool from a create/migration event.

    Trades on PumpSwap name only the pool, never the mint, so without this map a migrated
    token's trades cannot be attributed at all. Missing entries are counted rather than
    guessed: attributing a trade to the wrong mint is worse than not recording it.
    """

    base_mint: str
    quote_mint: str


EventSink = Callable[[TapeEvent], bool]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _u64(fields: Mapping[str, PumpValue], name: str) -> int:
    value = fields.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecorderError(f"pump event field {name} is not an integer")
    return int(value)


def _pubkey(fields: Mapping[str, PumpValue], name: str) -> str:
    value = fields.get(name)
    if not isinstance(value, str):
        raise RecorderError(f"pump event field {name} is not a pubkey")
    return value


def _text(fields: Mapping[str, PumpValue], name: str) -> str:
    value = fields.get(name)
    return value if isinstance(value, str) else ""


@dataclass(slots=True)
class _Pending:
    """One transaction's decoded events, held so a dev buy can be joined to its launch."""

    events: list[tuple[AttributedLog, AdvisoryPumpEvent]] = field(default_factory=list)


class TapeRecorder:
    """Turns chain transactions into tape events and drives the watch registry.

    The recorder owns no transport. It is handed already-fetched transactions, which is what
    makes the same object usable for a live subscription, for bounded HTTP backfill, and for
    a fixture in a test — and what keeps the credentialed-URL discipline in one place
    (``shitcoims_intelligence.helius``) instead of mirrored here.
    """

    def __init__(
        self,
        sink: EventSink,
        watches: WatchRegistry,
        *,
        source: str = "helius.getTransactionsForAddress",
        clock: Callable[[], datetime] = _utc_now,
        open_watch_on_launch: bool = True,
    ) -> None:
        self._sink = sink
        self._watches = watches
        self._source = source
        self._clock = clock
        self._open_watch_on_launch = open_watch_on_launch
        self._counters = RecorderCounters()
        self._curve_by_mint: dict[str, str] = {}
        self._pool_facts: dict[str, PoolFacts] = {}

    @property
    def counters(self) -> RecorderCounters:
        return self._counters

    @property
    def watches(self) -> WatchRegistry:
        return self._watches

    def record_transaction(
        self,
        transaction: Mapping[str, Any],
        *,
        cursor: str | None = None,
        observed_at: datetime | None = None,
    ) -> int:
        """Record one full jsonParsed transaction. Returns tape events written."""

        self._counters.transactions_seen += 1
        moment = observed_at.astimezone(UTC) if observed_at is not None else self._clock()
        meta = transaction.get("meta")
        if not isinstance(meta, Mapping):
            return 0
        if meta.get("err") is not None:
            # A failed transaction changed no reserves and moved no tokens. Recording it
            # would inflate every intensity estimate with attempts that never happened.
            self._counters.transactions_failed += 1
            return 0
        chain = self._chainstamp(transaction)
        if chain is None:
            return 0
        if chain.block_time is None:
            # ~11% of the existing store's chain rows have no block time. Slot is still an
            # exact ordering AND an approximate clock (Solana runs ~0.4213 s/slot), so the
            # event is kept and the gap is counted -- dropping 11% of the tape to avoid
            # admitting a missing field would be the worse trade, and guessing a timestamp
            # would be the unforgivable one.
            self._counters.chain_without_block_time += 1
        logs = meta.get("logMessages")
        if not isinstance(logs, Sequence) or isinstance(logs, str | bytes):
            return 0
        attributed = attribute_program_data(list(logs))
        if attributed.truncated:
            self._counters.transactions_truncated_logs += 1
        if attributed.unbalanced:
            self._counters.transactions_unbalanced_logs += 1

        pending = _Pending()
        for entry in attributed.entries:
            if entry.program_id not in _PUMP_PROGRAMS:
                self._counters.events_foreign_program += 1
                continue
            decoded = decode_pump_event(program_id=entry.program_id, data=entry.payload)
            if isinstance(decoded, QuarantinedPumpEvent):
                self._counters.events_quarantined += 1
                continue
            self._counters.events_decoded += 1
            pending.events.append((entry, decoded))

        provenance = Provenance(
            source=self._source, fetched_at=moment.isoformat(), cursor=cursor
        )
        custody = extract_custody(transaction)
        self._learn_pools_from(transaction, pending)
        written = 0
        for entry, decoded in pending.events:
            written += self._emit_for(
                entry,
                decoded,
                pending,
                chain=chain,
                moment=moment,
                provenance=provenance,
                custody=custody,
            )
        return written

    def record_transactions(
        self,
        transactions: Sequence[Mapping[str, Any]],
        *,
        cursor: str | None = None,
        observed_at: datetime | None = None,
    ) -> int:
        return sum(
            self.record_transaction(item, cursor=cursor, observed_at=observed_at)
            for item in transactions
        )

    def watch(self, mints: Sequence[str], *, now: datetime | None = None) -> int:
        """Open a clock watch on each of an explicit set of mints. Returns admissions.

        Launch-driven watching covers the firehose; this covers the other entry point — a
        mint list supplied by an operator or an upstream selector. Refusals at capacity are
        recorded as DISPLACED by the registry either way, so a truncated set is never silent.
        """

        return sum(1 for mint in mints if self._watches.open(mint, now=now).admitted)

    def record_callout(
        self,
        callout: Callout,
        *,
        posted_at: datetime,
        source: str,
        observed_at: datetime | None = None,
        watch: bool = True,
    ) -> int:
        """Record an exogenous attention event and start watching the mint it names.

        This is the join the callout->flow study needs and could not have: the existing
        intelligence store collects ``getTransactionsForAddress`` over a handful of *wallets*,
        so a called-out mint's own trades were never collected and the spike came back
        UNRESOLVABLE rather than null. Opening a WatchWindow on the *mint* at callout time,
        and pulling that mint's history, is what makes the intensity response measurable.

        **Where the post time goes, and why not in ``observed_at``.** ``posted_at`` is the
        causal origin; ``observed_at`` means "when we saw it" and is kept to that ONE meaning
        for every event kind, because a field whose sense flips between kinds is precisely the
        defect that made the existing store's two clocks inverted between social and chain
        rows. The frozen contract has no ``posted_at`` on :class:`Callout` and no non-chain
        origin on :class:`TapeEvent`, so the origin is recorded twice in typed, unambiguous
        places instead: as the ``opened_at`` of the WatchWindow this opens — which is also
        the observation window the intensity study needs — and redundantly in
        ``Provenance.cursor``. That gap in the contract is worth closing at the source.

        Credit arithmetic: ~28 mint-resolved callouts/day at one 100-transaction page each is
        280 credits/day, ~8.4k/month = **0.084%** of a 10M plan; five pages per mint is still
        only ~0.42%. Mint-scoped collection is cheap precisely because callouts are rare.
        """

        origin = posted_at.astimezone(UTC)
        moment = (observed_at or self._clock()).astimezone(UTC)
        written = self._write(
            EventKind.CALLOUT,
            callout,
            moment=moment,
            provenance=Provenance(
                source=source,
                fetched_at=moment.isoformat(),
                cursor=f"posted_at={origin.isoformat()}",
            ),
            chain=None,
        )
        self._counters.callouts += 1
        if watch:
            self._watches.open(callout.mint, now=origin)
        return written

    def expire_watches(self, *, now: datetime | None = None) -> int:
        """Close every watch whose clock deadline passed. Drive this on a timer."""

        return len(self._watches.expire(now=now))

    def mark_died(self, mint: str, *, now: datetime | None = None) -> bool:
        """Terminal outcome supplied by an external classifier. Never inferred from silence."""

        closed = self._watches.died(mint, now=now)
        if closed is not None:
            self._counters.deaths += 1
        return closed is not None

    # -- per-event emission --------------------------------------------------------

    def _emit_for(
        self,
        entry: AttributedLog,
        decoded: AdvisoryPumpEvent,
        pending: _Pending,
        *,
        chain: Chainstamp,
        moment: datetime,
        provenance: Provenance,
        custody: Custody = NO_CUSTODY,
    ) -> int:
        name = decoded.event_name
        try:
            if name == "CreateEvent":
                return self._on_create(decoded, pending, chain=chain, moment=moment, provenance=provenance)
            if name == "TradeEvent":
                return self._on_curve_trade(
                    entry,
                    decoded,
                    chain=chain,
                    moment=moment,
                    provenance=provenance,
                    custody=custody,
                )
            if name in {"CompleteEvent", "CompletePumpAmmMigrationEvent"}:
                return self._on_graduation(decoded, moment=moment, chain=chain)
            if name == "CreatePoolEvent":
                return self._on_create_pool(decoded, chain=chain, moment=moment, provenance=provenance)
            if name in {"BuyEvent", "SellEvent"}:
                return self._on_amm_trade(
                    entry,
                    decoded,
                    chain=chain,
                    moment=moment,
                    provenance=provenance,
                    custody=custody,
                )
            if name == "WithdrawEvent":
                return self._on_withdraw(decoded, moment=moment, chain=chain)
        except TapeError:
            # The contract refused the record. That is the schema doing its job; count it
            # loudly rather than downgrading the field until it fits.
            self._counters.rejected_by_schema += 1
            LOGGER.warning("tape contract rejected a %s record", name)
            return 0
        except RecorderError:
            self._counters.rejected_by_schema += 1
            LOGGER.warning("malformed %s field layout", name)
            return 0
        return 0

    def _on_create(
        self,
        decoded: AdvisoryPumpEvent,
        pending: _Pending,
        *,
        chain: Chainstamp,
        moment: datetime,
        provenance: Provenance,
    ) -> int:
        fields = decoded.fields
        mint = _pubkey(fields, "mint")
        curve = _pubkey(fields, "bonding_curve")
        self._curve_by_mint[mint] = curve
        written = 0
        launch = Launch(
            mint=mint,
            creator=_pubkey(fields, "creator"),
            name=_text(fields, "name"),
            symbol=_text(fields, "symbol"),
            # has_twitter/has_telegram/has_website are NOT observable from CreateEvent: the
            # socials live in the off-chain JSON behind `uri`, which this recorder does not
            # fetch. The frozen contract has no "unknown" state for them, so they stay at the
            # dataclass default and the provenance source says the record came from
            # `pump.CreateEvent` -- meaning unobserved, not observed-absent. Any study using
            # these flags must join a metadata sidecar first.
            initial_virtual_sol=_u64(fields, "virtual_sol_reserves"),
            dev_buy_raw=self._dev_buy_raw(mint, pending),
        )
        written += self._write(
            EventKind.LAUNCH, launch, moment=moment, provenance=provenance, chain=chain
        )
        self._counters.launches += 1
        written += self._write_reserves(
            pool=curve,
            virtual_sol=_u64(fields, "virtual_sol_reserves"),
            virtual_tokens=_u64(fields, "virtual_token_reserves"),
            real_sol=0,  # a curve holds no real SOL before its first buy; this is a fact
            real_tokens=_u64(fields, "real_token_reserves"),
            moment=moment,
            provenance=provenance,
            chain=chain,
        )
        if self._open_watch_on_launch:
            # Anchor the watch to CHAIN time. Time-to-graduation measured on the observer
            # clock is observer lag plus the truth, and for a replay of a capture it is zero.
            self._watches.open(mint, now=moment, chain=chain)
        return written

    @staticmethod
    def _dev_buy_raw(mint: str, pending: _Pending) -> int:
        """The creator's buy inside the create transaction, if there was one.

        98.7% of launches carry one, so its *presence* is uninformative; its *size* relative
        to the bundle-adjusted top-10 is the signal MELT's ablation actually found. Recording
        it at launch time is the only moment it is unambiguous.
        """

        for _entry, decoded in pending.events:
            if decoded.event_name != "TradeEvent":
                continue
            fields = decoded.fields
            if fields.get("mint") != mint or not bool(fields.get("is_buy")):
                continue
            amount = fields.get("token_amount")
            if isinstance(amount, int) and not isinstance(amount, bool):
                return int(amount)
        return 0

    def _on_curve_trade(
        self,
        entry: AttributedLog,
        decoded: AdvisoryPumpEvent,
        *,
        chain: Chainstamp,
        moment: datetime,
        provenance: Provenance,
        custody: Custody = NO_CUSTODY,
    ) -> int:
        fields = decoded.fields
        if _pubkey(fields, "quote_mint") != WRAPPED_SOL_MINT:
            self._counters.non_sol_quote_skipped += 1
            return 0
        mint = _pubkey(fields, "mint")
        is_buy = bool(fields.get("is_buy"))
        sol_amount = _u64(fields, "sol_amount")
        token_amount = _u64(fields, "token_amount")
        pool = self._curve_by_mint.get(mint)
        trade = Trade(
            mint=mint,
            wallet=_pubkey(fields, "user"),
            side=Side.BUY if is_buy else Side.SELL,
            sol_delta_lamports=-sol_amount if is_buy else sol_amount,
            token_delta_raw=token_amount if is_buy else -token_amount,
            pool=pool,
            fee_lamports=_u64(fields, "fee")
            + _u64(fields, "creator_fee")
            + _u64(fields, "buyback_fee"),
            routed_via_frontend=_routed_via_frontend(entry),
            signers=custody.signers,
            fee_payer=custody.fee_payer,
        )
        written = self._write(
            EventKind.TRADE, trade, moment=moment, provenance=provenance, chain=chain
        )
        self._counters.trades += 1
        if pool is None:
            # The curve address comes from CreateEvent. Recording a reserve reading against
            # an unknown pool would put two different tokens' depth under one key.
            self._counters.unattributed_pool_skipped += 1
            return written
        written += self._write_reserves(
            pool=pool,
            virtual_sol=_u64(fields, "virtual_sol_reserves"),
            virtual_tokens=_u64(fields, "virtual_token_reserves"),
            real_sol=_u64(fields, "real_sol_reserves"),
            real_tokens=_u64(fields, "real_token_reserves"),
            moment=moment,
            provenance=provenance,
            chain=chain,
        )
        return written

    def _on_graduation(
        self, decoded: AdvisoryPumpEvent, *, moment: datetime, chain: Chainstamp
    ) -> int:
        mint = _pubkey(decoded.fields, "mint")
        if decoded.event_name == "CompletePumpAmmMigrationEvent":
            self._pool_facts[_pubkey(decoded.fields, "pool")] = PoolFacts(
                base_mint=mint, quote_mint=_pubkey(decoded.fields, "quote_mint")
            )
        if self._watches.graduated(mint, now=moment, chain=chain) is not None:
            self._counters.graduations += 1
        return 0

    def _on_create_pool(
        self,
        decoded: AdvisoryPumpEvent,
        *,
        chain: Chainstamp,
        moment: datetime,
        provenance: Provenance,
        custody: Custody = NO_CUSTODY,
    ) -> int:
        fields = decoded.fields
        pool = _pubkey(fields, "pool")
        self._pool_facts[pool] = PoolFacts(
            base_mint=_pubkey(fields, "base_mint"), quote_mint=_pubkey(fields, "quote_mint")
        )
        if _pubkey(fields, "quote_mint") != WRAPPED_SOL_MINT:
            self._counters.non_sol_quote_skipped += 1
            return 0
        return self._write_reserves(
            pool=pool,
            # A constant-product PumpSwap pool has no virtual reserves. Recording 0 is the
            # truth and it is exactly why total depth drops 115 -> 85 SOL at migration while
            # price stays continuous; a replay that assumed the curve's virtuals persist
            # would misprice every post-migration fill.
            virtual_sol=0,
            virtual_tokens=0,
            real_sol=_u64(fields, "pool_quote_amount"),
            real_tokens=_u64(fields, "pool_base_amount"),
            moment=moment,
            provenance=provenance,
            chain=chain,
        )

    def _on_amm_trade(
        self,
        entry: AttributedLog,
        decoded: AdvisoryPumpEvent,
        *,
        chain: Chainstamp,
        moment: datetime,
        provenance: Provenance,
        custody: Custody = NO_CUSTODY,
    ) -> int:
        fields = decoded.fields
        pool = _pubkey(fields, "pool")
        facts = self._pool_facts.get(pool)
        if facts is None:
            # PumpSwap trade events name only the pool. Without a CreatePoolEvent or a
            # migration event we do not know which mint traded, and guessing would corrupt
            # every per-token statistic downstream.
            self._counters.unattributed_pool_skipped += 1
            return 0
        if facts.quote_mint != WRAPPED_SOL_MINT:
            self._counters.non_sol_quote_skipped += 1
            return 0
        is_buy = decoded.event_name == "BuyEvent"
        if is_buy:
            token_amount = _u64(fields, "base_amount_out")
            sol_amount = _u64(fields, "quote_amount_in")
        else:
            token_amount = _u64(fields, "base_amount_in")
            sol_amount = _u64(fields, "quote_amount_out")
        trade = Trade(
            mint=facts.base_mint,
            wallet=_pubkey(fields, "user"),
            side=Side.BUY if is_buy else Side.SELL,
            sol_delta_lamports=-sol_amount if is_buy else sol_amount,
            token_delta_raw=token_amount if is_buy else -token_amount,
            pool=pool,
            fee_lamports=_u64(fields, "lp_fee")
            + _u64(fields, "protocol_fee")
            + _u64(fields, "coin_creator_fee")
            + _u64(fields, "buyback_fee"),
            routed_via_frontend=_routed_via_frontend(entry),
            signers=custody.signers,
            fee_payer=custody.fee_payer,
        )
        written = self._write(
            EventKind.TRADE, trade, moment=moment, provenance=provenance, chain=chain
        )
        self._counters.trades += 1
        written += self._write_reserves(
            pool=pool,
            virtual_sol=0,
            virtual_tokens=0,
            real_sol=_u64(fields, "pool_quote_token_reserves"),
            real_tokens=_u64(fields, "pool_base_token_reserves"),
            moment=moment,
            provenance=provenance,
            chain=chain,
        )
        return written

    def _on_withdraw(
        self, decoded: AdvisoryPumpEvent, *, moment: datetime, chain: Chainstamp
    ) -> int:
        """An LP withdrawal that empties the pool is a terminal, observed death.

        This is the only inferred terminal outcome in the recorder, and it is inferred from a
        *positive* on-chain fact (the quote side reached zero), never from absence of
        activity. Silence is what the clock deadline is for.
        """

        fields = decoded.fields
        pool = _pubkey(fields, "pool")
        facts = self._pool_facts.get(pool)
        if facts is None or _u64(fields, "pool_quote_token_reserves") != 0:
            return 0
        if self._watches.died(facts.base_mint, now=moment, chain=chain) is not None:
            self._counters.deaths += 1
        return 0

    # -- writing -------------------------------------------------------------------

    def _write_reserves(
        self,
        *,
        pool: str,
        virtual_sol: int,
        virtual_tokens: int,
        real_sol: int,
        real_tokens: int,
        moment: datetime,
        provenance: Provenance,
        chain: Chainstamp,
    ) -> int:
        reserves = Reserves(
            pool=pool,
            virtual_sol=virtual_sol,
            virtual_tokens=virtual_tokens,
            real_sol=real_sol,
            real_tokens=real_tokens,
        )
        written = self._write(
            EventKind.RESERVE, reserves, moment=moment, provenance=provenance, chain=chain
        )
        self._counters.reserves += 1
        return written

    def _write(
        self,
        kind: EventKind,
        body: Launch | Trade | Reserves | Callout,
        *,
        moment: datetime,
        provenance: Provenance,
        chain: Chainstamp | None,
    ) -> int:
        event = TapeEvent(
            kind=kind,
            observed_at=moment.isoformat(),
            provenance=provenance,
            body=body,
            chain=chain,
        )
        if self._sink(event):
            self._counters.tape_events_written += 1
            return 1
        self._counters.tape_events_deduped += 1
        return 0

    def _learn_pools_from(self, transaction: Mapping[str, Any], pending: _Pending) -> None:
        """Seed pool facts for any pool this transaction trades on but we have not seen created.

        A witnessed ``CreatePoolEvent`` still wins: it is the authoritative statement of the
        pair, and this only fills gaps for pools that predate the recorder.
        """
        for _entry, decoded in pending.events:
            if decoded.event_name not in {"BuyEvent", "SellEvent"}:
                continue
            fields = decoded.fields
            pool = fields.get("pool")
            if not isinstance(pool, str) or pool in self._pool_facts:
                continue
            resolved = resolve_pool_facts(transaction, pool)
            if resolved is None:
                continue
            base, quote = resolved
            self._pool_facts[pool] = PoolFacts(base_mint=base, quote_mint=quote)
            self._counters.pools_resolved_from_balances += 1

    @staticmethod
    def _chainstamp(transaction: Mapping[str, Any]) -> Chainstamp | None:
        inner = transaction.get("transaction")
        signatures = inner.get("signatures") if isinstance(inner, Mapping) else None
        if not isinstance(signatures, Sequence) or not signatures:
            return None
        try:
            slot = int(transaction["slot"])
        except (KeyError, TypeError, ValueError):
            return None
        block_time = transaction.get("blockTime")
        tx_index = transaction.get("transactionIndex")
        try:
            return Chainstamp(
                slot=slot,
                signature=str(signatures[0]),
                block_time=None if block_time is None else int(block_time),
                tx_index=None if tx_index is None else int(tx_index),
            )
        except (TapeError, TypeError, ValueError):
            return None


def _routed_via_frontend(entry: AttributedLog) -> bool | None:
    """The cheap, purely-observable route signal — reported only where it is unambiguous.

    A pump instruction reached by CPI from another program (depth >= 2) is definitively not
    the vanilla frontend: some router, aggregator or bot contract stood between the signer
    and the curve. A *top-level* invocation is ambiguous — the frontend and a plain bot look
    identical at depth 1 — so it is left ``None`` rather than guessed. This field is
    therefore never set True by the recorder: nothing observable in a transaction proves
    frontend origin without a pinned referral/fee-account discriminator we do not have.
    """

    return False if entry.depth >= 2 else None


def graduation_seconds(opened_at: str, closed_at: str) -> float:
    """Chain-time-free helper: seconds between a watch opening and its close."""

    return (datetime.fromisoformat(closed_at) - datetime.fromisoformat(opened_at)).total_seconds()


__all__ = [
    "CREDITS_PER_ENHANCED_CALL",
    "CREDITS_PER_TRANSACTION_PAGE",
    "WRAPPED_SOL_MINT",
    "AttributedLog",
    "AttributedLogs",
    "CreditBudget",
    "CreditBudgetExceeded",
    "PoolFacts",
    "RecorderCounters",
    "RecorderError",
    "TapeRecorder",
    "WatchClose",
    "attribute_program_data",
    "graduation_seconds",
]
