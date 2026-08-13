"""The recorded-tape contract: interfaces #1, #7 and #8 of the Phase 0 manifest.

Everything downstream reads this module — the recorder, every signal study, the replay
harness, off-policy evaluation. It is deliberately authored in one pass rather than fanned
out, because an agent that cannot see this file reconstructs it from prose and verifies
against its own reconstruction.

Four decisions here are load-bearing, and each one is a bug the literature actually shipped:

**Raw amounts are integers in memory and STRINGS on the wire.** JSON numbers are f64, and
f64 loses exactness above 2**53 ~= 9.0e15. A 1e9-supply 6-decimal memecoin is 1e15 raw units
— already within one order of magnitude of the cliff. Serialising a raw amount as a JSON
number is a silent corruption that only shows up on the biggest bags.

**Two clocks, never conflated.** ``Chainstamp.slot``/``block_time`` is when the chain says it
happened; ``observed_at`` is when we saw it. Observer lag is real (a published pump.fun
collector measured median 34.8s, p99 151.6s), so survival analysis must use chain time as the
origin and treat observation as delayed entry, not as t=0.

**Censoring is recorded explicitly, and it is clock-based.** ``WatchWindow`` carries the
wall-clock deadline a mint was watched until. A published collector polled a top-50-newest
endpoint, so each token fell out of view after ~2.77 minutes *because other tokens launched* —
displacement censoring, which is informative censoring, which silently converted a "24-hour
graduation rate" into a 6-minute one. A watch must close on a clock or on a terminal outcome,
never because attention moved elsewhere; recording the window is what makes that auditable.

**Reserves are recorded, not just prices.** Exact replay of an AMM fill needs the pool state,
because impact is a deterministic function of reserves. This is the property that makes a
memecoin backtest higher-fidelity than any equities backtest can be, and it is lost forever if
the recorder stores prices instead of reserves.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

SCHEMA_VERSION: Final[int] = 1

_MINT = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SIGNATURE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{64,90}$")
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")


class TapeError(ValueError):
    """A record violates the tape contract. Always fail closed on this."""


class EventKind(StrEnum):
    LAUNCH = "launch"
    TRADE = "trade"
    RESERVE = "reserve"
    CALLOUT = "callout"
    MIGRATION = "migration"
    WATCH = "watch"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class WatchClose(StrEnum):
    """Why a mint stopped being watched. The censoring reason, explicitly."""

    DEADLINE = "deadline"          # clock expiry — the only benign censoring
    GRADUATED = "graduated"        # terminal outcome observed
    DIED = "died"                  # terminal outcome observed
    OPERATOR = "operator"          # a human stopped it
    DISPLACED = "displaced"        # ATTENTION MOVED ON — informative censoring, a bug
    OBSERVER_LOST = "observer_lost"  # crash/disconnect — informative, must be reported


#: Closing a watch for these reasons biases any survival estimate. `tape_health` counts them
#: and a study that ignores the count is reporting a truncated rate as a full-horizon one.
INFORMATIVE_CLOSES: Final[frozenset[WatchClose]] = frozenset(
    {WatchClose.DISPLACED, WatchClose.OBSERVER_LOST}
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TapeError(message)


def _mint(value: str, *, field: str = "mint") -> str:
    text = str(value).strip()
    _require(bool(_MINT.match(text)), f"{field} is not a base58 Solana address")
    return text


def _ident(value: str, *, field: str) -> str:
    text = str(value).strip()
    _require(bool(_IDENT.match(text)), f"{field} is not a valid identifier")
    return text


def _utc(value: str, *, field: str) -> str:
    """Normalise to a UTC ISO-8601 string. Naive timestamps are refused, not assumed."""
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TapeError(f"{field} is not ISO-8601") from exc
    _require(parsed.tzinfo is not None, f"{field} must carry a timezone")
    return parsed.astimezone(UTC).isoformat()


def _raw(value: Any, *, field: str, allow_negative: bool = False) -> int:
    """Parse a raw base-unit amount. Accepts int or decimal string; refuses float.

    A float here is the silent-corruption path this schema exists to close.
    """
    if isinstance(value, bool | float):
        raise TapeError(f"{field} must be an integer or decimal string, never a float")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise TapeError(f"{field} is not an integer amount") from exc
    if not allow_negative:
        _require(amount >= 0, f"{field} must not be negative")
    return amount


@dataclass(frozen=True, slots=True)
class Chainstamp:
    """When the chain says it happened. The time origin for any survival model."""

    slot: int
    signature: str
    block_time: int | None = None
    tx_index: int | None = None

    def __post_init__(self) -> None:
        _require(self.slot >= 0, "slot must be non-negative")
        _require(
            bool(_SIGNATURE.match(self.signature)), "signature is not base58"
        )
        if self.block_time is not None:
            _require(self.block_time > 0, "block_time must be positive")

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"slot": self.slot, "signature": self.signature}
        if self.block_time is not None:
            out["block_time"] = self.block_time
        if self.tx_index is not None:
            out["tx_index"] = self.tx_index
        return out


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a record came from, precisely enough to detect a gap after the fact."""

    source: str
    fetched_at: str
    cursor: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _ident(self.source, field="source"))
        object.__setattr__(self, "fetched_at", _utc(self.fetched_at, field="fetched_at"))

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source, "fetched_at": self.fetched_at}
        if self.cursor is not None:
            out["cursor"] = self.cursor
        return out


