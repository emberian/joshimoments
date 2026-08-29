"""Birth-slot feature extraction, replicated exactly from ``studies/operator_crime.py``.

THE PARITY OBLIGATION
---------------------
The screen B1 validated is a conjunction of five birth-time gates whose inputs are
defined by SQL in ``studies/operator_crime.py``. This module re-derives those inputs
from Helius ``getTransaction`` responses instead of the bulk parquet corpus, and the
whole point of the file is that the two derivations are THE SAME FUNCTION on the same
chain facts. Each definition below cites the SQL it mirrors; the parity test in
``tests/test_dregg_screen.py`` runs this extractor over real corpus birth slots
(reconstructed into Helius wire shape) and asserts equality against the study's own
``panel.parquet`` row. A drifted feature here does not crash — it silently detaches the
live verdicts from the validated precision numbers, which is the one failure this lane
is not allowed to have.

The corpus identities being mirrored:

* a LEDGER row is a per-(transaction, token-account) net balance change:
  ``delta = sum(post.amount) - sum(pre.amount)`` matched by ``account_index``, with a
  ``pre`` leg that has no ``post`` (closed account) appended negated, zero deltas
  dropped (``LEDGER_SQL``). Helius ``meta.pre/postTokenBalances`` carry exactly those
  legs, with ``amount`` as a STRING of raw units — parsed as int, never float, because
  the corpus docstring forbids exactly that float.
* BIRTH: the create transaction's legs, ranked by delta descending. Rank 1 is the
  curve seed and its owner is ``curve_owner``; rank 2, if positive, is the dev buy and
  its owner is ``deployer`` (``BIRTH_SQL``). Membership (``BORN``) is
  ``minted_raw == 1e15 AND decimals == 6`` — net supply minted from nothing, invariant
  to the dev buy. Anything else (mayhem mode, 9-decimal impostors wearing the ``pump``
  suffix) is OUT of the validated population and says so.
* SNIPERS: every owner with a net POSITIVE delta summed across the whole birth slot,
  other than the curve owner (``SNIPERS_SQL``). The deployer IS a sniper when it dev
  buys — the corpus counts it, so we count it. Failed transactions are excluded: every
  row of the corpus was a success (``err = ''`` on all 106,639,238 rows), so a reverted
  same-slot buy must not become a phantom sniper here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# -- constants lifted verbatim from studies/operator_crime.py --------------------------

PUMP_SUPPLY_RAW = 1_000_000_000_000_000  # 1e9 tokens at 6 decimals
PUMP_DECIMALS = 6

# The five gates of the validated CLEAN screen (cmd_screen), with the study's names.
GATE_MAX_SNIPERS = 1  # "no bundle at birth (n_snipers <= 1)"
GATE_MAX_DEV_BUY_SHARE = 0.02  # "dev buy under 2% of supply"
# prior_rips == 0, prior_dumps == 0, sniper_prior_max == 0 complete the conjunction.


@dataclass(frozen=True, slots=True)
class Leg:
    """One netted token-account leg, the unit LEDGER_SQL calls a balance change."""

    owner: str
    delta_raw: int
    decimals: int


def tx_success(tx: Mapping[str, Any]) -> bool:
    """Corpus membership check: every corpus row was a success (``err = ''``)."""

    meta = tx.get("meta") or {}
    return meta.get("err") is None


def mint_legs(tx: Mapping[str, Any], mint: str) -> list[Leg]:
    """Net per-token-account deltas for ``mint`` in one transaction.

    Mirrors LEDGER_SQL's inside-the-row netting: subtract the matching ``pre`` from
    every ``post`` by ``accountIndex``, append pre-only legs negated, drop zeros.
    Amounts are Helius strings of raw units; ``int()`` keeps them exact. A leg whose
    balance entry carries no ``owner`` cannot be attributed and is dropped — the corpus
    tape always carried owners, so on parity data this branch never fires.
    """

    meta = tx.get("meta") or {}
    pre = {
        b["accountIndex"]: b
        for b in meta.get("preTokenBalances") or []
        if b.get("mint") == mint
    }
    post = {
        b["accountIndex"]: b
        for b in meta.get("postTokenBalances") or []
        if b.get("mint") == mint
    }
    legs: list[Leg] = []
    for idx, b in post.items():
        owner = b.get("owner")
        if not owner:
            continue
        amount = int(b["uiTokenAmount"]["amount"])
        before = int(pre[idx]["uiTokenAmount"]["amount"]) if idx in pre else 0
        delta = amount - before
        if delta != 0:
            legs.append(Leg(owner=owner, delta_raw=delta, decimals=int(b["uiTokenAmount"]["decimals"])))
    for idx, b in pre.items():
        if idx in post:
            continue
        owner = b.get("owner")
        if not owner:
            continue
        amount = int(b["uiTokenAmount"]["amount"])
        if amount != 0:
            legs.append(Leg(owner=owner, delta_raw=-amount, decimals=int(b["uiTokenAmount"]["decimals"])))
    return legs


@dataclass(frozen=True, slots=True)
class BirthFeatures:
    """Everything the screen reads from the birth slot, in the study's vocabulary."""

    mint: str
    born_standard: bool  # BORN: minted_raw == 1e15 AND decimals == 6
    minted_raw: int
    decimals: int | None
    curve_owner: str | None  # BIRTH_SQL rank-1 leg owner (the bonding curve account)
    deployer: str | None  # BIRTH_SQL rank-2 positive leg owner; None when no dev buy
    dev_buy_raw: int  # coalesce(rank-2 delta, 0)
    n_birth_legs: int
    n_snipers: int  # SNIPERS_SQL: net-positive owners in the birth slot, ex curve
    snipers: tuple[str, ...]  # the sniper set itself (deployer INCLUDED, as the corpus does)
    partial: bool = False  # true when the same-slot tx list was capped — n_snipers is a floor
    notes: tuple[str, ...] = field(default=())

    @property
    def dev_buy_share(self) -> float:
        return self.dev_buy_raw / PUMP_SUPPLY_RAW

    @property
    def snipers_ex_deployer(self) -> tuple[str, ...]:
        """The crew-match set. cmd_graph drops the deployer from its own coins' sniper
        sets because the dev buy puts it there BY CONSTRUCTION — same-deployer overlap
        would be positive on an empty hypothesis. Crew matching inherits that rule."""

        return tuple(s for s in self.snipers if s != self.deployer)