@dataclass(frozen=True, slots=True)
class WatchWindow:
    """The censoring record. A study that ignores this is reporting a truncated rate."""

    mint: str
    opened_at: str
    deadline: str
    closed_at: str | None = None
    close_reason: WatchClose | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mint", _mint(self.mint))
        object.__setattr__(self, "opened_at", _utc(self.opened_at, field="opened_at"))
        object.__setattr__(self, "deadline", _utc(self.deadline, field="deadline"))
        _require(self.deadline > self.opened_at, "deadline must be after opened_at")
        if self.closed_at is not None:
            object.__setattr__(self, "closed_at", _utc(self.closed_at, field="closed_at"))
            _require(
                self.close_reason is not None,
                "a closed watch must record why it closed",
            )
        if self.close_reason is not None:
            _require(self.closed_at is not None, "close_reason needs a closed_at")

    @property
    def is_informatively_censored(self) -> bool:
        return self.close_reason in INFORMATIVE_CLOSES

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mint": self.mint,
            "opened_at": self.opened_at,
            "deadline": self.deadline,
        }
        if self.closed_at is not None:
            out["closed_at"] = self.closed_at
            out["close_reason"] = str(self.close_reason)
        return out


@dataclass(frozen=True, slots=True)
class Reserves:
    """Pool state. What makes an exact replay fill possible.

    pump.fun bonding curves carry virtual reserves that vanish at migration (total depth
    drops 115 -> 85 SOL while price stays continuous), so both must be recorded or the
    replayed fill is wrong on exactly the events that matter most.
    """

    pool: str
    virtual_sol: int
    virtual_tokens: int
    real_sol: int
    real_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool", _mint(self.pool, field="pool"))
        for field_name in ("virtual_sol", "virtual_tokens", "real_sol", "real_tokens"):
            object.__setattr__(
                self, field_name, _raw(getattr(self, field_name), field=field_name)
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "virtual_sol": str(self.virtual_sol),
            "virtual_tokens": str(self.virtual_tokens),
            "real_sol": str(self.real_sol),
            "real_tokens": str(self.real_tokens),
        }


@dataclass(frozen=True, slots=True)
class Trade:
    """One fill, attributed to a wallet.

    ``routed_via_frontend`` is the cheap, purely-observable bot proxy from the Lillo
    pump.fun study: a direct program invocation is a bot, a frontend-routed call is a human.
    It is the only bot signal in the literature that needs no estimation.
    """

    mint: str
    wallet: str
    side: Side
    sol_delta_lamports: int
    token_delta_raw: int
    pool: str | None = None
    fee_lamports: int = 0
    routed_via_frontend: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mint", _mint(self.mint))
        object.__setattr__(self, "wallet", _mint(self.wallet, field="wallet"))
        object.__setattr__(
            self,
            "sol_delta_lamports",
            _raw(self.sol_delta_lamports, field="sol_delta_lamports", allow_negative=True),
        )
        object.__setattr__(
            self,
            "token_delta_raw",
            _raw(self.token_delta_raw, field="token_delta_raw", allow_negative=True),
        )
        object.__setattr__(self, "fee_lamports", _raw(self.fee_lamports, field="fee_lamports"))
        if self.pool is not None:
            object.__setattr__(self, "pool", _mint(self.pool, field="pool"))
        # A buy takes tokens in and sends SOL out; a sell is the mirror. Refusing an
        # inconsistent pair here is what stops a mis-signed tape from reaching a study.
        if self.side is Side.BUY:
            _require(self.token_delta_raw >= 0, "a buy must not decrease the token balance")
        else:
            _require(self.token_delta_raw <= 0, "a sell must not increase the token balance")

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mint": self.mint,
            "wallet": self.wallet,
            "side": str(self.side),
            "sol_delta_lamports": str(self.sol_delta_lamports),
            "token_delta_raw": str(self.token_delta_raw),
            "fee_lamports": str(self.fee_lamports),
        }
        if self.pool is not None:
            out["pool"] = self.pool
        if self.routed_via_frontend is not None:
            out["routed_via_frontend"] = self.routed_via_frontend
        return out


@dataclass(frozen=True, slots=True)
class Launch:
    """A mint coming into existence, with the covariates known at t=0."""

    mint: str
    creator: str
    name: str = ""
    symbol: str = ""
    has_twitter: bool = False
    has_telegram: bool = False
    has_website: bool = False
    initial_virtual_sol: int = 0
    dev_buy_raw: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mint", _mint(self.mint))
        object.__setattr__(self, "creator", _mint(self.creator, field="creator"))
        object.__setattr__(
            self, "initial_virtual_sol", _raw(self.initial_virtual_sol, field="initial_virtual_sol")
        )
        object.__setattr__(self, "dev_buy_raw", _raw(self.dev_buy_raw, field="dev_buy_raw"))

    def to_json(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "creator": self.creator,
            "name": self.name[:64],
            "symbol": self.symbol[:32],
            "has_twitter": self.has_twitter,
            "has_telegram": self.has_telegram,
            "has_website": self.has_website,
            "initial_virtual_sol": str(self.initial_virtual_sol),
            "dev_buy_raw": str(self.dev_buy_raw),
        }


@dataclass(frozen=True, slots=True)
class Callout:
    """An exogenous attention event, resolved to a mint.

    The text itself is not stored — only its hash — so the tape carries no scraped prose.
    ``resolved_from`` records HOW the mint was identified, because a cashtag is a claim
    while a pump/dexscreener URL is an identifier, and pooling the two corrupts the study.
    """

    mint: str
    platform: str
    author: str
    resolved_from: str
    text_sha256: str
    author_followers: int = 0
    engagement: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mint", _mint(self.mint))
        object.__setattr__(self, "platform", _ident(self.platform, field="platform"))
        object.__setattr__(self, "resolved_from", _ident(self.resolved_from, field="resolved_from"))
        _require(
            bool(re.fullmatch(r"[0-9a-f]{64}", self.text_sha256)),
            "text_sha256 must be a hex sha256",
        )
        object.__setattr__(self, "author_followers", _raw(self.author_followers, field="author_followers"))
        object.__setattr__(self, "engagement", _raw(self.engagement, field="engagement"))

    def to_json(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "platform": self.platform,
            "author": self.author[:64],
            "resolved_from": self.resolved_from,
            "text_sha256": self.text_sha256,
            "author_followers": self.author_followers,
            "engagement": self.engagement,
        }


_BODY_TYPES: Final[dict[EventKind, type]] = {
    EventKind.LAUNCH: Launch,
    EventKind.TRADE: Trade,
    EventKind.RESERVE: Reserves,
    EventKind.CALLOUT: Callout,
    EventKind.WATCH: WatchWindow,
}