def extract_birth_features(
    mint: str,
    create_tx: Mapping[str, Any],
    same_slot_txs: Sequence[Mapping[str, Any]] = (),
    *,
    partial: bool = False,
) -> BirthFeatures:
    """The feature builder. ``create_tx`` is the create transaction (known from the
    PumpPortal event's signature — which is also why no first-key scan is needed: the
    mint cannot be touched before it exists, so the create IS the first transaction).
    ``same_slot_txs`` are the OTHER successful transactions of the birth slot that
    touch the mint; pass what hydration found, with ``partial=True`` if it was capped.
    """

    notes: list[str] = []
    birth = sorted(mint_legs(create_tx, mint), key=lambda leg: -leg.delta_raw)
    minted_raw = sum(leg.delta_raw for leg in birth)
    decimals = birth[0].decimals if birth else None
    born = minted_raw == PUMP_SUPPLY_RAW and decimals == PUMP_DECIMALS
    curve_owner = birth[0].owner if birth else None
    deployer: str | None = None
    dev_buy_raw = 0
    if len(birth) >= 2 and birth[1].delta_raw > 0:
        deployer = birth[1].owner
        dev_buy_raw = birth[1].delta_raw

    # SNIPERS_SQL: sum per owner over the WHOLE slot (create included), ex curve owner.
    by_owner: dict[str, int] = {}
    for tx in (create_tx, *same_slot_txs):
        if not tx_success(tx):
            notes.append("skipped_failed_tx")
            continue
        for leg in mint_legs(tx, mint):
            by_owner[leg.owner] = by_owner.get(leg.owner, 0) + leg.delta_raw
    snipers = tuple(sorted(o for o, d in by_owner.items() if d > 0 and o != curve_owner))

    return BirthFeatures(
        mint=mint,
        born_standard=born,
        minted_raw=minted_raw,
        decimals=decimals,
        curve_owner=curve_owner,
        deployer=deployer,
        dev_buy_raw=dev_buy_raw,
        n_birth_legs=len(birth),
        n_snipers=len(snipers),
        snipers=snipers,
        partial=partial,
        notes=tuple(notes),
    )


# -- the cheap (websocket-only) layer --------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheapFeatures:
    """What the PumpPortal create frame alone can say, before any Helius spend.

    ``dev_buy_share`` here comes from the vendor's ``initialBuy`` — a vendor FLOAT
    (see shitcoims_scalper.firehose's money warning), printed in whole tokens to six
    decimals, which happens to be raw/1e6 exactly, so for a 2%-of-supply threshold the
    float is safely far from the rounding cliff. It is still marked ``ws_vendor_float``
    and replaced by the chain-exact value whenever the launch is hydrated.
    """

    mint: str
    creator: str | None  # traderPublicKey — known live even with NO dev buy,
    #                       which the corpus's deployer (a dev-buy artifact) is not
    bonding_curve: str | None
    dev_buy_raw_est: int
    name: str | None
    symbol: str | None
    is_mayhem_mode: bool
    pool: str | None
    signature: str | None

    @property
    def dev_buy_share_est(self) -> float:
        return self.dev_buy_raw_est / PUMP_SUPPLY_RAW


def cheap_features_from_event(payload: Mapping[str, Any]) -> CheapFeatures:
    raw_buy = payload.get("initialBuy") or 0
    try:
        dev_buy_raw_est = round(float(raw_buy) * 10**PUMP_DECIMALS)
    except (TypeError, ValueError):
        dev_buy_raw_est = 0
    return CheapFeatures(
        mint=str(payload.get("mint", "")),
        creator=payload.get("traderPublicKey"),
        bonding_curve=payload.get("bondingCurveKey"),
        dev_buy_raw_est=dev_buy_raw_est,
        name=payload.get("name"),
        symbol=payload.get("symbol"),
        is_mayhem_mode=bool(payload.get("is_mayhem_mode", False)),
        pool=payload.get("pool"),
        signature=payload.get("signature"),
    )