@dataclass(frozen=True, slots=True)
class TapeEvent:
    """One line of tape. ``event_id`` is a content hash, so replays dedupe across sources."""

    kind: EventKind
    observed_at: str
    provenance: Provenance
    body: Launch | Trade | Reserves | Callout | WatchWindow
    chain: Chainstamp | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at, field="observed_at"))
        expected = _BODY_TYPES.get(self.kind)
        _require(expected is not None, f"unknown event kind {self.kind}")
        _require(
            isinstance(self.body, expected),  # type: ignore[arg-type]
            f"{self.kind} body must be {expected.__name__}",  # type: ignore[union-attr]
        )
        # A trade or reserve reading without a chainstamp cannot be ordered against other
        # events, and unordered events silently corrupt every downstream rolling statistic.
        if self.kind in {EventKind.TRADE, EventKind.RESERVE, EventKind.MIGRATION}:
            _require(self.chain is not None, f"{self.kind} requires a chainstamp")

    @property
    def event_id(self) -> str:
        payload = json.dumps(self.to_json(with_id=False), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json(self, *, with_id: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": str(self.kind),
            "observed_at": self.observed_at,
            "provenance": self.provenance.to_json(),
            "body": self.body.to_json(),
        }
        if self.chain is not None:
            out["chain"] = self.chain.to_json()
        if with_id:
            out["event_id"] = self.event_id
        return out

    def to_jsonl(self) -> str:
        """One line, no newlines inside. JSONL not CSV: memecoin symbols contain commas."""
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class EntityLink:
    """Interface #7 — wallet to entity, with the evidence that justified the merge.

    ``method`` matters as much as the link: co-signing and shared-funder have different
    false-positive profiles, and any study that clusters before splitting must be able to
    report which heuristic did the work.
    """

    wallet: str
    entity_id: str
    method: str
    confidence: float
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", _mint(self.wallet, field="wallet"))
        object.__setattr__(self, "entity_id", _ident(self.entity_id, field="entity_id"))
        object.__setattr__(self, "method", _ident(self.method, field="method"))
        _require(0.0 <= self.confidence <= 1.0, "confidence must be in [0, 1]")

    def to_json(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "entity_id": self.entity_id,
            "method": self.method,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class PropensityRecord:
    """Interface #8 — the decision log that makes our own trades counterfactual-ready.

    Logging the probability that generated an action, AT DECISION TIME, is what turns every
    trade into a small randomised experiment: off-policy evaluation, doubly-robust estimates
    and "what would policy B have earned on policy A's data" all require it, and none of it
    is reconstructible after the fact. Without this the tape is merely observational.
    """

    decision_id: str
    decided_at: str
    policy_id: str
    action: str
    propensity: float
    features_sha256: str
    envelope_verdict: str
    mint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _ident(self.decision_id, field="decision_id"))
        object.__setattr__(self, "decided_at", _utc(self.decided_at, field="decided_at"))
        object.__setattr__(self, "policy_id", _ident(self.policy_id, field="policy_id"))
        object.__setattr__(self, "action", _ident(self.action, field="action"))
        object.__setattr__(
            self, "envelope_verdict", _ident(self.envelope_verdict, field="envelope_verdict")
        )
        # A zero propensity means the logging policy could never have taken this action, so
        # no importance-weighted estimator can use it; refusing it here keeps the tape sound.
        _require(0.0 < self.propensity <= 1.0, "propensity must be in (0, 1]")
        _require(
            bool(re.fullmatch(r"[0-9a-f]{64}", self.features_sha256)),
            "features_sha256 must be a hex sha256",
        )
        if self.mint is not None:
            object.__setattr__(self, "mint", _mint(self.mint))

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision_id": self.decision_id,
            "decided_at": self.decided_at,
            "policy_id": self.policy_id,
            "action": self.action,
            "propensity": self.propensity,
            "features_sha256": self.features_sha256,
            "envelope_verdict": self.envelope_verdict,
        }
        if self.mint is not None:
            out["mint"] = self.mint
        return out


@dataclass(frozen=True, slots=True)
class TapeHealth:
    """Coverage against an independent count, plus the censoring audit.

    ``complete`` is deliberately strict: a study run on an incomplete tape reports a
    truncated rate as a full-horizon one, which is the single most consequential error in
    the published pump.fun literature.
    """

    observed_trades: int
    reference_trades: int
    watches_closed: int
    watches_informatively_censored: int

    @property
    def coverage(self) -> float:
        if self.reference_trades <= 0:
            return 0.0
        return self.observed_trades / self.reference_trades

    @property
    def censoring_rate(self) -> float:
        if self.watches_closed <= 0:
            return 0.0
        return self.watches_informatively_censored / self.watches_closed

    @property
    def complete(self) -> bool:
        return self.coverage >= 0.98 and self.censoring_rate == 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "observed_trades": self.observed_trades,
            "reference_trades": self.reference_trades,
            "coverage": self.coverage,
            "watches_closed": self.watches_closed,
            "watches_informatively_censored": self.watches_informatively_censored,
            "censoring_rate": self.censoring_rate,
            "complete": self.complete,
        }


def tape_health(
    *, observed_trades: int, reference_trades: int, watches: Sequence[WatchWindow]
) -> TapeHealth:
    closed = [w for w in watches if w.closed_at is not None]
    return TapeHealth(
        observed_trades=observed_trades,
        reference_trades=reference_trades,
        watches_closed=len(closed),
        watches_informatively_censored=sum(1 for w in closed if w.is_informatively_censored),
    )


def parse_amount(value: Any, *, field: str = "amount") -> int:
    """Public re-export of the raw-amount parser, for recorders and studies."""
    return _raw(value, field=field, allow_negative=True)


def event_from_json(payload: Mapping[str, Any]) -> TapeEvent:
    """Rebuild an event from a tape line, validating on the way in.

    Reading is where a corrupt tape must be caught: a study that silently accepts a
    malformed line is worse than one that crashes, because it publishes a number.
    """
    _require(isinstance(payload, Mapping), "tape line must be an object")
    version = payload.get("schema_version")
    _require(version == SCHEMA_VERSION, f"unsupported schema_version {version!r}")
    try:
        kind = EventKind(str(payload["kind"]))
    except (KeyError, ValueError) as exc:
        raise TapeError("tape line has no valid kind") from exc
    body_raw = payload.get("body")
    _require(isinstance(body_raw, Mapping), "tape line has no body object")
    chain_raw = payload.get("chain")
    chain = (
        Chainstamp(
            slot=int(chain_raw["slot"]),
            signature=str(chain_raw["signature"]),
            block_time=chain_raw.get("block_time"),
            tx_index=chain_raw.get("tx_index"),
        )
        if isinstance(chain_raw, Mapping)
        else None
    )
    prov_raw = payload.get("provenance")
    _require(isinstance(prov_raw, Mapping), "tape line has no provenance")
    provenance = Provenance(
        source=str(prov_raw["source"]),
        fetched_at=str(prov_raw["fetched_at"]),
        cursor=prov_raw.get("cursor"),
    )
    body = _body_from_json(kind, body_raw)
    return TapeEvent(
        kind=kind,
        observed_at=str(payload["observed_at"]),
        provenance=provenance,
        body=body,
        chain=chain,
    )


def _body_from_json(kind: EventKind, raw: Mapping[str, Any]) -> Any:
    if kind is EventKind.TRADE:
        return Trade(
            mint=str(raw["mint"]),
            wallet=str(raw["wallet"]),
            side=Side(str(raw["side"])),
            sol_delta_lamports=parse_amount(raw["sol_delta_lamports"], field="sol_delta_lamports"),
            token_delta_raw=parse_amount(raw["token_delta_raw"], field="token_delta_raw"),
            pool=raw.get("pool"),
            fee_lamports=parse_amount(raw.get("fee_lamports", 0), field="fee_lamports"),
            routed_via_frontend=raw.get("routed_via_frontend"),
        )
    if kind is EventKind.RESERVE:
        return Reserves(
            pool=str(raw["pool"]),
            virtual_sol=parse_amount(raw["virtual_sol"], field="virtual_sol"),
            virtual_tokens=parse_amount(raw["virtual_tokens"], field="virtual_tokens"),
            real_sol=parse_amount(raw["real_sol"], field="real_sol"),
            real_tokens=parse_amount(raw["real_tokens"], field="real_tokens"),
        )
    if kind is EventKind.LAUNCH:
        return Launch(
            mint=str(raw["mint"]),
            creator=str(raw["creator"]),
            name=str(raw.get("name", "")),
            symbol=str(raw.get("symbol", "")),
            has_twitter=bool(raw.get("has_twitter", False)),
            has_telegram=bool(raw.get("has_telegram", False)),
            has_website=bool(raw.get("has_website", False)),
            initial_virtual_sol=parse_amount(
                raw.get("initial_virtual_sol", 0), field="initial_virtual_sol"
            ),
            dev_buy_raw=parse_amount(raw.get("dev_buy_raw", 0), field="dev_buy_raw"),
        )
    if kind is EventKind.CALLOUT:
        return Callout(
            mint=str(raw["mint"]),
            platform=str(raw["platform"]),
            author=str(raw["author"]),
            resolved_from=str(raw["resolved_from"]),
            text_sha256=str(raw["text_sha256"]),
            author_followers=parse_amount(raw.get("author_followers", 0), field="author_followers"),
            engagement=parse_amount(raw.get("engagement", 0), field="engagement"),
        )
    if kind is EventKind.WATCH:
        reason = raw.get("close_reason")
        return WatchWindow(
            mint=str(raw["mint"]),
            opened_at=str(raw["opened_at"]),
            deadline=str(raw["deadline"]),
            closed_at=raw.get("closed_at"),
            close_reason=WatchClose(str(reason)) if reason is not None else None,
        )
    raise TapeError(f"no body decoder for {kind}")
